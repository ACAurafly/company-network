"""Exercise the local feature lifecycle without modifying the working checkout."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]


class FeatureLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="company-network-sdd-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tooling").mkdir()
        shutil.copy2(REPO / "tooling/local_sdd.py", self.root / "tooling/local_sdd.py")
        for directory in ("templates",):
            shutil.copytree(REPO / ".specify" / directory, self.root / ".specify" / directory,
                            ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "tooling/local_speckit", self.root / "tooling/local_speckit",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("SPECIFY_")}
        self.env["PYTHONIOENCODING"] = "utf-8"

    def command(self, script, *args, code=0, env=None):
        result = subprocess.run([sys.executable, str(self.root / script), *args],
                                cwd=self.root, env=self.env | (env or {}),
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def sdd(self, *args, **kwargs):
        return self.command("tooling/local_sdd.py", *args, **kwargs)

    def complete_artifacts(self, slug="camera-calibration"):
        self.sdd("new", slug)
        feature = self.root / ".scratch" / slug
        for name, text in {
            "spec.md": "# Calibration\nFR-001: Show when the player is visible.\n",
            "plan.md": "# Plan\nTest detection with recorded input.\n",
            "tasks.md": "# Tasks\n- [X] T001 [US1] Verify recorded calibration input.\n",
            "evidence.md": "# Evidence\nFR-001 / T001: recorded input verification passed.\n",
        }.items():
            (feature / name).write_text(text, encoding="utf-8")
        return feature

    def test_create_select_and_use_preserve_existing_spec(self):
        output = json.loads(self.sdd("new", "camera-calibration").stdout)
        spec = Path(output["SPEC_FILE"])
        spec.write_text("User-authored requirements.\n", encoding="utf-8")
        self.sdd("new", "camera-calibration", code=1)
        self.sdd("new", "second-feature")
        self.sdd("use", ".scratch/camera-calibration")
        self.assertEqual(json.loads(self.sdd("current").stdout)["SPEC_FILE"], str(spec))
        self.assertEqual(spec.read_text(encoding="utf-8"), "User-authored requirements.\n")

    def test_reuse_legacy_directory_does_not_require_plan(self):
        legacy = self.root / ".scratch/legacy-work"
        legacy.mkdir(parents=True)
        (legacy / "spec.md").write_text("Existing specification", encoding="utf-8")
        self.sdd("use", "legacy-work")
        self.assertFalse((legacy / "plan.md").exists())

    def test_invalid_names_and_escaping_paths_are_rejected(self):
        for slug in ("../escape", "bad name", "CON", "nul", "com1", "BadCase"):
            with self.subTest(slug=slug):
                self.sdd("new", slug, code=1)
        self.sdd("use", "../outside", code=1)
        self.assertFalse((self.root / ".specify/feature.json").exists())

    def test_missing_and_stale_pointer_fail_with_actionable_error(self):
        self.assertIn("Select a feature first", self.sdd("current", code=1).stderr)
        (self.root / ".specify/feature.json").write_text(
            json.dumps({"feature_directory": ".scratch/missing"}), encoding="utf-8")
        self.assertIn("spec.md not found", self.sdd("current", code=1).stderr)

    def test_environment_override_and_no_persist_isolate_selection(self):
        first = json.loads(self.sdd("new", "first-feature").stdout)["FEATURE_DIR"]
        self.sdd("new", "second-feature")
        before = (self.root / ".specify/feature.json").read_bytes()
        env = {"SPECIFY_FEATURE_DIRECTORY": ".scratch/first-feature", "SPECIFY_FEATURE_NO_PERSIST": "1"}
        self.assertEqual(json.loads(self.sdd("current", env=env).stdout)["FEATURE_DIR"], first)
        self.sdd("use", "first-feature", env=env)
        self.sdd("use", "second-feature", env=env, code=1)
        self.sdd("new", "third-feature", env=env, code=1)
        self.assertFalse((self.root / ".scratch/third-feature").exists())
        self.assertEqual((self.root / ".specify/feature.json").read_bytes(), before)

    def test_official_helpers_follow_local_feature_and_preserve_plan(self):
        feature = Path(json.loads(self.sdd("new", "camera-calibration").stdout)["FEATURE_DIR"])
        script = "tooling/local_speckit/setup_plan.py"
        plan = json.loads(self.command(script, "--json").stdout)
        self.assertEqual(Path(plan["FEATURE_DIR"]), feature)
        (feature / "plan.md").write_text("Existing plan.\n", encoding="utf-8")
        self.command(script, "--json")
        self.assertEqual((feature / "plan.md").read_text(encoding="utf-8"), "Existing plan.\n")
        tasks = json.loads(self.command("tooling/local_speckit/setup_tasks.py", "--json").stdout)
        self.assertEqual(Path(tasks["FEATURE_DIR"]), feature)
        self.assertTrue(tasks["TASKS_TEMPLATE_CONTENT"].strip())
        (feature / "tasks.md").write_text("- [ ] T001 Implement calibration.\n", encoding="utf-8")
        prereq = json.loads(self.command("tooling/local_speckit/check_prerequisites.py", "--json",
                                       "--require-spec", "--require-tasks", "--include-tasks").stdout)
        self.assertEqual(Path(prereq["FEATURE_DIR"]), feature)
        self.assertIn("tasks.md", prereq["AVAILABLE_DOCS"])

    def test_complete_delivery_passes(self):
        self.complete_artifacts()
        result = json.loads(self.sdd("check", "--require-complete").stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result["tasks"], 1)

    def test_incomplete_task_blocks_delivery_but_allows_planning(self):
        feature = self.complete_artifacts()
        (feature / "tasks.md").write_text("- [ ] T001 Implement calibration.\n", encoding="utf-8")
        self.sdd("check")
        result = json.loads(self.sdd("check", "--require-complete", code=1).stdout)
        self.assertEqual(result["unfinished"], ["T001"])

    def test_missing_evidence_and_unreviewed_checklist_block_delivery(self):
        feature = self.complete_artifacts()
        (feature / "evidence.md").unlink()
        (feature / "checklists").mkdir()
        (feature / "checklists/requirements.md").write_text("- [ ] Observable acceptance\n", encoding="utf-8")
        result = json.loads(self.sdd("check", "--require-complete", code=1).stdout)
        self.assertTrue(any("evidence.md" in error for error in result["errors"]))
        self.assertTrue(any("checklists/requirements.md" in error for error in result["errors"]))

    def test_duplicate_tasks_and_clarifications_are_rejected(self):
        feature = self.complete_artifacts()
        (feature / "tasks.md").write_text("- [X] T001 First\n- [X] T001 Duplicate\n", encoding="utf-8")
        (feature / "spec.md").write_text("[NEEDS CLARIFICATION: supported camera]\n", encoding="utf-8")
        result = json.loads(self.sdd("check", code=1).stdout)
        self.assertEqual(len(result["errors"]), 2)

    def test_fenced_examples_do_not_count_as_tasks(self):
        feature = self.complete_artifacts()
        (feature / "tasks.md").write_text("```text\n- [X] T001 Example\n```\n", encoding="utf-8")
        result = json.loads(self.sdd("check", code=1).stdout)
        self.assertEqual(result["tasks"], 0)

    def test_malformed_unfinished_task_cannot_hide_behind_completed_task(self):
        feature = self.complete_artifacts()
        with (feature / "tasks.md").open("a", encoding="utf-8") as task_file:
            task_file.write("- [ ] Missing task ID\n")
        result = json.loads(self.sdd("check", "--require-complete", code=1).stdout)
        self.assertTrue(any("malformed task" in error for error in result["errors"]))

    def test_explicit_check_is_read_only_and_wins_over_environment(self):
        self.complete_artifacts("first-feature")
        self.sdd("new", "second-feature")
        pointer = self.root / ".specify/feature.json"
        before = pointer.read_bytes()
        self.sdd("check", "--spec", ".scratch/first-feature", "--require-complete",
                 env={"SPECIFY_FEATURE_DIRECTORY": ".scratch/second-feature"})
        self.assertEqual(pointer.read_bytes(), before)


@unittest.skipUnless(importlib.util.find_spec("specify_cli"), "Install tooling/requirements-speckit.txt for upstream validation")
class WorkflowDefinitionTests(unittest.TestCase):
    def test_official_validator_accepts_every_installed_workflow(self):
        from specify_cli.workflows.engine import WorkflowDefinition, validate_workflow
        for path in (REPO / ".specify/workflows").glob("*/workflow.yml"):
            with self.subTest(workflow=path):
                self.assertEqual(validate_workflow(WorkflowDefinition.from_yaml(path)), [])

    def test_command_inputs_resolve_to_selected_feature(self):
        from specify_cli.workflows.base import StepContext
        from specify_cli.workflows.engine import WorkflowDefinition
        from specify_cli.workflows.expressions import evaluate_expression
        workflow = WorkflowDefinition.from_yaml(REPO / ".specify/workflows/company-network/workflow.yml")
        feature = str(REPO / "specs/007-example-feature")
        context = StepContext(inputs={"spec": "Calibrate camera"}, steps={
            "feature": {"output": {"data": {"FEATURE_DIR": feature}}},
            "analyze": {"output": {"stdout": "Analysis: requirements align."}},
        })
        for step in workflow.steps:
            if "command" in step:
                with self.subTest(step=step["id"]):
                    args = evaluate_expression(step["input"]["args"], context)
                    self.assertIn(f"SPECIFY_FEATURE_DIRECTORY={feature}", args)
                    self.assertNotIn("{{", args)
                    if step["id"] == "implement":
                        self.assertIn("Analysis: requirements align.", args)
                    skill = REPO / ".agents/skills" / step["command"].replace(".", "-") / "SKILL.md"
                    self.assertTrue(skill.is_file(), skill)


if __name__ == "__main__":
    unittest.main()
