from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

_PLAIN_TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm"}
_PDF_EXTENSION = ".pdf"
_DOCX_EXTENSION = ".docx"
_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 100


# Learner Note: Document processor is part of the document ingestion pipeline.
class DocumentProcessor:
    # Learner note: Handles process document as an isolated ingestion step so failures are easier to diagnose.
    """Represent document processor within the document ingestion pipeline.

    Learner Note:
        This class groups state and behavior behind a clear, testable contract.
    """
    def process_document(self, file_path: str) -> list[dict]:
        """Perform process document for the document ingestion pipeline.

        Learner Note:
            This function keeps the responsibility explicit for callers, tests, and operators.
        """
        suffix = Path(file_path).suffix.lower()

        if suffix in _PLAIN_TEXT_EXTENSIONS:
            return self._process_plain(file_path)

        if suffix == _PDF_EXTENSION:
            return self._process_pdf_pypdf(file_path)

        if suffix == _DOCX_EXTENSION:
            return self._process_docx_python_docx(file_path)

        return self._process_docling(file_path)

    # Learner note: Encapsulates process plain so this responsibility can be understood, tested, and changed independently.
    def _process_plain(self, file_path: str) -> list[dict]:
        """Support the document ingestion pipeline by performing process plain.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
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

    # Learner note: Encapsulates process docling so this responsibility can be understood, tested, and changed independently.
    def _process_docling(self, file_path: str) -> list[dict]:
        """Support the document ingestion pipeline by performing process docling.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
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

    # Learner note: Encapsulates process docx python docx so this responsibility can be understood, tested, and changed independently.
    def _process_docx_python_docx(self, file_path: str) -> list[dict]:
        """Support the document ingestion pipeline by performing process docx python docx.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
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

    # Learner note: Encapsulates process pdf pypdf so this responsibility can be understood, tested, and changed independently.
    def _process_pdf_pypdf(self, file_path: str) -> list[dict]:
        """Support the document ingestion pipeline by performing process pdf pypdf.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
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

    # Learner note: Encapsulates chunk text so this responsibility can be understood, tested, and changed independently.
    def _chunk_text(
        self,
        text: str,
        source_name: str,
        source_path: str,
        page_number: int | None,
    ) -> list[dict]:
        """Support the document ingestion pipeline by performing chunk text.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
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

    # Learner note: Encapsulates normalize whitespace so this responsibility can be understood, tested, and changed independently.
    def _normalize_whitespace(self, text: str) -> str:
        """Support the document ingestion pipeline by performing normalize whitespace.

        Learner Note:
            Keeping this helper focused makes the surrounding workflow easier to test and maintain.
        """
        return re.sub(r"\s+", " ", text).strip()
