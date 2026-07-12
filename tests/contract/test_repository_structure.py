"""Contract tests for enterprise package boundaries and learner documentation."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOTS = ("app", "evals", "Eval", "scripts", "tests", "ui")


# Learner Note: Guard the production-oriented directory boundaries against regression.
def test_enterprise_repository_boundaries_exist():
    """Verify that every canonical application, test, eval, UI, DB, and infra layer exists.

    Learner Note:
        This contract stops future changes from silently returning code to a flat layout.
    """
    expected = (
        "app/api/v1",
        "app/core",
        "app/rag",
        "app/sql",
        "app/security",
        "app/caching",
        "app/ingestion",
        "app/storage",
        "app/observability",
        "db/migrations",
        "db/seeds",
        "tests/unit",
        "tests/integration",
        "tests/contract",
        "tests/e2e",
        "tests/fixtures",
        "evals/datasets",
        "evals/runners",
        "evals/reports",
        "ui/streamlit",
        "infra/docker",
        "infra/ecs",
        "infra/cloudwatch",
        "infra/terraform",
    )

    missing = [relative for relative in expected if not (ROOT / relative).is_dir()]
    assert not missing, f"Missing enterprise repository boundaries: {missing}"


# Learner Note: Enforce the learner-facing documentation standard for every definition.
def test_all_python_classes_and_functions_have_docstrings():
    """Verify that every maintained Python class and function has a non-empty docstring.

    Learner Note:
        Hiring managers and new contributors should not encounter undocumented behavior.
    """
    missing: list[str] = []
    for relative_root in PYTHON_ROOTS:
        for path in (ROOT / relative_root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if not ast.get_docstring(node):
                        missing.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.name}")

    assert not missing, "Missing docstrings:\n" + "\n".join(missing)
