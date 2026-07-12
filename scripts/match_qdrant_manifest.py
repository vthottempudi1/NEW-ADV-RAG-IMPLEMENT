"""Match Qdrant source names to reproducible local corpus paths."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> None:
    """Resolve exported source basenames and write an auditable corpus manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        default="seed/manifests/aws_successful_sources.json",
        help="JSON list of source names exported from Qdrant.",
    )
    parser.add_argument(
        "--output",
        default="seed/manifests/aws_successful_corpus.json",
        help="Destination for resolved, missing, and ambiguous paths.",
    )
    args = parser.parse_args()

    source_path = Path(args.sources)
    output_path = Path(args.output)
    source_names = json.loads(source_path.read_text(encoding="utf-8-sig"))

    files_by_name: dict[str, list[Path]] = defaultdict(list)
    for root in (Path("seed/docs/true_data"), Path("seed/docs/noisy_data")):
        for path in root.rglob("*"):
            if path.is_file():
                files_by_name[path.name.casefold()].append(path)

    resolved: dict[str, str] = {}
    missing: list[str] = []
    ambiguous: dict[str, list[str]] = {}
    for source_name in source_names:
        name = Path(str(source_name)).name
        matches = files_by_name.get(name.casefold(), [])
        if len(matches) == 1:
            resolved[str(source_name)] = matches[0].as_posix()
        elif not matches:
            missing.append(str(source_name))
        else:
            ambiguous[str(source_name)] = [path.as_posix() for path in matches]

    result = {
        "resolved": resolved,
        "missing": missing,
        "ambiguous": ambiguous,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    paths = list(resolved.values())
    true_count = sum("/true_data/" in path for path in paths)
    noisy_count = sum("/noisy_data/" in path for path in paths)
    print(f"Input AWS sources: {len(source_names)}")
    print(f"Resolved: {len(resolved)}")
    print(f"True sources: {true_count}")
    print(f"Noisy sources: {noisy_count}")
    print(f"Missing: {len(missing)}")
    print(f"Ambiguous: {len(ambiguous)}")
    print(f"Manifest: {output_path}")
    if missing:
        print("Missing source names:")
        for name in missing:
            print(f"  - {name}")
    if ambiguous:
        print("Ambiguous source names:")
        for name, matches in ambiguous.items():
            print(f"  - {name}: {matches}")


if __name__ == "__main__":
    main()
