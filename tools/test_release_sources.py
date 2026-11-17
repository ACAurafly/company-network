"""Exercise release selection against real tracked Git files after SDD setup."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from package_release import source_files


class ReleaseSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for name in ('bootstrap/Build.ps1', 'bootstrap/CompanyNetwork.ico',
                     'README.md', '员工说明.txt', 'tools/package_release.py'):
            self.track(name)

    def track(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('release fixture\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(self.root), 'add', '--', name], check=True,
                       capture_output=True)

    def test_governance_does_not_block_or_enter_employee_source_package(self):
        for name in ('AGENTS.md', 'CLAUDE.md', 'CONTRIBUTING.md', '.gitattributes',
                     '.github/workflows/sdd.yml', '.specify/templates/spec-template.md',
                     '.agents/skills/speckit-specify/SKILL.md', '.claude/skills/example/SKILL.md',
                     '.githooks/pre-commit', 'tooling/sdd.py', 'specs/007-example/spec.md'):
            self.track(name)
        sources = source_files(self.root)
        self.assertEqual(len(sources), 5)
        self.assertIn('bootstrap/Build.ps1', sources)
        self.assertIn('员工说明.txt', sources)

    def test_unknown_and_private_tracked_files_still_require_review(self):
        for name in ('unexpected.json', 'docs/credentials.md', '.github/credentials.txt'):
            with self.subTest(name=name):
                self.track(name)
                with self.assertRaisesRegex(ValueError, 'release review|allowlist'):
                    source_files(self.root)
                subprocess.run(['git', '-C', str(self.root), 'rm', '-q', '-f', '--', name], check=True)


if __name__ == '__main__':
    unittest.main()
