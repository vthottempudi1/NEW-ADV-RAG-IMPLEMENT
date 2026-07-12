"""Add consistent learner notes and docstrings without changing Python behavior.

This maintenance utility uses the standard-library AST only to locate definitions.
It inserts text into the original source lines, so formatting, comments, decorators,
and executable statements remain intact. Re-running it is idempotent.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOTS = ("app", "evals", "Eval", "scripts", "tests", "ui")
DEFINITION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


# Learner Note: Convert identifiers into readable phrases used by generated documentation.
def _words(name: str) -> str:
    """Convert snake_case or CamelCase identifiers into a readable lowercase phrase."""
    expanded = re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("_", " ")
    return " ".join(expanded.split()).lower()


# Learner Note: Map each source path to its architectural responsibility.
def _domain(path: Path) -> str:
    """Return a concise architecture-domain description for a Python source path."""
    normalized = path.as_posix().lower()
    mappings = (
        ("/api/", "the versioned HTTP API boundary"),
        ("/rag/", "the retrieval-augmented generation pipeline"),
        ("/sql/", "the governed structured-query pipeline"),
        ("/caching/", "the distributed caching layer"),
        ("/ingestion/", "the document ingestion pipeline"),
        ("/observability/", "the observability and cost-control layer"),
        ("/security/", "the application security boundary"),
        ("/middleware/", "the cross-cutting request middleware"),
        ("/storage/", "the storage abstraction layer"),
        ("/core/", "the application orchestration layer"),
        ("evals/", "the evaluation and quality-gate framework"),
        ("tests/", "the automated regression suite"),
        ("ui/", "the Streamlit presentation layer"),
        ("scripts/", "the operational tooling layer"),
    )
    for marker, description in mappings:
        if marker in f"/{normalized}":
            return description
    return "the enterprise RAG application"


# Learner Note: Generate documentation that explains role and operational importance.
def _docstring(node: ast.AST, path: Path) -> list[str]:
    """Build a short role-aware docstring for one class or function definition."""
    name = getattr(node, "name", "definition")
    readable = _words(name)
    domain = _domain(path)

    if isinstance(node, ast.ClassDef):
        summary = f"Represent {readable} within {domain}."
        detail = "This class groups state and behavior behind a clear, testable contract."
    elif name.startswith("test_"):
        summary = f"Verify that {readable.removeprefix('test ')}."
        detail = "This regression test protects an expected production behavior from silent changes."
    elif name == "__init__":
        summary = f"Initialize {readable} dependencies and runtime state."
        detail = "Explicit initialization keeps object construction predictable and testable."
    elif isinstance(node, ast.AsyncFunctionDef):
        summary = f"Handle {readable} asynchronously within {domain}."
        detail = "The async boundary prevents request handling from blocking unrelated work."
    elif name.startswith("_"):
        summary = f"Support {domain} by performing {readable.lstrip(' ')}."
        detail = "Keeping this helper focused makes the surrounding workflow easier to test and maintain."
    else:
        summary = f"Perform {readable} for {domain}."
        detail = "This function keeps the responsibility explicit for callers, tests, and operators."

    return [summary, "", "Learner Note:", f"    {detail}"]


# Learner Note: Detect whether a nearby explanatory comment already documents a definition.
def _has_nearby_note(lines: list[str], line_index: int) -> bool:
    """Return whether the lines immediately before a definition contain a learner note."""
    start = max(0, line_index - 3)
    nearby = "\n".join(lines[start:line_index]).lower()
    return "learner note:" in nearby or "learner note -" in nearby


# Learner Note: Insert documentation from bottom to top so AST line numbers stay stable.
def _document_file(path: Path) -> tuple[int, int]:
    """Add missing notes and docstrings to one file and return insertion counts."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines(keepends=True)
    insertions: dict[int, list[str]] = {}
    notes_added = 0
    docs_added = 0

    nodes = [node for node in ast.walk(tree) if isinstance(node, DEFINITION_TYPES)]
    for node in nodes:
        decorator_lines = [decorator.lineno for decorator in getattr(node, "decorator_list", [])]
        definition_line = min(decorator_lines or [node.lineno]) - 1
        indent = " " * node.col_offset

        if not _has_nearby_note(lines, definition_line):
            readable = _words(getattr(node, "name", "definition"))
            note = f"{indent}# Learner Note: {readable.capitalize()} is part of {_domain(path)}.\n"
            insertions.setdefault(definition_line, []).append(note)
            notes_added += 1

        if not ast.get_docstring(node, clean=False):
            body = getattr(node, "body", [])
            if not body:
                continue
            first_body_decorators = [
                decorator.lineno for decorator in getattr(body[0], "decorator_list", [])
            ]
            body_line = min(first_body_decorators or [body[0].lineno]) - 1
            body_indent = " " * body[0].col_offset
            doc_lines = _docstring(node, path)
            rendered = [f'{body_indent}"""{doc_lines[0]}\n']
            rendered.extend(
                f"{body_indent}{line}\n" if line else "\n" for line in doc_lines[1:]
            )
            rendered.append(f'{body_indent}"""\n')
            insertions.setdefault(body_line, []).extend(rendered)
            docs_added += 1

    if insertions:
        output: list[str] = []
        for index, line in enumerate(lines):
            output.extend(insertions.get(index, []))
            output.append(line)
        output.extend(insertions.get(len(lines), []))
        path.write_text("".join(output), encoding="utf-8", newline="\n")

    return notes_added, docs_added


# Learner Note: Discover repository Python files while excluding generated environments and caches.
def _python_files(root: Path) -> list[Path]:
    """Return sorted Python source files from the maintained repository areas."""
    paths: list[Path] = []
    for relative_root in ROOTS:
        directory = root / relative_root
        if directory.exists():
            paths.extend(directory.rglob("*.py"))
    return sorted(
        path
        for path in paths
        if ".venv" not in path.parts and "__pycache__" not in path.parts
    )


# Learner Note: Run the idempotent repository-wide learner-documentation codemod.
def main() -> None:
    """Document all maintained Python definitions and print a concise change summary."""
    root = Path(__file__).resolve().parents[1]
    notes = 0
    docs = 0
    for path in _python_files(root):
        added_notes, added_docs = _document_file(path)
        notes += added_notes
        docs += added_docs
    print(f"learner_notes_added={notes} docstrings_added={docs}")


if __name__ == "__main__":
    main()
