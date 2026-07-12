import json

import pytest

from scripts.seed_db import _select_manifest_corpus


# Learner Note: Test manifest selection preserves exact authority partition is part of the automated regression suite.
def test_manifest_selection_preserves_exact_authority_partition(tmp_path, monkeypatch):
    """A manifest must select exactly its listed true and noisy documents."""
    monkeypatch.chdir(tmp_path)
    true_file = tmp_path / "seed/docs/true_data/policy.txt"
    noisy_file = tmp_path / "seed/docs/noisy_data/noise.pdf"
    true_file.parent.mkdir(parents=True)
    noisy_file.parent.mkdir(parents=True)
    true_file.write_text("policy", encoding="utf-8")
    noisy_file.write_text("noise", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "resolved": {
                "policy.txt": "seed/docs/true_data/policy.txt",
                "noise.pdf": "seed/docs/noisy_data/noise.pdf",
            },
            "missing": [],
            "ambiguous": {},
        }),
        encoding="utf-8",
    )

    true_files, noisy_files = _select_manifest_corpus(manifest)

    assert true_files == [true_file.resolve()]
    assert noisy_files == [noisy_file.resolve()]


# Learner Note: Test manifest selection rejects unresolved entries is part of the automated regression suite.
def test_manifest_selection_rejects_unresolved_entries(tmp_path):
    """Missing or ambiguous sources require an explicit exclusion decision."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "resolved": {},
            "missing": ["runtime-upload.md"],
            "ambiguous": {},
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unresolved entries"):
        _select_manifest_corpus(manifest)
