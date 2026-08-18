from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ckb_rpc_correctness.oracle import NetworkOracle
from ckb_rpc_correctness.settings import NetworkSettings, Settings


class NetworkOracleTests(unittest.TestCase):
    def test_completed_epoch_extrema_skips_epoch_with_unavailable_statistics(self) -> None:
        settings = Settings(
            settings_file=Path("networks.json"),
            run_live=False,
            timeout_seconds=1,
            transport_retries=0,
            max_lag_blocks=5,
            proposal_window=10,
            list_page_size=100,
            sample_search_pages=5,
            rpc_batch_size=100,
            networks=(),
        )
        network = NetworkSettings("mainnet", "https://explorer.invalid", "https://rpc.invalid", "ckb")
        oracle = NetworkOracle(network, settings)
        oracle.api_tip_height = Mock(return_value=250)  # type: ignore[method-assign]
        details = {
            250: {"start_number": "200"},
            199: {
                "epoch": "2",
                "start_number": "100",
                "length": "100",
                "largest_block_in_epoch": None,
                "max_cycles_in_epoch": None,
            },
            99: {
                "epoch": "1",
                "start_number": "98",
                "length": "2",
                "largest_block_in_epoch": 22,
                "max_cycles_in_epoch": 5,
            },
        }
        oracle.detail_attributes = Mock(side_effect=lambda height: details[int(height)])  # type: ignore[method-assign]
        oracle.rpc_batch_results = Mock(  # type: ignore[method-assign]
            return_value=[
                {"block": {"header": {"number": "0x62"}}, "cycles": ["0x3"]},
                {"block": {"header": {"number": "0x63"}}, "cycles": ["0x5"]},
            ]
        )

        with (
            patch(
                "ckb_rpc_correctness.oracle.serialized_block_size_without_uncle_proposals",
                side_effect=[11, 22],
            ),
            patch("ckb_rpc_correctness.oracle.block_cycles", side_effect=[3, 5]),
        ):
            extrema = oracle.completed_epoch_extrema()

        self.assertEqual([250, 199, 99], [call.args[0] for call in oracle.detail_attributes.call_args_list])
        self.assertEqual(1, extrema.epoch)
        self.assertEqual(98, extrema.start_height)
        self.assertEqual(2, extrema.length)
        self.assertEqual(22, extrema.largest_block)
        self.assertEqual(5, extrema.max_cycles)
        self.assertIs(extrema.attributes, details[99])


if __name__ == "__main__":
    unittest.main()
