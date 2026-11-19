"""Static checks of everything that is not Python: action.yml, workflows, docs, packaging."""

import glob
import re
import tomllib
import unittest
from pathlib import Path

import yaml

import commit_rider
from commit_rider import action
from commit_rider.config.settings import Settings, option_schema
from tests.support import ROOT

ACTION = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
FIRST_PARTY = ("actions/",)
SHA = re.compile(r"^[0-9a-f]{40}$")


def workflow_files():
    paths = sorted(glob.glob(str(ROOT / ".github" / "workflows" / "*.yml")))
    paths += sorted(glob.glob(str(ROOT / "examples" / "workflows" / "*.yml")))
    return [Path(p) for p in paths]


def steps_of(workflow):
    for job in workflow["jobs"].values():
        yield from job.get("steps", [])


class ActionMetadataTests(unittest.TestCase):
    def test_required_top_level_fields(self):
        for key in ("name", "description", "author", "branding", "inputs", "outputs", "runs"):
            self.assertIn(key, ACTION)
        self.assertEqual(ACTION["runs"]["using"], "composite")
        self.assertIn(ACTION["branding"]["icon"], {"activity", "bar-chart-2", "play", "navigation", "zap"})
        self.assertIn(ACTION["branding"]["color"], {"white", "yellow", "blue", "green", "orange", "red", "purple", "gray-dark"})

    def test_every_input_is_documented_and_has_a_default(self):
        for name, spec in ACTION["inputs"].items():
            with self.subTest(input=name):
                self.assertTrue(spec["description"].strip())
                self.assertIn("default", spec)
                self.assertIs(spec.get("required", False), False)  # sensible defaults for everything
        self.assertEqual(ACTION["inputs"]["token"]["default"], "${{ github.token }}")

    def test_composite_steps_are_valid(self):
        for step in ACTION["runs"]["steps"]:
            if "run" in step:
                self.assertIn("shell", step, "composite run steps need an explicit shell")
            else:
                self.assertTrue(step["uses"].startswith(FIRST_PARTY))

    def test_inputs_reach_the_program_through_environment_variables(self):
        generate = next(s for s in ACTION["runs"]["steps"] if s.get("id") == "generate")
        env = generate["env"]
        self.assertNotIn("${{", generate["run"], "inputs must not be spliced into the shell script")
        consumed = {action.env_name(n) for n in action.ALL_INPUTS}
        self.assertEqual(set(env), consumed)
        for variable, expression in env.items():
            expected = variable[len("INPUT_"):].lower().replace("_", "-")
            self.assertEqual(expression, "${{ inputs." + expected + " }}", variable)
            self.assertIn(expected, ACTION["inputs"])
        only_setup = set(ACTION["inputs"]) - {n for n in action.ALL_INPUTS}
        self.assertEqual(only_setup, {"python-version"})

    def test_action_defaults_equal_library_defaults(self):
        defaults = {n: ACTION["inputs"][n]["default"] for n in action.SETTING_INPUTS}
        self.assertEqual(Settings.from_mapping(defaults), Settings())

    def test_outputs_match_what_the_program_writes(self):
        self.assertEqual(
            set(ACTION["outputs"]),
            {"path", "preview-path", "total-contributions", "frames", "size-bytes", "published"},
        )
        for name, spec in ACTION["outputs"].items():
            self.assertEqual(spec["value"], "${{ steps.generate.outputs." + name + " }}")
        source = (ROOT / "src" / "commit_rider" / "action.py").read_text()
        for name in ACTION["outputs"]:
            self.assertIn(f'"{name}"', source)

    def test_install_step_uses_the_pinned_constraints(self):
        install = next(s for s in ACTION["runs"]["steps"] if s.get("name") == "Install Commit Rider")
        self.assertIn("--constraint", install["run"])
        self.assertIn("requirements.txt", install["run"])


class WorkflowTests(unittest.TestCase):
    def test_all_workflows_parse_and_declare_least_privilege_permissions(self):
        files = workflow_files()
        self.assertGreaterEqual(len(files), 4)
        for path in files:
            wf = yaml.safe_load(path.read_text(encoding="utf-8"))
            with self.subTest(workflow=path.name):
                self.assertIn("permissions", wf, "every workflow sets explicit permissions")
                self.assertIn("jobs", wf)
                self.assertTrue(wf.get("on") or wf.get(True))  # PyYAML reads the key `on` as True
                for level in wf["permissions"].values():
                    self.assertIn(level, ("read", "write", "none"))

    def test_no_unpinned_third_party_actions(self):
        for path in workflow_files() + [ROOT / "action.yml"]:
            text = yaml.safe_load(path.read_text(encoding="utf-8"))
            steps = text["runs"]["steps"] if "runs" in text else list(steps_of(text))
            for step in steps:
                uses = step.get("uses")
                if not uses or uses.startswith("./"):
                    continue
                owner_repo, _, ref = uses.partition("@")
                if owner_repo.startswith(FIRST_PARTY) or owner_repo == "Sumit6258/commit-rider":
                    continue
                self.assertRegex(ref, SHA, f"{path.name}: third-party action {uses} must be pinned to a full commit SHA")

    def test_workflows_only_pass_inputs_the_action_declares(self):
        declared = set(ACTION["inputs"])
        for path in workflow_files():
            wf = yaml.safe_load(path.read_text(encoding="utf-8"))
            for step in steps_of(wf):
                uses = step.get("uses", "")
                if uses.startswith("./") or uses.startswith("Sumit6258/commit-rider@"):
                    unknown = set(step.get("with", {})) - declared
                    self.assertFalse(unknown, f"{path.name} passes unknown input(s) {unknown}")

    def test_consumer_example_is_complete(self):
        wf = yaml.safe_load((ROOT / "examples" / "workflows" / "commit-rider.yml").read_text())
        triggers = wf.get("on") or wf.get(True)
        self.assertIn("workflow_dispatch", triggers)
        self.assertIn("schedule", triggers)
        self.assertEqual(wf["permissions"], {"contents": "write"})
        steps = list(steps_of(wf))
        self.assertTrue(steps[0]["uses"].startswith("actions/checkout@"))  # credentials for publishing
        with_ = steps[1]["with"]
        self.assertEqual(with_["publish-branch"], "output")
        self.assertEqual(with_["username"], "${{ github.repository_owner }}")
        # the example mirrors the values requested in the specification
        spec = {"theme": "midnight", "bike": "bmx", "width": 1200, "height": 360, "fps": 18, "duration": 8}
        for key, value in spec.items():
            self.assertEqual(with_[key], value)

    def test_release_workflow_runs_tests_before_publishing(self):
        wf = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
        names = [s.get("run", s.get("name", "")) for s in steps_of(wf)]
        order = [i for i, text in enumerate(names) if "pytest" in text or "gh release create" in text or "tag -f" in text]
        self.assertEqual(len(order), 3)
        self.assertTrue(names[order[0]].startswith("python -m pytest"))
        self.assertIn("gh release create", names[order[1]])

    def test_dependabot_covers_actions_and_pip(self):
        data = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
        self.assertEqual({u["package-ecosystem"] for u in data["updates"]}, {"github-actions", "pip"})


class PackagingTests(unittest.TestCase):
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    def test_versions_agree(self):
        self.assertEqual(self.pyproject["project"]["version"], commit_rider.__version__)
        self.assertIn(f"## [{commit_rider.__version__}]", (ROOT / "CHANGELOG.md").read_text())

    def test_pinned_requirement_is_inside_the_declared_range(self):
        pin = re.search(r"^Pillow==(\d+)\.(\d+)", (ROOT / "requirements.txt").read_text(), re.M)
        self.assertIsNotNone(pin)
        major, minor = int(pin.group(1)), int(pin.group(2))
        spec = next(d for d in self.pyproject["project"]["dependencies"] if d.startswith("Pillow"))
        low = re.search(r">=(\d+)\.(\d+)", spec)
        high = re.search(r"<(\d+)", spec)
        self.assertGreaterEqual((major, minor), (int(low.group(1)), int(low.group(2))))
        self.assertLess(major, int(high.group(1)))

    def test_runtime_dependencies_stay_minimal(self):
        self.assertEqual(len(self.pyproject["project"]["dependencies"]), 1)

    def test_console_script_and_license(self):
        self.assertEqual(self.pyproject["project"]["scripts"]["commit-rider"], "commit_rider.cli:main")
        self.assertIn("MIT", (ROOT / "LICENSE").read_text()[:200])
        self.assertEqual(self.pyproject["project"]["license"]["text"], "MIT")


class DocumentationTests(unittest.TestCase):
    required = [
        "README.md", "LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", ".gitignore",
        "docs/installation.md", "docs/configuration.md", "docs/architecture.md", "docs/troubleshooting.md",
        "docs/examples.md", ".github/PULL_REQUEST_TEMPLATE.md", ".github/ISSUE_TEMPLATE/bug_report.yml",
        "examples/sample-contributions.json", "examples/demo.gif", "examples/preview.png", "assets/README.md",
    ]

    def test_required_files_exist(self):
        for rel in self.required:
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_readme_has_the_requested_sections(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for heading in ("Quick start", "Installation", "Features", "Configuration", "Themes", "Authentication",
                        "Troubleshooting", "Contributing", "License"):
            self.assertRegex(text, rf"(?m)^#+ .*{heading}", heading)
        self.assertIn("Your GitHub contributions. Your terrain. Your ride.", text)
        self.assertLess(text.index("demo.gif"), text.index("Installation"), "demo must be near the top")

    def test_relative_links_and_images_resolve(self):
        link = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s#]+)")
        for rel in ["README.md", "CONTRIBUTING.md", "SECURITY.md", *glob.glob("docs/*.md", root_dir=ROOT)]:
            path = ROOT / rel
            for target in link.findall(path.read_text(encoding="utf-8")):
                resolved = (path.parent / target).resolve()
                self.assertTrue(resolved.exists(), f"{rel} links to missing {target}")

    def test_configuration_docs_list_every_option_and_action_input(self):
        text = (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
        for name in option_schema():
            self.assertTrue(name in text or name.replace("_", "-") in text, f"option {name} is undocumented")
        for name in ACTION["inputs"]:
            self.assertIn(f"`{name}`", text + (ROOT / "docs" / "installation.md").read_text(), f"input {name} is undocumented")

    def test_docs_describe_the_verified_authentication_modes(self):
        text = (ROOT / "docs" / "installation.md").read_text(encoding="utf-8")
        for needle in ("GITHUB_TOKEN", "read:user", "contents: write", "persist-credentials", "orphan"):
            self.assertIn(needle, text)

    def test_no_secrets_are_committed(self):
        pattern = re.compile(r"(ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY)")
        skipped = {".git", "tests", "dist", "build", "__pycache__"}
        for path in ROOT.rglob("*"):
            if path.is_file() and not (set(path.relative_to(ROOT).parts) & skipped) and path.suffix not in {".gif", ".png"}:
                if ".egg-info" in str(path):
                    continue
                self.assertIsNone(pattern.search(path.read_text(encoding="utf-8", errors="ignore")), str(path))

    def test_gitignore_keeps_artefacts_out(self):
        text = (ROOT / ".gitignore").read_text()
        for entry in ("__pycache__", "dist/", ".env", "*.egg-info"):
            self.assertIn(entry, text)


if __name__ == "__main__":
    unittest.main()
