from __future__ import annotations

import json
import unittest
from decimal import Decimal, ROUND_DOWN

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings

from tests.contract_script.test_v2_scripts_ckb_transactions import _raw_explorer_response


class V1MonetaryDataShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    # TEST-MAP: ECON-RPC-07
    def test_default_and_custom_nominal_apc_have_exact_month_counts_and_halving_shape(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    default = oracle.explorer_json("/v1/monetary_data/nominal_apc")
                    custom = oracle.explorer_json("/v1/monetary_data/nominal_apc3")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                default_values = default.get("data", {}).get("attributes", {}).get("nominal_apc")
                custom_values = custom.get("data", {}).get("attributes", {}).get("nominal_apc")
                self.assertIsInstance(default_values, list)
                self.assertIsInstance(custom_values, list)
                self.assertEqual(240, len(default_values))
                self.assertEqual(36, len(custom_values))
                self.assertEqual(default_values[:36], custom_values)
                values = [Decimal(value) for value in default_values]
                self.assertEqual(Decimal("4.0"), values[0])
                self.assertTrue(all(left >= right for left, right in zip(values, values[1:])))
                self.assertLess(values[47] - values[48], values[46] - values[47])

    # TEST-MAP: ECON-RPC-08
    @unittest.expectedFailure
    def test_nominal_and_real_inflation_are_600_month_aligned_exact_decimal_series(self) -> None:
        indicator = "nominal_apc50-nominal_inflation_rate-real_inflation_rate"
        mismatches: list[str] = []
        for network in self.settings.networks:
            oracle = NetworkOracle(network, self.settings)
            try:
                payload = oracle.explorer_json(f"/v1/monetary_data/{indicator}")
            except OracleUnavailable as error:
                raise unittest.SkipTest(str(error)) from error
            attributes = payload.get("data", {}).get("attributes", {})
            apc = attributes.get("nominal_apc")
            nominal = attributes.get("nominal_inflation_rate")
            real = attributes.get("real_inflation_rate")
            self.assertEqual(600, len(apc))
            self.assertEqual(600, len(nominal))
            self.assertEqual(600, len(real))
            for index, (apc_value, nominal_value, real_value) in enumerate(zip(apc, nominal, real, strict=True)):
                expected = (Decimal(nominal_value) - Decimal(apc_value)).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )
                if expected != Decimal(real_value):
                    mismatches.append(f"{network.name}[{index}] expected {expected}, got {real_value}")
                self.assertRegex(str(real_value), r"^-?\d+(?:\.\d{1,8})?$")
        self.assertEqual([], mismatches)

    # TEST-MAP: ECON-RPC-09
    def test_unknown_monetary_model_returns_422_code_1024(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    status, raw = _raw_explorer_response(oracle, "/v1/monetary_data/not-a-model")
                except OracleUnavailable as error:
                    raise unittest.SkipTest(str(error)) from error
                body = json.loads(raw)
                self.assertEqual(422, status)
                self.assertIsInstance(body, list)
                self.assertEqual(1024, body[0].get("code"))
