import argparse
import os
import random
import shutil
import time
from pathlib import Path

import psycopg2
from loguru import logger

from app.config import settings
from app.middleware.auth import hash_password


DATABASE_URL = os.getenv("DATABASE_URL", settings.database_url)
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "seed" / "migrations"
DOCS_DIR = Path(__file__).resolve().parent.parent / "seed" / "docs"
DOC_CACHE_DIR = Path(".cache/storage")

DEMO_USERS = [
    ("agent@demo.local", "agent123", False),
    ("admin@demo.local", "admin123", True),
]

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}
SAMPLE_SEED = 42


def _collect_files(subdir: str) -> list[Path]:
    root = DOCS_DIR / subdir
    if not root.exists():
        return []
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and p.name != ".gitkeep"
    )


def _select_corpus(
    noise_sample_size: int | str,
    true_sample_size: int | str = "auto",
) -> tuple[list[Path], list[Path]]:
    true_files = _collect_files("true_data")
    all_noisy = _collect_files("noisy_data")

    legacy_files = [
        p
        for p in DOCS_DIR.iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and p.name != ".gitkeep"
    ]

    if legacy_files:
        logger.info("Found {} legacy top-level docs (treating as true signal)", len(legacy_files))

    true_files = legacy_files + true_files

    if true_files:
        if true_sample_size == "all":
            logger.info("Using ALL true_data: {} files", len(true_files))
        elif true_sample_size == "auto":
            n_true = max(1, len(true_files) // 10)
            rng = random.Random(SAMPLE_SEED)
            true_files = sorted(rng.sample(true_files, n_true))
            logger.info("Sampling 10% of true_data: {}/{} files", n_true, n_true * 10)
        else:
            n_true = min(int(true_sample_size), len(true_files))
            rng = random.Random(SAMPLE_SEED)
            true_files = sorted(rng.sample(true_files, n_true))
            logger.info("Sampling {} of true_data files", n_true)

    if noise_sample_size == "all":
        noisy_files = all_noisy
    elif noise_sample_size == "auto":
        n = max(1, len(all_noisy) // 10)
        rng = random.Random(SAMPLE_SEED)
        noisy_files = sorted(rng.sample(all_noisy, n))
    elif noise_sample_size == 0:
        noisy_files = []
    else:
        n = int(noise_sample_size)
        if n >= len(all_noisy):
            noisy_files = all_noisy
        else:
            rng = random.Random(SAMPLE_SEED)
            noisy_files = sorted(rng.sample(all_noisy, n))
    return true_files, noisy_files


def _clear_doc_cache_storage() -> None:
    if DOC_CACHE_DIR.exists():
        shutil.rmtree(DOC_CACHE_DIR, ignore_errors=True)
    DOC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Cleared document metadata cache at {}", DOC_CACHE_DIR)


def seed_docs(
    noise_sample_size: int | str = "auto",
    true_sample_size: int | str = "auto",
    wipe: bool = False,
) -> dict:
    from app.services.ingestion_service import IngestionService
    from app.services.vector_store import recreate_collection

    service = IngestionService()
    true_files, noisy_files = _select_corpus(noise_sample_size, true_sample_size)
    total = len(true_files) + len(noisy_files)

    logger.info("=" * 60)
    logger.info("INGESTION PLAN")
    logger.info("  true_data  : {} files (full signal)", len(true_files))
    logger.info("  noisy_data : {} files (sample={})", len(noisy_files), noise_sample_size)
    logger.info("  total      : {} files", total)
    logger.info("=" * 60)

    if wipe:
        logger.info("Recreating Qdrant collection before ingest (--wipe enabled)...")
        recreate_collection()
        _clear_doc_cache_storage()

    if total == 0:
        logger.warning("No files found to ingest - did you populate seed/docs?")
        return {"true_ingested": 0, "noisy_ingested": 0, "failed": 0, "chunks": 0}

    counters = {"true_ingested": 0, "noisy_ingested": 0, "failed": 0, "chunks": 0}
    t0 = time.time()

    for idx, src in enumerate(true_files, start=1):
        _ingest_one(service, src, idx, total, counters, force_reindex=wipe)
        if counters["chunks"] > 0 and idx == len(true_files):
            logger.info("All {} true (signal) files done", len(true_files))

    for jdx, src in enumerate(noisy_files, start=1):
        idx = len(true_files) + jdx
        _ingest_one(service, src, idx, total, counters, force_reindex=wipe)

    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("INGESTION COMPLETE in {:.1f} min", elapsed / 60)
    logger.info("  true_data ingested   : {}", counters["true_ingested"])
    logger.info("  noisy_data ingested  : {}", counters["noisy_ingested"])
    logger.info("  failed (or skipped)  : {}", counters["failed"])
    logger.info("  total chunks indexed : {}", counters["chunks"])
    logger.info("=" * 60)

    return counters


def _ingest_one(
    service,
    src: Path,
    idx: int,
    total: int,
    counters: dict,
    *,
    force_reindex: bool = False,
) -> None:
    label = "true" if "true_data" in str(src) else "noisy"
    logger.info("[{}/{}] start {} {}", idx, total, label, src.name)
    try:
        result = service.ingest_file(str(src), force_reindex=force_reindex)
        status = result.get("status", "unknown")

        if status == "indexed":
            counters["chunks"] += int(result.get("chunks_indexed", 0))
            counters[f"{label}_ingested"] += 1
        elif status == "skipped":
            logger.info(
                "[{}/{}] skipped {} {} ({})",
                idx,
                total,
                label,
                src.name,
                result.get("reason", "unknown"),
            )
        else:
            counters["failed"] += 1

        if idx % 10 == 0 or idx == total:
            logger.info("  [{}/{}] progress - {} chunks so far", idx, total, counters["chunks"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[{}/{}] FAILED {} {}: {}", idx, total, label, src.name, type(exc).__name__)
        counters["failed"] += 1


def run_migrations(conn: psycopg2.extensions.connection) -> None:
    cur = conn.cursor()
    files = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))
    for filename in files:
        path = MIGRATIONS_DIR / filename
        with path.open(encoding="utf-8") as file_obj:
            sql = file_obj.read()
        logger.info("Running migration: {}", filename)
        cur.execute(sql)
    conn.commit()
    cur.close()


def seed_users(conn: psycopg2.extensions.connection) -> None:
    cur = conn.cursor()
    for username, password, is_admin in DEMO_USERS:
        password_hash = hash_password(password)
        cur.execute(
            """
            INSERT INTO users (username, password_hash, is_admin)
            VALUES (%s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET
                password_hash = EXCLUDED.password_hash,
                is_admin = EXCLUDED.is_admin
            """,
            (username, password_hash, is_admin),
        )
        logger.info("Seeded user: {} (admin={})", username, is_admin)
    conn.commit()
    cur.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed DB + ingest documents")
    parser.add_argument(
        "--no-ingest",
        action="store_true",
        help="Run migrations + users only; skip vector-store ingestion",
    )
    parser.add_argument(
        "--noise-sample",
        default="auto",
        help="Number of noisy docs to sample. Use 'auto', 'all', or an integer.",
    )
    parser.add_argument(
        "--true-sample",
        default="auto",
        help="Number of true-signal docs to use. Use 'auto', 'all', or an integer.",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Drop/recreate Qdrant collection and clear doc cache before ingest.",
    )
    args = parser.parse_args()

    logger.info("Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)
    logger.info("Running migrations...")
    run_migrations(conn)
    logger.info("Seeding demo users...")
    seed_users(conn)
    conn.close()
    logger.info("DB seeding done.")

    if args.no_ingest:
        logger.info("--no-ingest set; skipping doc ingestion.")
        return

    noise_arg: int | str = args.noise_sample
    if noise_arg not in ("all", "auto"):
        try:
            noise_arg = int(noise_arg)
        except ValueError as exc:
            raise SystemExit(
                f"--noise-sample must be int, 'all', or 'auto', got {noise_arg!r}"
            ) from exc

    true_arg: int | str = args.true_sample
    if true_arg not in ("all", "auto"):
        try:
            true_arg = int(true_arg)
        except ValueError as exc:
            raise SystemExit(
                f"--true-sample must be int, 'all', or 'auto', got {true_arg!r}"
            ) from exc

    seed_docs(noise_sample_size=noise_arg, true_sample_size=true_arg, wipe=args.wipe)


if __name__ == "__main__":
    main()
