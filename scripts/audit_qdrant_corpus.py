"""Audit Qdrant corpus sources and point payloads without exporting vectors."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

from qdrant_client import QdrantClient


# Main is part of the operational tooling layer.
def main() -> None:
    """Scroll one collection and write source-level counts and fingerprints."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("QDRANT_URL"))
    parser.add_argument("--api-key", default=os.getenv("QDRANT_API_KEY"))
    parser.add_argument(
        "--collection",
        default=os.getenv("QDRANT_COLLECTION", "new_adv_rag_documents"),
    )
    parser.add_argument(
        "--output",
        default="seed/manifests/aws_qdrant_corpus_audit.json",
    )
    args = parser.parse_args()
    if not args.url:
        raise SystemExit("QDRANT_URL is required")

    client = QdrantClient(url=args.url, api_key=args.api_key or None, timeout=60)
    texts_by_source: dict[str, list[str]] = defaultdict(list)
    payload_fields: set[str] = set()
    missing_source_points = 0
    offset = None
    total_points = 0
    while True:
        points, offset = client.scroll(
            collection_name=args.collection,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            payload_fields.update(payload)
            source = str(payload.get("source") or "").strip()
            text = str(payload.get("text") or "")
            if source:
                texts_by_source[source].append(text)
            else:
                missing_source_points += 1
            total_points += 1
        if offset is None:
            break

    sources = []
    duplicate_chunk_count = 0
    for source, texts in sorted(texts_by_source.items()):
        text_hashes = [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]
        unique_text_hashes = sorted(set(text_hashes))
        duplicate_chunk_count += len(text_hashes) - len(unique_text_hashes)
        document_fingerprint = hashlib.sha256(
            "\n".join(unique_text_hashes).encode("utf-8")
        ).hexdigest()
        sources.append({
            "source": source,
            "point_count": len(texts),
            "unique_chunk_count": len(unique_text_hashes),
            "document_fingerprint": document_fingerprint,
        })

    report = {
        "collection": args.collection,
        "total_points": total_points,
        "unique_sources": len(sources),
        "missing_source_points": missing_source_points,
        "duplicate_chunks_within_source": duplicate_chunk_count,
        "payload_fields": sorted(payload_fields),
        "sources": sources,
        "limitations": [
            "Qdrant stores source and text but no document content hash in this collection.",
            "Identical source/text chunks overwrite by deterministic point ID, so original upload counts cannot be reconstructed exactly.",
        ],
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Collection: {args.collection}")
    print(f"Total points: {total_points}")
    print(f"Unique sources: {len(sources)}")
    print(f"Points missing source: {missing_source_points}")
    print(f"Duplicate chunks within source: {duplicate_chunk_count}")
    print(f"Payload fields: {', '.join(sorted(payload_fields))}")
    print(f"Report: {output_path}")


if __name__ == "__main__":
    main()
