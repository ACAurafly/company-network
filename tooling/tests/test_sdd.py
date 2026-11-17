import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "sdd.py"

class SddTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args], capture_output=True, text=True)

    def valid_spec(self, issue=7, completed=True):
        spec = self.root / "specs/007-example"
        spec.mkdir(parents=True)
        (spec / "spec.md").write_text(f"---\nid: 007-example\nissue: {issue}\nowner: ACAurafly\nstatus: implementing\npaths: [game/**]\n---\n# Example\n\n## Requirements\n- **FR-001**: Round-trip the exported level.\n", encoding="utf-8")
        (spec / "plan.md").write_text("# Plan\nReuse the existing loader and preserve version compatibility.\n", encoding="utf-8")
        mark = "x" if completed else " "
        (spec / "tasks.md").write_text(f"# Tasks\n- [{mark}] T001 [FR-001] Verify the loader.\n", encoding="utf-8")
        result = "passed" if completed else "pending"
        (spec / "verification.md").write_text(f"# Verification\n| Requirement | Evidence | Result |\n|---|---|---|\n| FR-001 | python -m pytest game/tests | {result} |\n", encoding="utf-8")
        return spec

    def test_complete_spec_passes(self):
        self.valid_spec()
        result = self.run_cli("check", "--require-complete")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_artifact_rejected(self):
        spec = self.valid_spec()
        (spec / "plan.md").unlink()
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("plan.md", result.stderr)

    def test_requirement_without_evidence_rejected(self):
        spec = self.valid_spec()
        with (spec / "spec.md").open("a") as f: f.write("- **FR-002**: Reject corrupt levels.\n")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FR-002", result.stderr)

    def test_incomplete_tasks_fail_ready_gate(self):
        self.valid_spec(completed=False)
        result = self.run_cli("check", "--require-complete")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("T001", result.stderr)

    def test_draft_pr_can_review_unfinished_work(self):
        self.valid_spec(completed=False)
        body = self.root / "body.md"; body.write_text("Spec: specs/007-example\n")
        result = self.run_cli("check", "--pr-body", str(body), "--draft")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ready_pr_requires_linked_issue(self):
        self.valid_spec(issue="null")
        body = self.root / "body.md"; body.write_text("Spec: specs/007-example\n")
        result = self.run_cli("check", "--pr-body", str(body))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("issue", result.stderr.lower())

    def test_pr_cannot_select_outside_spec_directory(self):
        self.valid_spec()
        body = self.root / "body.md"; body.write_text("Spec: specs/../../outside\n")
        result = self.run_cli("check", "--pr-body", str(body))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Spec:", result.stderr)

    def test_pr_missing_spec_line_rejected(self):
        self.valid_spec()
        body = self.root / "body.md"; body.write_text("Just a tiny doc fix.\n")
        result = self.run_cli("check", "--pr-body", str(body))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Spec:", result.stderr)

    def test_pr_event_does_not_execute_body(self):
        self.valid_spec(completed=False)
        event = self.root / "event.json"
        event.write_text(json.dumps({"pull_request": {"body": "Spec: specs/007-example\n$(touch injected)", "draft": True}}))
        result = self.run_cli("check", "--event", str(event))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "injected").exists())

    def test_new_feature_creates_full_scaffold_and_preserves_duplicate(self):
        templates = self.root / ".specify/templates"; templates.mkdir(parents=True)
        for name in ("spec", "plan", "tasks", "verification"):
            (templates / f"{name}-template.md").write_text("# {{FEATURE_ID}}\nIssue: {{ISSUE}}\n")
        result = self.run_cli("new", "shared-level", "--issue", "21")
        self.assertEqual(result.returncode, 0, result.stderr)
        feature = self.root / "specs/021-shared-level"
        self.assertEqual({p.name for p in feature.iterdir()}, {"spec.md", "plan.md", "tasks.md", "verification.md"})
        before = (feature / "spec.md").read_text()
        duplicate = self.run_cli("new", "shared-level", "--issue", "21")
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual((feature / "spec.md").read_text(), before)

    def test_new_feature_rejects_path_traversal(self):
        result = self.run_cli("new", "../outside", "--issue", "21")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("slug", result.stderr.lower())

    def test_current_feature_follows_explicit_selection_without_replacing_state(self):
        self.valid_spec()
        folder = self.root / ".specify"
        folder.mkdir()
        pointer = folder / "feature.json"
        pointer.write_text(json.dumps({"feature_directory": "specs/999-missing"}))
        before = pointer.read_bytes()
        env = dict(os.environ, SPECIFY_FEATURE_DIRECTORY="specs/007-example")
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "current"],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["RELATIVE_DIR"], "specs/007-example")
        self.assertEqual(pointer.read_bytes(), before)

    def test_new_feature_can_be_read_by_workflow_current_step(self):
        templates = self.root / ".specify/templates"
        templates.mkdir(parents=True)
        for name in ("spec", "plan", "tasks", "verification"):
            (templates / f"{name}-template.md").write_text("# {{FEATURE_ID}}\nIssue: {{ISSUE}}\n")
        self.assertEqual(self.run_cli("new", "example", "--issue", "7").returncode, 0)
        env = {key: value for key, value in os.environ.items() if key != "SPECIFY_FEATURE_DIRECTORY"}
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "current"],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["RELATIVE_DIR"], "specs/007-example")

    def test_current_rejects_missing_or_outside_selection(self):
        folder = self.root / ".specify"
        folder.mkdir()
        for value in ("specs/999-missing", "../outside"):
            (folder / "feature.json").write_text(json.dumps({"feature_directory": value}))
            env = {key: val for key, val in os.environ.items() if key != "SPECIFY_FEATURE_DIRECTORY"}
            result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "current"],
                                    capture_output=True, text=True, env=env)
            self.assertNotEqual(result.returncode, 0)

    def test_absolute_spec_outside_repo_is_rejected(self):
        spec = self.valid_spec()
        result = self.run_cli("check", "--spec", str(spec))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("relative", result.stderr.lower())

    def test_symlink_spec_outside_repo_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "specs").mkdir()
            link = self.root / "specs/007-example"
            if os.name == "nt":
                # Directory junctions need no Windows symlink privilege and still
                # exercise resolve() escaping the permitted specification root.
                import _winapi
                _winapi.CreateJunction(outside, str(link))
            else:
                link.symlink_to(outside, target_is_directory=True)
            result = self.run_cli("check", "--spec", "specs/007-example")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside", result.stderr.lower())

    def test_invalid_metadata_returns_clean_error(self):
        spec = self.valid_spec()
        (spec / "spec.md").write_text("---\nid: [unclosed\n---\n**FR-001**: test")
        result = self.run_cli("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_status_rejected(self):
        spec = self.valid_spec()
        file = spec / "spec.md"
        file.write_text(file.read_text().replace("status: implementing\n", ""))
        self.assertNotEqual(self.run_cli("check").returncode, 0)

    def test_duplicate_requirement_evidence_rejected(self):
        spec = self.valid_spec()
        with (spec / "verification.md").open("a") as f:
            f.write("| FR-001 | actual test failed | failed |\n| FR-001 | overwrite | passed |\n")
        self.assertNotEqual(self.run_cli("check", "--require-complete").returncode, 0)

    def test_sync_check_detects_drift_without_modifying_files(self):
        (self.root / "AGENTS.md").write_text("# Rules\n")
        source = self.root / "tooling/skills/company-reference/SKILL.md"
        source.parent.mkdir(parents=True)
        source.write_text("# Reference\n")
        self.assertEqual(self.run_cli("sync-agents").returncode, 0)
        generated = self.root / "CLAUDE.md"
        generated.write_text("# Changed\n")
        result = self.run_cli("sync-agents", "--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(generated.read_text(), "# Changed\n")

    def test_contract_fixture_violation_is_rejected(self):
        folder = self.root / "contracts/fixtures"; folder.mkdir(parents=True)
        schema = {"$schema":"https://json-schema.org/draft/2020-12/schema", "type":"object", "properties":{"schema":{"const":"example/1"},"count":{"type":"integer","minimum":1}},"required":["schema","count"]}
        (folder.parent / "example.schema.json").write_text(json.dumps(schema))
        fixture = folder / "example.json"
        fixture.write_text(json.dumps({"schema":"example/1","count":0}))
        self.assertNotEqual(self.run_cli("contracts").returncode, 0)
        fixture.write_text(json.dumps({"schema":"example/1","count":1}))
        self.assertEqual(self.run_cli("contracts").returncode, 0)

    def test_nested_contract_fixture_resolves_shared_definitions(self):
        folder = self.root / "contracts/fixtures/nested"
        folder.mkdir(parents=True)
        schemas = self.root / "contracts/nested"
        schemas.mkdir()
        base = "https://example.invalid/nested/"
        common = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": base + "common.schema.json",
                  "$defs": {"positive": {"type": "integer", "minimum": 1}}}
        document = {"$schema": common["$schema"], "$id": base + "document.schema.json", "type": "object",
                    "properties": {"schema": {"const": "nested/1"}, "count": {"$ref": "common.schema.json#/$defs/positive"}},
                    "required": ["schema", "count"]}
        (schemas / "common.schema.json").write_text(json.dumps(common))
        (schemas / "document.schema.json").write_text(json.dumps(document))
        fixture = folder / "valid.json"
        fixture.write_text(json.dumps({"schema": "nested/1", "count": 1}))
        result = self.run_cli("contracts")
        self.assertEqual(result.returncode, 0, result.stderr)
        fixture.write_text(json.dumps({"schema": "nested/1", "count": 0}))
        self.assertNotEqual(self.run_cli("contracts").returncode, 0)

    def test_git_diff_rejects_change_outside_declared_scope(self):
        self.valid_spec()
        def git(*args):
            return subprocess.run(["git",*args],cwd=self.root,capture_output=True,text=True,check=True).stdout.strip()
        git("init");git("config","user.name","Test");git("config","user.email","test@example.invalid")
        git("add",".");git("commit","-m","baseline")
        base = git("rev-parse","HEAD")
        (self.root / "unrelated.md").write_text("out of scope")
        git("add",".");git("commit","-m","unrelated")
        result = self.run_cli("check","--spec","specs/007-example","--base",base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrelated.md",result.stderr)

    def test_git_diff_accepts_chinese_path_in_declared_scope(self):
        spec = self.valid_spec()
        file = spec / "spec.md"
        file.write_text(file.read_text().replace("paths: [game/**]","paths: [docs/**]"))
        def git(*args):
            return subprocess.run(["git",*args],cwd=self.root,capture_output=True,text=True,check=True).stdout.strip()
        git("init");git("config","user.name","Test");git("config","user.email","test@example.invalid")
        git("add",".");git("commit","-m","baseline")
        base = git("rev-parse","HEAD")
        (self.root/"docs").mkdir()
        (self.root/"docs/方案综述与流程.md").write_text("in scope")
        git("add",".");git("commit","-m","docs")
        result = self.run_cli("check","--spec","specs/007-example","--base",base)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_removed_skill_is_detected_and_cleaned_across_integrations(self):
        (self.root/"AGENTS.md").write_text("# Rules")
        folder = self.root/"tooling/skills"
        for name in ("company-keep","company-remove"):
            source = folder/name/"SKILL.md";source.parent.mkdir(parents=True)
            source.write_text("# Reference")
        self.assertEqual(self.run_cli("sync-agents").returncode,0)
        (folder/"company-remove/SKILL.md").unlink()
        (self.root/".agents/skills/company-remove/SKILL.md").unlink()
        result = self.run_cli("sync-agents","--check")
        self.assertNotEqual(result.returncode,0)
        self.assertIn("company-remove",result.stderr)
        self.assertTrue((self.root/".claude/skills/company-remove/SKILL.md").exists())
        self.assertEqual(self.run_cli("sync-agents").returncode,0)
        for integration in (".agents",".claude",".github"):
            self.assertFalse((self.root/integration/"skills/company-remove").exists())
            self.assertTrue((self.root/integration/"skills/company-keep/SKILL.md").exists())

if __name__ == "__main__": unittest.main()
