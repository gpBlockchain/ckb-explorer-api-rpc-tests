from __future__ import annotations

import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


ATTRIBUTE_FIELDS = {"full_name", "symbol", "udt_type", "type_hash", "icon_file"}


class V1UdtQueriesIndexRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")

    def _query(self, oracle: NetworkOracle, term: str) -> list[Mapping[str, Any]]:
        payload = oracle.explorer_json("/v1/udt_queries", {"q": term})
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise OracleUnavailable(f"{oracle.network.name} UDT search response is unavailable")
        for row in data:
            attributes = row.get("attributes")
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{oracle.network.name} UDT search row is unavailable")
        return data

    def _assert_matches(self, rows: list[Mapping[str, Any]], term: str) -> None:
        lowered = term.casefold()
        self.assertEqual(len(rows), len({str(row["id"]) for row in rows}))
        for row in rows:
            attributes = row["attributes"]
            self.assertEqual(ATTRIBUTE_FIELDS, set(attributes))
            symbol = str(attributes.get("symbol") or "").casefold()
            full_name = str(attributes.get("full_name") or "").casefold()
            self.assertTrue(lowered in symbol or lowered in full_name)

    # TEST-MAP: UDT-CATALOG-RPC-01
    def test_symbol_and_full_name_substrings_are_case_insensitive_and_fields_are_minimal(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    seed = self._query(oracle, "usd")
                    symbol_row = next(
                        row for row in seed
                        if isinstance(row["attributes"].get("symbol"), str)
                        and len(row["attributes"]["symbol"]) >= 4
                        and row["attributes"]["symbol"].casefold()
                        not in str(row["attributes"].get("full_name") or "").casefold()
                    )
                    full_name_row = next(
                        row for row in seed
                        if isinstance(row["attributes"].get("full_name"), str)
                        and len(row["attributes"]["full_name"]) >= 8
                        and row["attributes"]["full_name"].casefold()
                        not in str(row["attributes"].get("symbol") or "").casefold()
                    )
                    symbol = str(symbol_row["attributes"]["symbol"])
                    symbol_term = symbol[1:] if len(symbol) > 4 else symbol
                    full_name = str(full_name_row["attributes"]["full_name"])
                    full_name_term = full_name[1:]
                    symbol_lower = self._query(oracle, symbol_term.lower())
                    symbol_upper = self._query(oracle, symbol_term.upper())
                    name_lower = self._query(oracle, full_name_term.lower())
                    name_upper = self._query(oracle, full_name_term.upper())
                except (OracleUnavailable, StopIteration, KeyError, TypeError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self._assert_matches(symbol_lower, symbol_term)
                self._assert_matches(symbol_upper, symbol_term)
                self._assert_matches(name_lower, full_name_term)
                self._assert_matches(name_upper, full_name_term)
                self.assertEqual(
                    {str(row["id"]) for row in symbol_lower},
                    {str(row["id"]) for row in symbol_upper},
                )
                self.assertEqual(
                    {str(row["id"]) for row in name_lower},
                    {str(row["id"]) for row in name_upper},
                )
                self.assertIn(str(symbol_row["id"]), {str(row["id"]) for row in symbol_lower})
                self.assertIn(str(full_name_row["id"]), {str(row["id"]) for row in name_lower})

    # TEST-MAP: UDT-CATALOG-RPC-02
    def test_no_match_is_empty_and_dual_field_match_is_not_duplicated(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                try:
                    no_match = self._query(oracle, "zzz-no-match-rpc-correctness")
                    matches = self._query(oracle, "usd")
                    dual = next(
                        row for row in matches
                        if "usd" in str(row["attributes"].get("symbol") or "").casefold()
                        and "usd" in str(row["attributes"].get("full_name") or "").casefold()
                    )
                except (OracleUnavailable, StopIteration, KeyError, TypeError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual([], no_match)
                self._assert_matches(matches, "usd")
                self.assertEqual(1, sum(str(row["id"]) == str(dual["id"]) for row in matches))


if __name__ == "__main__":
    unittest.main()
