import argparse
import gc
import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

import psycopg2
from loguru import logger

# Direct script execution places ``scripts`` first on sys.path. Insert the
# repository root so imports always resolve this checkout instead of a stale
# site-packages build of the project.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.middleware.auth import hash_password  # noqa: E402

DATABASE_URL = os.getenv("DATABASE_URL", settings.database_url)
MIGRATIONS_DIR = ROOT / "db" / "migrations"
DOCS_DIR = ROOT / "seed" / "docs"
DOC_CACHE_DIR = Path(".cache/storage")

DEMO_USERS = [
    ("agent@demo.local", "agent123", False),
    ("admin@demo.local", "admin123", True),
]

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}
SAMPLE_SEED = 42


# Learner note: Encapsulates collect files so this responsibility can be understood, tested, and changed independently.
def _collect_files(subdir: str) -> list[Path]:
    """Support the operational tooling layer by performing collect files.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
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


# Learner note: Encapsulates select corpus so this responsibility can be understood, tested, and changed independently.
def _select_corpus(
    noise_sample_size: int | str,
    true_sample_size: int | str = "auto",
) -> tuple[list[Path], list[Path]]:
    """Support the operational tooling layer by performing select corpus.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
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


def _select_manifest_corpus(
    manifest_path: Path,
    *,
    allow_unresolved: bool = False,
) -> tuple[list[Path], list[Path]]:
    """Load an exact corpus manifest and fail safely on unresolved entries."""
    payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    resolved = payload.get("resolved")
    if not isinstance(resolved, dict):
        raise ValueError("manifest must contain a 'resolved' source-to-path object")

    missing = payload.get("missing") or []
    ambiguous = payload.get("ambiguous") or {}
    if (missing or ambiguous) and not allow_unresolved:
        raise ValueError(
            "manifest contains unresolved entries; resolve them or pass "
            "--allow-unresolved-manifest to exclude them explicitly"
        )

    paths: list[Path] = []
    seen: set[Path] = set()
    for raw_path in resolved.values():
        path = Path(str(raw_path)).resolve()
        if path in seen:
            continue
        if not path.is_file():
            raise FileNotFoundError(f"manifest file does not exist: {path}")
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"unsupported manifest file type: {path}")
        seen.add(path)
        paths.append(path)

    true_files = sorted(path for path in paths if "true_data" in path.parts)
    noisy_files = sorted(path for path in paths if "noisy_data" in path.parts)
    unclassified = [
        path for path in paths if path not in true_files and path not in noisy_files
    ]
    if unclassified:
        raise ValueError(
            "manifest paths must belong to true_data or noisy_data: "
            + ", ".join(str(path) for path in unclassified[:5])
        )
    return true_files, noisy_files


# Learner note: Encapsulates clear doc cache storage so this responsibility can be understood, tested, and changed independently.
def _clear_doc_cache_storage() -> None:
    """Support the operational tooling layer by performing clear doc cache storage.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    if DOC_CACHE_DIR.exists():
        shutil.rmtree(DOC_CACHE_DIR, ignore_errors=True)
    DOC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Cleared document metadata cache at {}", DOC_CACHE_DIR)


# Learner note: Encapsulates seed docs so this responsibility can be understood, tested, and changed independently.
def seed_docs(
    noise_sample_size: int | str = "auto",
    true_sample_size: int | str = "auto",
    wipe: bool = False,
    manifest_path: Path | None = None,
    allow_unresolved_manifest: bool = False,
) -> dict:
    """Perform seed docs for the operational tooling layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
    from app.ingestion.service import IngestionService
    from app.rag.vector_store import recreate_collection

    service = IngestionService()
    if manifest_path is not None:
        true_files, noisy_files = _select_manifest_corpus(
            manifest_path,
            allow_unresolved=allow_unresolved_manifest,
        )
    else:
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

    counters = {
        "true_ingested": 0,
        "noisy_ingested": 0,
        "failed": 0,
        "chunks": 0,
        "consecutive_failures": 0,
    }
    t0 = time.time()

    for idx, src in enumerate(true_files, start=1):
        _ingest_one(
            service,
            src,
            idx,
            total,
            counters,
            force_reindex=wipe,
            authority_tier="true",
        )
        if counters["consecutive_failures"] >= 3:
            raise RuntimeError("aborting ingestion after three consecutive document failures")
        if counters["chunks"] > 0 and idx == len(true_files):
            logger.info("All {} true (signal) files done", len(true_files))

    for jdx, src in enumerate(noisy_files, start=1):
        idx = len(true_files) + jdx
        _ingest_one(
            service,
            src,
            idx,
            total,
            counters,
            force_reindex=wipe,
            authority_tier="noisy",
        )
        if counters["consecutive_failures"] >= 3:
            raise RuntimeError("aborting ingestion after three consecutive document failures")

    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("INGESTION COMPLETE in {:.1f} min", elapsed / 60)
    logger.info("  true_data ingested   : {}", counters["true_ingested"])
    logger.info("  noisy_data ingested  : {}", counters["noisy_ingested"])
    logger.info("  failed (or skipped)  : {}", counters["failed"])
    logger.info("  total chunks indexed : {}", counters["chunks"])
    logger.info("=" * 60)

    return counters


# Learner note: Encapsulates ingest one so this responsibility can be understood, tested, and changed independently.
def _ingest_one(
    service,
    src: Path,
    idx: int,
    total: int,
    counters: dict,
    *,
    force_reindex: bool = False,
    authority_tier: str,
) -> None:
    """Support the operational tooling layer by performing ingest one.

    Learner Note:
        Keeping this helper focused makes the surrounding workflow easier to test and maintain.
    """
    label = "true" if "true_data" in str(src) else "noisy"
    logger.info("[{}/{}] start {} {}", idx, total, label, src.name)
    try:
        result = service.ingest_file(
            str(src),
            force_reindex=force_reindex,
            authority_tier=authority_tier,
            ingestion_version="v2",
        )
        status = result.get("status", "unknown")

        if status == "indexed":
            counters["chunks"] += int(result.get("chunks_indexed", 0))
            counters[f"{label}_ingested"] += 1
            counters["consecutive_failures"] = 0
        elif status == "skipped":
            counters["consecutive_failures"] = 0
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
            counters["consecutive_failures"] += 1

        if idx % 10 == 0 or idx == total:
            logger.info("  [{}/{}] progress - {} chunks so far", idx, total, counters["chunks"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[{}/{}] FAILED {} {}: {}", idx, total, label, src.name, type(exc).__name__)
        counters["failed"] += 1
        counters["consecutive_failures"] += 1
    finally:
        # Large PDFs can retain parser and embedding buffers until cyclic GC
        # runs. Reclaim them after every document so long corpus jobs do not
        # accumulate memory across hundreds of files.
        gc.collect()


# Learner note: Orchestrates run migrations, making this function a clear execution boundary for learners and tests.
def run_migrations(conn: psycopg2.extensions.connection) -> None:
    """Perform run migrations for the operational tooling layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
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


# Learner note: Encapsulates seed users so this responsibility can be understood, tested, and changed independently.
def seed_users(conn: psycopg2.extensions.connection) -> None:
    """Perform seed users for the operational tooling layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
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


# Learner note: Orchestrates main, making this function a clear execution boundary for learners and tests.
def main() -> None:
    """Perform main for the operational tooling layer.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
    """
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
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Exact source-to-path corpus manifest; disables random folder sampling.",
    )
    parser.add_argument(
        "--allow-unresolved-manifest",
        action="store_true",
        help="Explicitly exclude manifest entries listed as missing or ambiguous.",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Target Qdrant collection. Required with --manifest for isolation.",
    )
    args = parser.parse_args()

    configured_collection = settings.qdrant_collection
    if args.manifest is not None and not args.collection:
        raise SystemExit("--collection is required with --manifest")
    if (
        args.manifest is not None
        and args.wipe
        and args.collection == configured_collection
    ):
        raise SystemExit(
            "refusing to wipe the configured active collection during manifest ingestion; "
            "use a new versioned collection name"
        )
    if args.collection:
        settings.qdrant_collection = args.collection

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

    seed_docs(
        noise_sample_size=noise_arg,
        true_sample_size=true_arg,
        wipe=args.wipe,
        manifest_path=args.manifest,
        allow_unresolved_manifest=args.allow_unresolved_manifest,
    )


if __name__ == "__main__":
    main()
