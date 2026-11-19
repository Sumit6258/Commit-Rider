"""Dependency-free line coverage for ``src/commit_rider`` using ``sys.monitoring`` (Python 3.12+).

    python tools/linecov.py [unittest args...]

Runs the test suite once under a low-overhead line monitor and prints per-module statement coverage
(executable lines found by compiling each file, minus docstrings and ``# pragma: no cover`` lines). It is a
convenient approximation of ``coverage.py`` (use that in CI); the numbers can differ slightly.
"""

from __future__ import annotations

import ast
import sys
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "commit_rider"


def executable_lines(path: Path) -> set[int]:
    source = path.read_text(encoding="utf-8")
    code = compile(source, str(path), "exec")
    lines: set[int] = set()

    def walk(c):
        for _, _, line in c.co_lines():
            if line:
                lines.add(line)
        for const in c.co_consts:
            if hasattr(const, "co_lines"):
                walk(const)

    walk(code)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
            doc = body[0]
            lines -= set(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    for number, text in enumerate(source.splitlines(), 1):
        if "pragma: no cover" in text:
            lines.discard(number)
    return lines


def main() -> int:
    if not hasattr(sys, "monitoring"):
        print("This tool needs Python 3.12+ (sys.monitoring).")
        return 2
    mon = sys.monitoring
    tool = mon.COVERAGE_ID
    mon.use_tool_id(tool, "linecov")
    hits: dict[str, set[int]] = defaultdict(set)
    prefix = str(PKG)

    def on_line(code, line):
        if code.co_filename.startswith(prefix):
            hits[code.co_filename].add(line)
        return mon.DISABLE

    mon.register_callback(tool, mon.events.LINE, on_line)
    mon.set_events(tool, mon.events.LINE)
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=0, stream=open("/dev/null", "w")).run(suite)
    mon.set_events(tool, 0)
    mon.free_tool_id(tool)

    rows = []
    for path in sorted(PKG.rglob("*.py")):
        want = executable_lines(path)
        got = hits.get(str(path), set()) & want
        rows.append((path.relative_to(PKG).as_posix(), len(got), len(want)))
    width = max(len(r[0]) for r in rows)
    print(f"tests run: {result.testsRun}, failures: {len(result.failures)}, errors: {len(result.errors)}")
    for name, got, want in rows:
        pct = 100.0 * got / want if want else 100.0
        print(f"{name:{width}s} {got:5d}/{want:<5d} {pct:5.1f}%")

    def total(prefixes):
        g = sum(r[1] for r in rows if r[0].startswith(prefixes))
        w = sum(r[2] for r in rows if r[0].startswith(prefixes))
        return 100.0 * g / w if w else 100.0

    print(f"\nterrain + animation (core algorithms): {total(('terrain/', 'animation/')):.1f}%")
    print(f"whole package:                          {total(('',)):.1f}%")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
