from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader


_PLAIN_TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm"}
_PDF_EXTENSION = ".pdf"
_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 100


class DocumentProcessor:
    def process_document(self, file_path: str) -> list[dict]:
        suffix = Path(file_path).suffix.lower()

        if suffix in _PLAIN_TEXT_EXTENSIONS:
            return self._process_plain(file_path)

        if suffix == _PDF_EXTENSION:
            return self._process_pdf_pypdf(file_path)

        return self._process_docling(file_path)

    def _process_plain(self, file_path: str) -> list[dict]:
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

    def _process_pdf_pypdf(self, file_path: str) -> list[dict]:
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
        chunks: list[dict] = []
        start = 0

        while start < len(text):
            end = start + _CHUNK_SIZE
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
            start += _CHUNK_SIZE - _CHUNK_OVERLAP

        return chunks

    def _normalize_whitespace(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()