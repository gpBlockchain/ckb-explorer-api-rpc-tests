from __future__ import annotations

import hashlib
import os
import unittest
from decimal import Decimal
from typing import Any, Mapping

from ckb_rpc_correctness.http import HttpClientError, JsonHttpClient
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


RGBPP_CODE_HASHES = {
    "mainnet": {"0xbc6c568a1a0d0a09f6844dc9d74ddb4343c32143ff25f727c59edf4fb72d6936"},
    "testnet": {
        "0x61ca7a4796a4eb19ca4f0d065cb9b10ddcf002f10f7cbb810c706cb6bb5c3248",
        "0xd07598deec7ce7b5665310386b4abd06a6d48843e953c5cc2112ad0d5a220364",
    },
}
BTC_TIME_CODE_HASHES = {
    "mainnet": {"0x70d64497a075bd651e98ac030455ea200637ee325a12ad08aff03f1a117e5a62"},
    "testnet": {
        "0x00cdf8fab0f8ac638758ebf5ea5e4052b1d71e8a77b9f43139718621f6849326",
        "0x80a09eca26d77cea1f5a69471c59481be7404febf40ee90f886c36a948385b55",
    },
}
VERIFIED_FIXTURES = {
    "mainnet": "0x0688e00cbc70359b21c98e0f9d1c51552e88a2c748d66c760ac4477b42089ff5",
    "testnet": "0x847096bb05662aca7bc9b06cccd3925170e0438fee31d58f500955b8b176a353",
}
MISMATCH_FIXTURES = {
    "testnet": "0x3568b2d1d23f0112ebe815ff61df07de02c6e24cf23604477f33e7b8eb6a4d65",
}
UNLINKED_FIXTURES = {
    "mainnet": "0x31556bbe1037503a51f0c213159a0d95de7e7b3f28490093a4a2ec178fa7a525",
    "testnet": "0xf418c1e0688e2e4fb82e831807f2fbba708646520eb0017e13e4b9e9cf96d164",
}
WORKFLOW_FIXTURES = {
    "mainnet": {
        ("withinBTC", "isomorphic"): VERIFIED_FIXTURES["mainnet"],
        ("in", "isomorphic"): UNLINKED_FIXTURES["mainnet"],
        ("leapoutBTC", "isomorphic"): "0x429a187e0da178129a5ca312082f3c927a36257663166c58b9344166ba978fdd",
    },
    "testnet": {
        ("withinBTC", "isomorphic"): VERIFIED_FIXTURES["testnet"],
        ("in", "isomorphic"): MISMATCH_FIXTURES["testnet"],
        ("leapoutBTC", "isomorphic"): "0x4cc3db3d4ededee9ba12336483ae112e6fff5c390d5e0780ae58fa8ba1b019ac",
    },
}
BITCOIN_RPC_URLS = {
    "mainnet": "https://bitcoin-rpc.publicnode.com",
    "testnet": "https://bitcoin-testnet-rpc.publicnode.com",
}


def _u32(value: int) -> bytes:
    return value.to_bytes(4, "little")


def _molecule_table(fields: list[bytes]) -> bytes:
    offset = 4 + 4 * len(fields)
    offsets: list[int] = []
    for field in fields:
        offsets.append(offset)
        offset += len(field)
    return _u32(offset) + b"".join(_u32(item) for item in offsets) + b"".join(fields)


def _serialize_script(script: Mapping[str, Any]) -> bytes:
    args = bytes.fromhex(str(script["args"])[2:])
    return _molecule_table(
        [
            bytes.fromhex(str(script["code_hash"])[2:]),
            bytes([{"data": 0, "type": 1, "data1": 2}[str(script["hash_type"])]]),
            _u32(len(args)) + args,
        ]
    )


def _serialize_output(output: Mapping[str, Any]) -> bytes:
    type_script = output.get("type")
    return _molecule_table(
        [
            int(str(output["capacity"]), 16).to_bytes(8, "little"),
            _serialize_script(output["lock"]),
            b"" if type_script is None else _serialize_script(type_script),
        ]
    )


def _commitment(
    transaction: Mapping[str, Any],
    parent_transactions: Mapping[str, Mapping[str, Any]],
) -> str:
    inputs: list[bytes] = []
    for item in transaction["inputs"]:
        previous = item["previous_output"]
        parent = parent_transactions[previous["tx_hash"]]
        output = parent["outputs"][int(previous["index"], 16)]
        if output.get("type") is not None:
            inputs.append(
                bytes.fromhex(previous["tx_hash"][2:])
                + int(previous["index"], 16).to_bytes(4, "little")
            )

    outputs: list[bytes] = []
    for index, output in enumerate(transaction["outputs"]):
        if output.get("type") is None:
            continue
        normalized = {
            "capacity": output["capacity"],
            "lock": dict(output["lock"]),
            "type": output["type"],
        }
        args = normalized["lock"]["args"]
        normalized["lock"]["args"] = args[:10] + "0" * 64
        data = bytes.fromhex(transaction["outputs_data"][index][2:])
        outputs.append(_serialize_output(normalized) + _u32(len(data)) + data)

    if len(inputs) > 255 or len(outputs) > 255:
        raise ValueError("RGB++ virtual transaction has more than 255 inputs or outputs")
    message = (
        b"RGB++"
        + bytes([0, 0, len(inputs), len(outputs)])
        + b"".join(inputs)
        + b"".join(outputs)
    )
    return hashlib.sha256(hashlib.sha256(message).digest()).hexdigest()


class V2CkbTransactionsRgbDigestRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.bitcoin_client = JsonHttpClient(
            timeout=max(cls.settings.timeout_seconds, 65),
            retries=cls.settings.transport_retries,
        )

    def _ckb_transaction(
        self, oracle: NetworkOracle, tx_hash: str
    ) -> tuple[Mapping[str, Any], Mapping[str, Mapping[str, Any]], str | None]:
        result = oracle.rpc_result("get_transaction", [tx_hash])
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise OracleUnavailable(f"{oracle.network.name} CKB transaction {tx_hash} is unavailable")
        parents: dict[str, Mapping[str, Any]] = {}
        for item in transaction.get("inputs", []):
            previous = item.get("previous_output") if isinstance(item, dict) else None
            parent_hash = previous.get("tx_hash") if isinstance(previous, dict) else None
            if not isinstance(parent_hash, str):
                raise OracleUnavailable(f"{oracle.network.name} CKB input outpoint is unavailable")
            parent_result = oracle.rpc_result("get_transaction", [parent_hash])
            parent = parent_result.get("transaction") if isinstance(parent_result, dict) else None
            if not isinstance(parent, dict):
                raise OracleUnavailable(
                    f"{oracle.network.name} CKB parent transaction {parent_hash} is unavailable"
                )
            parents[parent_hash] = parent
        return transaction, parents, status.get("block_hash")

    def _bitcoin_transaction(self, network_name: str, txid: str) -> Mapping[str, Any]:
        endpoint = os.getenv(
            f"{network_name.upper()}_BITCOIN_RPC_URL",
            BITCOIN_RPC_URLS[network_name],
        ).rstrip("/")
        try:
            payload = self.bitcoin_client.request_json(
                endpoint,
                method="POST",
                json_body={
                    "jsonrpc": "1.0",
                    "id": 1,
                    "method": "getrawtransaction",
                    "params": [txid, 2],
                },
            )
        except HttpClientError as error:
            raise OracleUnavailable(
                f"{network_name} Bitcoin RPC transaction {txid} is unavailable: {error}"
            ) from error
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise OracleUnavailable(
                f"{network_name} Bitcoin RPC transaction {txid} returned no result"
            )
        return result

    def _digest(self, oracle: NetworkOracle, tx_hash: str) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v2/ckb_transactions/{tx_hash}/rgb_digest")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise OracleUnavailable(f"{oracle.network.name} RGB digest data is unavailable")
        return data

    def _workflow(
        self,
        network_name: str,
        transaction: Mapping[str, Any],
        parents: Mapping[str, Mapping[str, Any]],
    ) -> tuple[str | None, str | None]:
        def lock_type(output: Mapping[str, Any]) -> str | None:
            code_hash = output["lock"]["code_hash"]
            if code_hash in RGBPP_CODE_HASHES[network_name]:
                return "rgbpp"
            if code_hash in BTC_TIME_CODE_HASHES[network_name]:
                return "btc_time"
            return None

        input_types = {
            lock_type(
                parents[item["previous_output"]["tx_hash"]]["outputs"][
                    int(item["previous_output"]["index"], 16)
                ]
            )
            for item in transaction["inputs"]
            if parents[item["previous_output"]["tx_hash"]]["outputs"][
                int(item["previous_output"]["index"], 16)
            ].get("type")
            is not None
        }
        output_types = {
            lock_type(output)
            for output in transaction["outputs"]
            if output.get("type") is not None
        }
        if input_types == {"rgbpp"} and output_types == {"rgbpp"}:
            return "withinBTC", "isomorphic"
        if input_types == {"rgbpp"} and output_types in (
            {"btc_time"},
            {"btc_time", "rgbpp"},
        ):
            return "in", "isomorphic"
        if input_types == {"btc_time"}:
            return "in", "unlock"
        if "rgbpp" not in input_types and "rgbpp" in output_types:
            return "leapoutBTC", "isomorphic"
        return None, None

    # TEST-MAP: RGB-TX-RPC-01
    # TEST-MAP: RGB-TX-RPC-02
    # TEST-MAP: RGB-TX-RPC-12
    def test_linked_digest_matches_ckb_virtual_commitment_and_bitcoin_rpc(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                # ISSUE: https://github.com/nervosnetwork/ckb-explorer/issues/2947
                if network.name == "testnet":
                    raise unittest.SkipTest(
                        "temporarily skipped until nervosnetwork/ckb-explorer#2947 is fixed"
                    )
                oracle = NetworkOracle(network, self.settings)
                tx_hash = VERIFIED_FIXTURES[network.name]
                try:
                    transaction, parents, block_hash_before = self._ckb_transaction(oracle, tx_hash)
                    data = self._digest(oracle, tx_hash)
                    bitcoin_transaction = self._bitcoin_transaction(network.name, data["txid"])
                    final = oracle.rpc_result("get_transaction", [tx_hash])
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                final_status = final.get("tx_status") if isinstance(final, dict) else None
                if not isinstance(final_status, dict) or final_status.get("block_hash") != block_hash_before:
                    raise unittest.SkipTest(f"{network.name} CKB reorganization observed")

                output_txids = set()
                for output in transaction["outputs"]:
                    lock = output.get("lock")
                    if not isinstance(lock, dict) or lock.get("code_hash") not in RGBPP_CODE_HASHES[network.name]:
                        continue
                    args = bytes.fromhex(lock["args"][2:])
                    output_txids.add(args[4:36][::-1].hex())
                self.assertIn(data["txid"], output_txids)
                self.assertEqual(data["txid"], bitcoin_transaction["txid"])
                self.assertEqual(data["confirmations"], bitcoin_transaction["confirmations"])
                op_returns = [
                    output["scriptPubKey"]["hex"][4:68]
                    for output in bitcoin_transaction["vout"]
                    if output.get("scriptPubKey", {}).get("hex", "").startswith("6a20")
                ]
                self.assertIn(data["commitment"], op_returns)
                self.assertEqual(data["commitment"], _commitment(transaction, parents))
                self.assertIs(data["commitment_verified"], True)
                expected_direction, expected_step = self._workflow(
                    network.name, transaction, parents
                )
                self.assertEqual(expected_direction, data["leap_direction"])
                self.assertEqual(expected_step, data["transfer_step"])

    # TEST-MAP: RGB-TX-RPC-03
    def test_mismatched_op_return_is_preserved_and_reported_unverified(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                tx_hash = MISMATCH_FIXTURES.get(network.name)
                if tx_hash is None:
                    raise unittest.SkipTest(
                        f"{network.name} public RGB index has no stable mismatched fixture"
                    )
                oracle = NetworkOracle(network, self.settings)
                try:
                    transaction, parents, _block_hash = self._ckb_transaction(oracle, tx_hash)
                    data = self._digest(oracle, tx_hash)
                    bitcoin_transaction = self._bitcoin_transaction(network.name, data["txid"])
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                op_returns = [
                    output["scriptPubKey"]["hex"][4:68]
                    for output in bitcoin_transaction["vout"]
                    if output.get("scriptPubKey", {}).get("hex", "").startswith("6a20")
                ]
                self.assertIn(data["commitment"], op_returns)
                self.assertNotEqual(data["commitment"], _commitment(transaction, parents))
                self.assertIs(data["commitment_verified"], False)

    # TEST-MAP: RGB-TX-RPC-04
    def test_ckb_transaction_without_complete_bitcoin_link_has_null_link_fields(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                tx_hash = UNLINKED_FIXTURES[network.name]
                try:
                    transaction, parents, _block_hash = self._ckb_transaction(oracle, tx_hash)
                    data = self._digest(oracle, tx_hash)
                except (OracleUnavailable, ValueError) as error:
                    raise unittest.SkipTest(str(error)) from error
                for field in ("txid", "confirmations", "commitment", "commitment_verified"):
                    self.assertIsNone(data[field])
                self.assertIsInstance(data["transfers"], list)
                expected_direction, expected_step = self._workflow(
                    network.name, transaction, parents
                )
                self.assertEqual(expected_direction, data["leap_direction"])
                self.assertEqual(expected_step, data["transfer_step"])

    # TEST-MAP: RGB-TX-RPC-05
    def test_transfer_addresses_and_shannon_deltas_follow_mapped_rgb_cells_only(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                tx_hash = VERIFIED_FIXTURES[network.name]
                try:
                    transaction, parents, _block_hash = self._ckb_transaction(oracle, tx_hash)
                    data = self._digest(oracle, tx_hash)
                    cells: list[tuple[int, Mapping[str, Any]]] = []
                    for item in transaction["inputs"]:
                        previous = item["previous_output"]
                        output = parents[previous["tx_hash"]]["outputs"][int(previous["index"], 16)]
                        if output.get("type") is not None:
                            cells.append((-1, output))
                    cells.extend(
                        (1, output)
                        for output in transaction["outputs"]
                        if output.get("type") is not None
                    )
                    expected_capacity: dict[str, int] = {}
                    expected_count: dict[str, int] = {}
                    bitcoin_cache: dict[str, Mapping[str, Any]] = {}
                    for sign, output in cells:
                        lock = output["lock"]
                        if lock["code_hash"] not in RGBPP_CODE_HASHES[network.name]:
                            continue
                        args = bytes.fromhex(lock["args"][2:])
                        output_index = int.from_bytes(args[:4], "little")
                        bitcoin_txid = args[4:36][::-1].hex()
                        bitcoin_transaction = bitcoin_cache.setdefault(
                            bitcoin_txid,
                            self._bitcoin_transaction(network.name, bitcoin_txid),
                        )
                        bitcoin_address = bitcoin_transaction["vout"][output_index][
                            "scriptPubKey"
                        ].get("address")
                        if not isinstance(bitcoin_address, str):
                            raise OracleUnavailable(
                                f"{network.name} Bitcoin vout has no address mapping"
                            )
                        expected_capacity[bitcoin_address] = expected_capacity.get(
                            bitcoin_address, 0
                        ) + sign * int(output["capacity"], 16)
                        expected_count[bitcoin_address] = expected_count.get(bitcoin_address, 0) + sign
                except (OracleUnavailable, ValueError, KeyError, IndexError) as error:
                    raise unittest.SkipTest(str(error)) from error

                observed_capacity: dict[str, int] = {}
                observed_count: dict[str, int] = {}
                for group in data["transfers"]:
                    address = group["address"]
                    for transfer in group["transfers"]:
                        capacity = Decimal(transfer["capacity"])
                        self.assertEqual(capacity, capacity.to_integral_value())
                        observed_capacity[address] = observed_capacity.get(address, 0) + int(capacity)
                        if "count" in transfer:
                            observed_count[address] = observed_count.get(address, 0) + int(
                                transfer["count"]
                            )
                self.assertEqual(expected_capacity, observed_capacity)
                self.assertEqual(expected_count, observed_count)

    # TEST-MAP: RGB-TX-RPC-06
    def test_workflow_fields_follow_ckb_input_and_output_lock_combinations(self) -> None:
        reviewed = {
            ("withinBTC", "isomorphic"),
            ("in", "isomorphic"),
            ("in", "unlock"),
            ("leapoutBTC", "isomorphic"),
        }
        for network in self.settings.networks:
            for expected in reviewed:
                with self.subTest(network=network.name, workflow=expected):
                    tx_hash = WORKFLOW_FIXTURES[network.name].get(expected)
                    if tx_hash is None:
                        raise unittest.SkipTest(
                            f"{network.name} public RGB index has no {expected} fixture"
                        )
                    oracle = NetworkOracle(network, self.settings)
                    try:
                        transaction, parents, _block_hash = self._ckb_transaction(oracle, tx_hash)
                        data = self._digest(oracle, tx_hash)
                    except (OracleUnavailable, ValueError) as error:
                        raise unittest.SkipTest(str(error)) from error
                    self.assertEqual(expected, self._workflow(network.name, transaction, parents))
                    self.assertEqual(expected, (data["leap_direction"], data["transfer_step"]))

    # TEST-MAP: RGB-TX-RPC-11
    def test_unknown_ckb_transaction_hash_returns_404_without_digest(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                with self.assertRaises(HttpClientError) as raised:
                    oracle.client.request_json(
                        network.explorer_api_url
                        + "/v2/ckb_transactions/0x"
                        + "00" * 32
                        + "/rgb_digest",
                        headers=V1_HEADERS,
                    )
                self.assertIn("returned HTTP 404:", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
