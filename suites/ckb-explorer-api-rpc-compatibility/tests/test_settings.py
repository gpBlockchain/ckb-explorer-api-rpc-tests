from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ckb_api_compat.settings import DEFAULT_SETTINGS_FILE, load_settings


class RuntimeSettingsTests(unittest.TestCase):
    def test_checked_in_defaults_require_no_environment_variables(self) -> None:
        settings = load_settings(DEFAULT_SETTINGS_FILE, environ={})
        self.assertEqual("https://testnet-api-ckba.explorer.nervos.org/api", settings.baseline_url)
        self.assertEqual("https://testnet-api.explorer.nervos.org/api", settings.candidate_url)
        self.assertEqual("https://testnet.ckbapp.dev", settings.fixture_rpc_url)
        self.assertTrue(settings.run_live)
        self.assertTrue(settings.include_known_defects)
        self.assertTrue(settings.allow_mutations)
        self.assertTrue(settings.run_exports)
        self.assertTrue(settings.strict_fixtures)
        self.assertTrue(settings.print_responses)
        self.assertEqual(60.0, settings.timeout_seconds)
        self.assertEqual(1, settings.transport_retries)
        self.assertEqual("endpoints.json", settings.manifest_file.name)
        self.assertEqual("fixtures.example.json", settings.fixtures_file.name)

    def test_environment_variables_are_optional_overrides(self) -> None:
        settings = load_settings(
            DEFAULT_SETTINGS_FILE,
            environ={
                "RUN_LIVE_COMPAT": "false",
                "RUN_LIVE_KNOWN_DEFECTS": "0",
                "RUN_LIVE_MUTATIONS": "no",
                "RUN_LIVE_EXPORTS": "yes",
                "PRINT_RESPONSES": "false",
                "BASELINE_API_URL": "https://baseline.example/api/",
                "CANDIDATE_API_URL": "https://candidate.example/api/",
                "CKB_RPC_URL": "https://rpc.example/",
            },
        )
        self.assertFalse(settings.run_live)
        self.assertFalse(settings.include_known_defects)
        self.assertFalse(settings.allow_mutations)
        self.assertTrue(settings.run_exports)
        self.assertFalse(settings.print_responses)
        self.assertEqual("https://baseline.example/api", settings.baseline_url)
        self.assertEqual("https://candidate.example/api", settings.candidate_url)
        self.assertEqual("https://rpc.example", settings.fixture_rpc_url)

    def test_relative_manifest_and_fixture_paths_resolve_from_settings_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = json.loads(DEFAULT_SETTINGS_FILE.read_text(encoding="utf-8"))
            path = root / "settings.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            settings = load_settings(path, environ={})
            resolved = root.resolve()
            self.assertEqual(resolved / "endpoints.json", settings.manifest_file)
            self.assertEqual(resolved / "fixtures.example.json", settings.fixtures_file)

    def test_invalid_boolean_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "RUN_LIVE_COMPAT must be true or false"):
            load_settings(DEFAULT_SETTINGS_FILE, environ={"RUN_LIVE_COMPAT": "maybe"})


if __name__ == "__main__":
    unittest.main()
