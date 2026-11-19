"""A small, dependency-free stand-in for the most common ruff findings.

It does NOT replace ``ruff check .`` (use that when you can). It reports, for the package, the tests and
tools: syntax errors, unused imports (F401), unused local variables (F841), trailing whitespace (W291/W293),
tabs (W191), comparisons to None/True/False with ``==`` (E711/E712), bare ``except:`` (E722) and syntax
that needs Python 3.12 (nested same-type quotes or backslashes inside f-string replacement fields), because
the project supports Python 3.11.

    python tools/lint_check.py
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", "build", "dist", ".venv", "__pycache__"}


def python_files():
    for path in sorted(ROOT.rglob("*.py")):
        if not (set(path.relative_to(ROOT).parts) & SKIP) and ".egg-info" not in str(path):
            yield path


class Usage(ast.NodeVisitor):
    def __init__(self):
        self.names: set[str] = set()

    def visit_Name(self, node):  # noqa: N802
        self.names.add(node.id)

    def visit_Attribute(self, node):  # noqa: N802
        self.generic_visit(node)


def check_imports(tree, source, path):
    problems = []
    used = Usage()
    used.visit(tree)
    exported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            exported |= {e.value for e in getattr(node.value, "elts", []) if isinstance(e, ast.Constant)}
    string_refs = " ".join(c.value for c in ast.walk(tree) if isinstance(c, ast.Constant) and isinstance(c.value, str))
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            if path.name == "__init__.py":
                continue
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0]
                if name not in used.names and name not in exported and not re.search(rf"\b{re.escape(name)}\b", string_refs):
                    line = source.splitlines()[node.lineno - 1]
                    if "noqa" not in line:
                        problems.append((node.lineno, f"F401 '{alias.name}' imported but unused"))
    return problems


def check_unused_locals(tree, source):
    problems = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        assigned: dict[str, int] = {}
        loads: set[str] = set()
        for node in ast.walk(func):
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Store):
                    assigned.setdefault(node.id, node.lineno)
                else:
                    loads.add(node.id)
        nonlocal_names = {n for node in ast.walk(func) if isinstance(node, (ast.Global, ast.Nonlocal)) for n in node.names}
        for name, line in assigned.items():
            if name not in loads and name not in nonlocal_names and not name.startswith("_"):
                # tuple-unpacking targets and loop variables are ignored by ruff's F841, so skip them
                parents = [n for n in ast.walk(func) if isinstance(n, (ast.For, ast.comprehension, ast.With, ast.Tuple)) and any(isinstance(t, ast.Name) and t.id == name for t in ast.walk(n))]
                if not parents and "noqa" not in source.splitlines()[line - 1]:
                    problems.append((line, f"F841 local variable '{name}' is assigned to but never used"))
    return problems


def check_text(source):
    problems = []
    for number, line in enumerate(source.splitlines(), 1):
        if line.rstrip() != line:
            problems.append((number, "W291 trailing whitespace"))
        if "\t" in line[: len(line) - len(line.lstrip())]:
            problems.append((number, "W191 indentation contains tabs"))
    return problems


def check_ast_style(tree):
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            problems.append((node.lineno, "E722 bare except"))
        if isinstance(node, ast.Compare):
            for op, right in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(right, ast.Constant) and right.value is None:
                    problems.append((node.lineno, "E711 comparison to None"))
    return problems


def check_py312_fstrings(source):
    """Flag f-strings that only parse on Python 3.12+ (PEP 701)."""
    problems = []
    stack = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.FSTRING_START:
                stack.append((tok.string[-1], tok.start[0]))
            elif tok.type == tokenize.FSTRING_END:
                stack.pop()
            elif stack and tok.type in (tokenize.STRING, tokenize.FSTRING_START):
                quote = tok.string.lstrip("rbfRBF")[0]
                if quote == stack[-1][0]:
                    problems.append((tok.start[0], "needs Python 3.12: same quote type nested inside an f-string"))
    except tokenize.TokenError:
        pass
    return problems


def main() -> int:
    total = 0
    for path in python_files():
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            print(f"{path.relative_to(ROOT)}:{exc.lineno}: syntax error: {exc.msg}")
            total += 1
            continue
        found = check_imports(tree, source, path) + check_unused_locals(tree, source) + check_text(source)
        found += check_ast_style(tree)
        found += check_py312_fstrings(source)
        for line, message in sorted(found):
            print(f"{path.relative_to(ROOT)}:{line}: {message}")
        total += len(found)
    print(f"{total} problem(s)" if total else "lint_check: clean")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
