from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ckb_rpc_correctness.settings import load_settings


class SettingsTests(unittest.TestCase):
    def test_defaults_declare_two_public_networks_and_five_block_lag(self) -> None:
        settings = load_settings(environ={})
        self.assertEqual(5, settings.max_lag_blocks)
        self.assertEqual(3, settings.transport_retries)
        self.assertEqual(5, settings.sample_search_pages)
        self.assertEqual(100, settings.rpc_batch_size)
        self.assertEqual(("mainnet", "testnet"), tuple(item.name for item in settings.networks))
        self.assertEqual(("ckb", "ckt"), tuple(item.address_hrp for item in settings.networks))

    def test_network_urls_can_be_overridden(self) -> None:
        settings = load_settings(
            environ={
                "MAINNET_EXPLORER_API_URL": "https://mainnet.example/api/",
                "MAINNET_CKB_RPC_URL": "https://mainnet-rpc.example/",
                "TESTNET_EXPLORER_API_URL": "https://testnet.example/api/",
                "TESTNET_CKB_RPC_URL": "https://testnet-rpc.example/",
                "RUN_LIVE_RPC_CORRECTNESS": "0",
            }
        )
        self.assertFalse(settings.run_live)
        self.assertEqual("https://mainnet.example/api", settings.networks[0].explorer_api_url)
        self.assertEqual("https://testnet-rpc.example", settings.networks[1].ckb_rpc_url)

    def test_missing_transport_retry_setting_defaults_to_three(self) -> None:
        payload = {
            "run_live": False,
            "networks": [
                {
                    "name": "testnet",
                    "explorer_api_url": "https://explorer.invalid/api",
                    "ckb_rpc_url": "https://rpc.invalid",
                    "address_hrp": "ckt",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "networks.json")
            path.write_text(json.dumps(payload))
            settings = load_settings(path, environ={})

        self.assertEqual(3, settings.transport_retries)


if __name__ == "__main__":
    unittest.main()
