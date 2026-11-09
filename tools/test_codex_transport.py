"""Regression checks for preserving private TOML and refusing unsafe edits."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import codex_transport as transport


class TransportTests(unittest.TestCase):
    def fixture(self, newline=b"\r\n", bom=b"\xef\xbb\xbf"):
        return bom + newline.join([
            b'model_provider = "OpenAI"', b'model = "unchanged"',
            b'[model_providers.OpenAI]', b'base_url = "http://example.invalid/v1"',
            b'api_key = "synthetic-secret"',
            b'supports_websockets = true # preserve this',
            b'[model_providers.Other]', b'supports_websockets = true', b'',
        ])

    def test_exact_bytes_preserved_for_bom_and_newlines(self):
        for newline in (b"\r\n", b"\n"):
            for bom in (b"\xef\xbb\xbf", b""):
                original = self.fixture(newline, bom)
                changed = transport.disable(original, "OpenAI", "http://example.invalid/v1")
                self.assertEqual(changed, original.replace(
                    b'true # preserve this', b'false # preserve this'))

    def test_wrong_provider_endpoint_or_state_refused(self):
        for provider, url, data in [
            ("Other", "http://example.invalid/v1", self.fixture()),
            ("OpenAI", "http://wrong.invalid/v1", self.fixture()),
            ("OpenAI", "http://example.invalid/v1", self.fixture().replace(b'true #', b'false #')),
        ]:
            with self.assertRaises(transport.Refused):
                transport.disable(data, provider, url)

    def test_misleading_multiline_text_cannot_be_changed(self):
        data = (b'model_provider = "OpenAI"\ntext = """\n'
                b'[model_providers.OpenAI]\nsupports_websockets = true\n"""\n'
                b'[model_providers.OpenAI]\nbase_url = "http://example.invalid/v1"\n'
                b'supports_websockets = true\n')
        with self.assertRaises(transport.Refused):
            transport.disable(data, "OpenAI", "http://example.invalid/v1")

    def test_rollback_refuses_later_changes(self):
        original = self.fixture()
        changed = transport.disable(original, "OpenAI", "http://example.invalid/v1")
        self.assertEqual(transport.restore_bytes(changed, original, "OpenAI", "http://example.invalid/v1"), original)
        with self.assertRaises(transport.Refused):
            transport.restore_bytes(changed + b'# later edit\n', original, "OpenAI", "http://example.invalid/v1")

    def test_cli_private_backup_and_rollback_without_secret_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "CodexPrivate").mkdir()
            config = root / "config.toml"
            config.write_bytes(self.fixture())
            command = [sys.executable, str(Path(transport.__file__)),
                       "--config", str(config), "--provider", "OpenAI",
                       "--expected-base-url", "http://example.invalid/v1"]
            env = dict(os.environ, LOCALAPPDATA=folder)
            applied = subprocess.run(command + ["--apply"], env=env, capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stdout)
            self.assertNotIn("synthetic-secret", applied.stdout + applied.stderr)
            report = json.loads(applied.stdout)
            backup = Path(report["private_backup"])
            self.assertTrue(backup.is_relative_to(root / "CodexPrivate"))
            self.assertEqual(backup.read_bytes(), self.fixture())
            reverted = subprocess.run(command + ["--rollback", str(backup)], env=env, capture_output=True, text=True)
            self.assertEqual(reverted.returncode, 0, reverted.stdout)
            self.assertEqual(config.read_bytes(), self.fixture())
            self.assertNotIn("synthetic-secret", reverted.stdout + reverted.stderr)


if __name__ == "__main__":
    unittest.main()
