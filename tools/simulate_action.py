"""Run the composite action's shell steps locally, as GitHub would (developer helper).

It reads ``action.yml``, substitutes ``${{ inputs.NAME }}`` with the input defaults (plus overrides), then
runs the "Install Commit Rider" and "Generate animation" ``run`` scripts under bash in a throw-away virtual
environment. It cannot reproduce ``actions/setup-python`` or the runner's network, so it needs Pillow
importable (the venv uses system site-packages) and installs the package with ``--no-build-isolation``.

    python tools/simulate_action.py source=demo width=480 height=144 fps=10 duration=3
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    overrides = dict(arg.split("=", 1) for arg in sys.argv[1:])
    action = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    inputs = {name: str(spec.get("default", "")) for name, spec in action["inputs"].items()}
    inputs["token"] = ""  # `github.token` does not exist locally
    inputs.update(overrides)
    steps = {s.get("name"): s for s in action["runs"]["steps"]}

    def expand(text: str) -> str:
        return re.sub(r"\$\{\{\s*inputs\.([\w-]+)\s*\}\}", lambda m: inputs[m.group(1)], text)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "workspace"
        work.mkdir()
        env = {**os.environ, "RUNNER_TEMP": tmp, "GITHUB_OUTPUT": str(Path(tmp) / "out.txt"),
               "GITHUB_STEP_SUMMARY": str(Path(tmp) / "summary.md"), "ACTION_PATH": str(ROOT)}
        install = steps["Install Commit Rider"]["run"].replace("-m venv", "-m venv --system-site-packages")
        install = install.replace("--quiet", "--quiet --no-build-isolation --no-deps")
        subprocess.run(["bash", "-c", install], check=True, env=env, cwd=work)
        gen = steps["Generate animation"]
        run_env = {**env, **{k: expand(str(v)) for k, v in gen["env"].items()}}
        proc = subprocess.run(["bash", "-c", gen["run"]], env=run_env, cwd=work)
        print("--- GITHUB_OUTPUT ---")
        print(Path(env["GITHUB_OUTPUT"]).read_text() if Path(env["GITHUB_OUTPUT"]).exists() else "(none)")
        produced = sorted(p.relative_to(work).as_posix() for p in work.rglob("*") if p.is_file())
        print("files in workspace:", produced)
        return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
