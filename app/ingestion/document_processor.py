from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

_PLAIN_TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm"}
_PDF_EXTENSION = ".pdf"
_DOCX_EXTENSION = ".docx"
_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 100


class DocumentProcessor:
    """Convert a source document on disk into a list of ingestion-ready text chunks.

    Dispatches to format-specific extraction logic (plain text/HTML, PDF, DOCX)
    based on file extension, with Docling used both as the catch-all converter
    for unrecognized formats and as a fallback when a format-specific extractor
    fails. Every extraction path funnels through ``_chunk_text`` (or Docling's
    own chunker) so callers always get back a flat list of chunk dicts with
    ``text``, ``source``, ``source_name``, ``source_path``, and ``page_number``.
    """

    def process_document(self, file_path: str) -> list[dict]:
        """Extract and chunk ``file_path`` based on its extension.

        Routes plain text/markdown/HTML files to ``_process_plain``, PDFs to
        ``_process_pdf_pypdf``, DOCX files to ``_process_docx_python_docx``,
        and any other extension to ``_process_docling``. Returns a list of
        chunk dicts.
        """
        suffix = Path(file_path).suffix.lower()

        if suffix in _PLAIN_TEXT_EXTENSIONS:
            return self._process_plain(file_path)

        if suffix == _PDF_EXTENSION:
            return self._process_pdf_pypdf(file_path)

        if suffix == _DOCX_EXTENSION:
            return self._process_docx_python_docx(file_path)

        return self._process_docling(file_path)

    def _process_plain(self, file_path: str) -> list[dict]:
        """Read a plain text/markdown/HTML file and split it into chunks.

        Strips HTML tags and entities when the extension is ``.html``/``.htm``,
        normalizes whitespace, and returns ``[]`` if nothing remains. Page
        numbers are not applicable here, so ``page_number`` is always ``None``.
        """
        path = Path(file_path)
        source_name = path.name

        text = path.read_text(encoding="utf-8", errors="replace")

        if path.suffix.lower() in {".html", ".htm"}:
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"&[a-zA-Z]+;", " ", text)

        text = self._normalize_whitespace(text)
        if not text:
            return []

        return self._chunk_text(
            text=text,
            source_name=source_name,
            source_path=str(path),
            page_number=None,
        )

    def _process_docling(self, file_path: str) -> list[dict]:
        """Convert and chunk a document using Docling's ``DocumentConverter``/``HybridChunker``.

        Acts as the catch-all handler for formats without a dedicated extractor,
        and as the fallback for DOCX/PDF extraction failures. Page numbers are
        pulled from chunk provenance metadata when available. If Docling raises
        or yields no chunks, falls back to ``_process_pdf_pypdf``.
        """
        path = Path(file_path)
        source_name = path.name

        try:
            from docling.chunking import HybridChunker
            from docling.document_converter import DocumentConverter

            converter = DocumentConverter()
            chunker = HybridChunker()

            result = converter.convert(file_path)
            doc = result.document

            chunks: list[dict] = []
            for chunk in chunker.chunk(doc):
                text = self._normalize_whitespace(chunk.text)
                if not text:
                    continue

                page_number = None
                if hasattr(chunk, "meta") and hasattr(chunk.meta, "doc_items"):
                    items = chunk.meta.doc_items
                    if items and hasattr(items[0], "prov") and items[0].prov:
                        page_number = items[0].prov.page_no

                chunks.append(
                    {
                        "text": text,
                        "source": source_name,
                        "source_name": source_name,
                        "source_path": str(path),
                        "page_number": page_number,
                    }
                )

            if chunks:
                return chunks
        except Exception:
            pass

        return self._process_pdf_pypdf(file_path)

    def _process_docx_python_docx(self, file_path: str) -> list[dict]:
        """Extract and chunk a ``.docx`` file's paragraph text using python-docx.

        Joins all paragraph text, normalizes whitespace, and chunks the result.
        Falls back to ``_process_docling`` if python-docx is unavailable or
        extraction raises.
        """
        path = Path(file_path)
        source_name = path.name

        try:
            from docx import Document

            document = Document(file_path)
            text = self._normalize_whitespace(
                " ".join(paragraph.text for paragraph in document.paragraphs)
            )
            if not text:
                return []

            return self._chunk_text(
                text=text,
                source_name=source_name,
                source_path=str(path),
                page_number=None,
            )
        except Exception:
            return self._process_docling(file_path)

    def _process_pdf_pypdf(self, file_path: str) -> list[dict]:
        """Extract text per page with pypdf and chunk each page independently.

        Chunking page-by-page (rather than concatenating the whole document
        first) keeps ``page_number`` accurate on every resulting chunk. Pages
        with no extractable text are skipped.
        """
        path = Path(file_path)
        source_name = path.name
        reader = PdfReader(file_path)

        chunks: list[dict] = []
        for page_index, page in enumerate(reader.pages, start=1):
            text = self._normalize_whitespace(page.extract_text() or "")
            if not text:
                continue

            page_chunks = self._chunk_text(
                text=text,
                source_name=source_name,
                source_path=str(path),
                page_number=page_index,
            )
            chunks.extend(page_chunks)

        return chunks

    def _chunk_text(
        self,
        text: str,
        source_name: str,
        source_path: str,
        page_number: int | None,
    ) -> list[dict]:
        """Split ``text`` into overlapping chunks of roughly ``_CHUNK_SIZE`` characters.

        For each window, prefers to end the chunk at the last sentence boundary
        found within the final ~35% of the window (``_CHUNK_SIZE * 0.65`` to the
        hard end); if no sentence boundary exists, falls back to the last word
        boundary; if neither exists, cuts at the hard limit. The next chunk then
        backs up by ``_CHUNK_OVERLAP`` characters (again snapping forward to the
        nearest sentence boundary within that overlap window when possible) so
        consecutive chunks share trailing/leading context. Empty chunks are
        dropped. Returns a list of dicts with ``text``, ``source``,
        ``source_name``, ``source_path``, and ``page_number`` (as passed in,
        unchanged per chunk).
        """
        chunks: list[dict] = []
        start = 0

        while start < len(text):
            hard_end = min(start + _CHUNK_SIZE, len(text))
            end = hard_end
            if hard_end < len(text):
                search_floor = start + int(_CHUNK_SIZE * 0.65)
                sentence_ends = [
                    match.end()
                    for match in re.finditer(r"[.!?](?=\s|[A-Z]|$)", text[search_floor:hard_end])
                ]
                if sentence_ends:
                    end = search_floor + sentence_ends[-1]
                else:
                    word_end = text.rfind(" ", search_floor, hard_end)
                    if word_end > start:
                        end = word_end

            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(
                    {
                        "text": chunk_text,
                        "source": source_name,
                        "source_name": source_name,
                        "source_path": source_path,
                        "page_number": page_number,
                    }
                )
            if end >= len(text):
                break

            overlap_target = max(end - _CHUNK_OVERLAP, start + 1)
            sentence_starts = [
                match.end()
                for match in re.finditer(r"[.!?](?=\s|[A-Z]|$)", text[start:overlap_target])
            ]
            next_start = start + sentence_starts[-1] if sentence_starts else overlap_target
            while next_start < end and text[next_start].isspace():
                next_start += 1
            start = next_start if next_start > start else end

        return chunks

    def _normalize_whitespace(self, text: str) -> str:
        """Collapse any run of whitespace to a single space and trim the ends."""
        return re.sub(r"\s+", " ", text).strip()
