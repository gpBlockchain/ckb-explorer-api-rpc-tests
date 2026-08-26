from __future__ import annotations

import json
import socket
import time
import unittest
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import ckb_script_hash, decode_hex_int, output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable, V1_HEADERS
from ckb_rpc_correctness.settings import load_settings


ZERO_TX_HASH = "0x" + "00" * 32
DAO_CODE_HASH = "0x82d76d1b75fe2fd9a27dfbaa65a039221a380d76c926f378d3f81cf3e7e13f2e"


@dataclass(frozen=True)
class UdtFixture:
    transaction_hash: str
    type_hash: str
    cell_type: str


@dataclass(frozen=True)
class DetailsNetworkFixture:
    ordinary_transaction_hash: str
    cellbase_transaction_hash: str
    udt: UdtFixture
    large_capacity_transaction_hash: str
    large_udt: UdtFixture
    dao_transaction_hash: str
    nft_transaction_hash: str
    nft_code_hash: str


DETAILS_FIXTURES = {
    "mainnet": DetailsNetworkFixture(
        ordinary_transaction_hash="0xb1c468e47a507425814fea33402ed50fe800899d975875033f992a9cb19419b7",
        cellbase_transaction_hash="0xae1fa53d770c7571de66c7373528508c4591edca36f7e870c307cd1f88d7e3a4",
        udt=UdtFixture(
            transaction_hash="0x2afff0376860381cab26f9ffdcce08f6eca0ce66d0e02643150e5960577a5f48",
            type_hash="0x59f9e9966f4b0e8578c1b73fb3eb06241607bff05e17d7869d4a17293303a27b",
            cell_type="xudt",
        ),
        large_capacity_transaction_hash=(
            "0x82de2ec0cf9ae0a1b21e88f2b7bc301d487c21560ee739a8bcbb6a5692cf5225"
        ),
        large_udt=UdtFixture(
            transaction_hash="0x0ee00d6aaafa6ee798bacf4a22f417f98478aab23997c3c5a312159bd81a2381",
            type_hash="0x471bed3f26611ef8af6be47de72520f110763692e77f19d0d15b9cb7fa6a072c",
            cell_type="udt",
        ),
        dao_transaction_hash="0x315eb9a89c36ac82e8c5fcaa9a19e029b71570269186ea9f62ffc699ae4d50bb",
        nft_transaction_hash="0x0d615377af6eca7ba75c9a6133b3ea9ff4a7805f680beafacd7b1e0d0f2692b9",
        nft_code_hash="0x4a4dce1df3dffff7f8b2cd7dff7303df3b6150c9788cb75dcf6747247132b9f5",
    ),
    "testnet": DetailsNetworkFixture(
        ordinary_transaction_hash="0x7340b4de9ddc23af6554106bac01a91f0fc5e669cbbd91c12415c87964784def",
        cellbase_transaction_hash="0xa3ca91e5368fafec9c61ac3c94152436cb3e8329af078a3ceee66bbd63af8016",
        udt=UdtFixture(
            transaction_hash="0x3c57557ef883e1c2388678e6a284f1e221d9b4a7dfdd341729da147254ec5712",
            type_hash="0x3b6afac4101eea2e297c4270ab0e4e3cc0d3d9ab882025b2b0b9face48249204",
            cell_type="udt",
        ),
        large_capacity_transaction_hash=(
            "0xf1675c536b534a0a6298aeceeabe0808f39076d3ea31a5b99036a81d66696148"
        ),
        large_udt=UdtFixture(
            transaction_hash="0x60d54e88dec09f39da3ef1bb87886f5d7876db13b9c76fa51a494db73e7b5500",
            type_hash="0x97ee3842e73dae57fb0cf5d09305bc619b1624e927c91a6fe543121e482e6d1e",
            cell_type="xudt",
        ),
        dao_transaction_hash="0x25cc211764095166c16be8dfb32e141a334ae847bcde49979430a80899d2c3c9",
        nft_transaction_hash="0xaf0e27b58f9131b1e6fd1080e680854794437ba08f9939c74de2cd42748dd395",
        nft_code_hash="0x685a60219309029d01310311dba953d67029170ca4848a4ff638e57002130a0d",
    ),
}


class _StatusPreservingProcessor(urllib.request.HTTPErrorProcessor):
    def http_response(self, request: urllib.request.Request, response: Any) -> Any:
        return response

    https_response = http_response


def _explorer_response(oracle: NetworkOracle, path: str) -> tuple[int, Any, bytes]:
    url = oracle.network.explorer_api_url + path
    headers = dict(V1_HEADERS)
    headers["User-Agent"] = oracle.client.user_agent
    opener = urllib.request.build_opener(_StatusPreservingProcessor())

    for attempt in range(oracle.client.retries + 1):
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with opener.open(request, timeout=oracle.client.timeout) as response:
                raw = response.read(oracle.client.max_body_bytes + 1)
                status = int(response.status)
            if len(raw) > oracle.client.max_body_bytes:
                raise OracleUnavailable(
                    f"{oracle.network.name} Explorer {path} exceeds "
                    f"{oracle.client.max_body_bytes} bytes"
                )
            if attempt < oracle.client.retries and (status == 429 or status >= 500):
                time.sleep(0.2 * (attempt + 1))
                continue
            if not raw:
                return status, None, raw
            try:
                return status, json.loads(raw), raw
            except json.JSONDecodeError as error:
                raise OracleUnavailable(
                    f"{oracle.network.name} Explorer {path} returned invalid JSON: {error}"
                ) from error
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as error:
            if attempt < oracle.client.retries:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise OracleUnavailable(
                f"{oracle.network.name} Explorer {path} transport failure: "
                f"{type(error).__name__}: {error}"
            ) from error
    raise AssertionError("unreachable HTTP retry loop")


class V2CkbTransactionsDetailsRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.oracles = tuple(NetworkOracle(network, cls.settings) for network in cls.settings.networks)
        cls.samples: dict[
            tuple[str, str],
            tuple[Mapping[str, Any], list[tuple[Mapping[str, Any], object]], Mapping[str, Any]],
        ] = {}
        cls.checked_networks: set[str] = set()

    def _assert_network_pair(self, oracle: NetworkOracle) -> None:
        if oracle.network.name in self.checked_networks:
            return
        try:
            api_genesis = oracle.detail_attributes(0)
            rpc_genesis = oracle.block(0)
            api_tip = oracle.api_tip_height()
            rpc_tip = oracle.rpc_tip_height()
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        rpc_header = rpc_genesis.get("header")
        self.assertIsInstance(rpc_header, dict)
        self.assertEqual(rpc_header.get("hash"), api_genesis.get("block_hash"))
        self.assertLessEqual(api_tip, rpc_tip)
        self.assertLessEqual(rpc_tip - api_tip, self.settings.max_lag_blocks)
        self.checked_networks.add(oracle.network.name)

    def _load_sample(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
    ) -> tuple[Mapping[str, Any], list[tuple[Mapping[str, Any], object]], Mapping[str, Any]]:
        key = (oracle.network.name, transaction_hash)
        if key in self.samples:
            return self.samples[key]
        self._assert_network_pair(oracle)
        try:
            result = oracle.rpc_result("get_transaction", [transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        transaction = result.get("transaction") if isinstance(result, dict) else None
        status = result.get("tx_status") if isinstance(result, dict) else None
        if not isinstance(transaction, dict) or not isinstance(status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {transaction_hash} is unavailable"
            )

        inputs = transaction.get("inputs")
        self.assertIsInstance(inputs, list)
        is_cellbase = bool(inputs) and all(
            isinstance(item, dict)
            and isinstance(item.get("previous_output"), dict)
            and item["previous_output"].get("tx_hash") == ZERO_TX_HASH
            for item in inputs
        )
        try:
            referenced_outputs = [] if is_cellbase else oracle.referenced_outputs(transaction)
            block_hash = status.get("block_hash")
            if not isinstance(block_hash, str):
                raise OracleUnavailable(
                    f"{oracle.network.name} RPC transaction {transaction_hash} has no block hash"
                )
            block = oracle.block_by_hash(block_hash)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error

        block_transactions = block.get("transactions")
        self.assertIsInstance(block_transactions, list)
        self.assertEqual("committed", status.get("status"))
        self.assertEqual(transaction_hash, transaction.get("hash"))
        if not is_cellbase:
            self.assertEqual(len(inputs), len(referenced_outputs))
        tx_index = decode_hex_int(status.get("tx_index"), "tx_status.tx_index")
        self.assertEqual(transaction_hash, block_transactions[tx_index].get("hash"))
        self.samples[key] = transaction, referenced_outputs, status
        return self.samples[key]

    def _assert_sample_stable(
        self,
        oracle: NetworkOracle,
        transaction_hash: str,
        initial_status: Mapping[str, Any],
    ) -> None:
        try:
            fresh_result = oracle.rpc_result("get_transaction", [transaction_hash])
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        fresh_status = fresh_result.get("tx_status") if isinstance(fresh_result, dict) else None
        if not isinstance(fresh_status, dict):
            raise unittest.SkipTest(
                f"{oracle.network.name} RPC transaction {transaction_hash} became unavailable"
            )
        if (
            fresh_status.get("status") != initial_status.get("status")
            or fresh_status.get("block_hash") != initial_status.get("block_hash")
        ):
            raise unittest.SkipTest(
                f"{oracle.network.name} transaction {transaction_hash} changed status or block"
            )

    def _details(self, oracle: NetworkOracle, transaction_hash: str) -> list[Mapping[str, Any]]:
        path = f"/v2/ckb_transactions/{transaction_hash}/details"
        try:
            status, payload, raw = _explorer_response(oracle, path)
        except OracleUnavailable as error:
            raise unittest.SkipTest(str(error)) from error
        context = (
            f"{oracle.network.name} tx={transaction_hash} status={status} "
            f"body={raw[:1000]!r}"
        )
        self.assertEqual(200, status, context)
        data = payload.get("data") if isinstance(payload, dict) else None
        self.assertIsInstance(data, list, context)
        rows: list[Mapping[str, Any]] = []
        seen_addresses: set[str] = set()
        for index, row in enumerate(data):
            self.assertIsInstance(row, dict, f"{context} data[{index}]")
            address = row.get("address")
            transfers = row.get("transfers")
            self.assertIsInstance(address, str, f"{context} data[{index}].address")
            self.assertNotIn(address, seen_addresses, f"{context} duplicate address={address}")
            self.assertIsInstance(transfers, list, f"{context} address={address}")
            self.assertTrue(transfers, f"{context} address={address} has no transfers")
            self.assertTrue(
                all(isinstance(transfer, dict) for transfer in transfers),
                f"{context} address={address} has a non-object transfer",
            )
            seen_addresses.add(address)
            rows.append(row)
        return rows

    def _integer(self, value: object, field: str) -> int:
        try:
            decimal = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            self.fail(f"{field} is not a decimal number: {value!r}; {error}")
        self.assertTrue(decimal.is_finite(), f"{field} must be finite: {value!r}")
        self.assertEqual(decimal, decimal.to_integral_value(), f"{field} is not an integer: {value!r}")
        return int(decimal)

    def _normal_expected(
        self,
        oracle: NetworkOracle,
        transaction: Mapping[str, Any],
        referenced_outputs: list[tuple[Mapping[str, Any], object]],
    ) -> tuple[dict[str, int], dict[str, tuple[int, int]]]:
        capacities: defaultdict[str, int] = defaultdict(int)
        counts: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
        for output, _data in referenced_outputs:
            address = output_address(output, oracle.network.address_hrp)
            capacities[address] -= decode_hex_int(output.get("capacity"), "input.capacity")
            counts[address][0] += 1
        outputs = transaction.get("outputs")
        self.assertIsInstance(outputs, list)
        for output in outputs:
            self.assertIsInstance(output, dict)
            address = output_address(output, oracle.network.address_hrp)
            capacities[address] += decode_hex_int(output.get("capacity"), "output.capacity")
            counts[address][1] += 1
        return dict(capacities), {address: tuple(value) for address, value in counts.items()}

    def _normal_actual(
        self,
        rows: list[Mapping[str, Any]],
        *,
        require_only_normal: bool,
    ) -> dict[str, int]:
        actual: dict[str, int] = {}
        for row in rows:
            address = str(row["address"])
            transfers = row["transfers"]
            normal = [item for item in transfers if item.get("cell_type") == "normal"]
            self.assertEqual(1, len(normal), f"address={address} normal transfers={normal!r}")
            if require_only_normal:
                self.assertEqual(normal, transfers, f"address={address} unexpected transfers={transfers!r}")
            actual[address] = self._integer(normal[0].get("capacity"), f"{address}.normal.capacity")
        return actual

    def _udt_expected(
        self,
        oracle: NetworkOracle,
        transaction: Mapping[str, Any],
        referenced_outputs: list[tuple[Mapping[str, Any], object]],
        fixture: UdtFixture,
    ) -> dict[tuple[str, str, str], tuple[int, int]]:
        changes: defaultdict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])

        def add(output: Mapping[str, Any], data: object, direction: int, field: str) -> None:
            type_script = output.get("type")
            if not isinstance(type_script, dict) or ckb_script_hash(type_script) != fixture.type_hash:
                return
            self.assertIsInstance(data, str, f"{field}.data")
            try:
                raw = bytes.fromhex(data.removeprefix("0x"))
            except ValueError as error:
                self.fail(f"{field}.data contains invalid hexadecimal bytes: {error}")
            self.assertGreaterEqual(len(raw), 16, f"{field}.data has no 128-bit amount")
            address = output_address(output, oracle.network.address_hrp)
            key = (address, fixture.type_hash, fixture.cell_type)
            changes[key][0] += direction * decode_hex_int(output.get("capacity"), f"{field}.capacity")
            changes[key][1] += direction * int.from_bytes(raw[:16], "little")

        for index, (output, data) in enumerate(referenced_outputs):
            add(output, data, -1, f"inputs[{index}]")
        outputs = transaction.get("outputs")
        outputs_data = transaction.get("outputs_data")
        self.assertIsInstance(outputs, list)
        self.assertIsInstance(outputs_data, list)
        self.assertEqual(len(outputs), len(outputs_data))
        for index, (output, data) in enumerate(zip(outputs, outputs_data, strict=True)):
            self.assertIsInstance(output, dict)
            add(output, data, 1, f"outputs[{index}]")
        self.assertTrue(changes, f"fixture {fixture.transaction_hash} has no {fixture.type_hash} cells")
        return {key: tuple(value) for key, value in changes.items()}

    def _udt_actual(
        self,
        rows: list[Mapping[str, Any]],
        fixture: UdtFixture,
    ) -> dict[tuple[str, str, str], tuple[int, int]]:
        actual: dict[tuple[str, str, str], tuple[int, int]] = {}
        for row in rows:
            address = str(row["address"])
            for index, transfer in enumerate(row["transfers"]):
                if transfer.get("cell_type") != fixture.cell_type:
                    continue
                info = transfer.get("udt_info")
                self.assertIsInstance(info, dict, f"{address}.transfers[{index}].udt_info")
                type_hash = info.get("type_hash")
                self.assertEqual(fixture.type_hash, type_hash)
                key = (address, str(type_hash), fixture.cell_type)
                self.assertNotIn(key, actual, f"duplicate UDT aggregate {key}")
                actual[key] = (
                    self._integer(transfer.get("capacity"), f"{key}.capacity"),
                    self._integer(info.get("amount"), f"{key}.amount"),
                )
        return actual

    # TEST-MAP: CKB-TX-VIEWS-RPC-01
    def test_ordinary_ckb_changes_match_rpc_by_address(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                fixture = DETAILS_FIXTURES[oracle.network.name]
                transaction, references, status = self._load_sample(
                    oracle, fixture.ordinary_transaction_hash
                )
                expected, counts = self._normal_expected(oracle, transaction, references)
                self.assertTrue(any(inputs and outputs for inputs, outputs in counts.values()))
                self.assertTrue(any((inputs == 0) != (outputs == 0) for inputs, outputs in counts.values()))
                rows = self._details(oracle, fixture.ordinary_transaction_hash)
                actual = self._normal_actual(rows, require_only_normal=True)
                self.assertEqual(expected, actual)
                total_inputs = sum(
                    decode_hex_int(output.get("capacity"), "input.capacity")
                    for output, _data in references
                )
                outputs = transaction.get("outputs")
                self.assertIsInstance(outputs, list)
                total_outputs = sum(
                    decode_hex_int(output.get("capacity"), "output.capacity")
                    for output in outputs
                )
                self.assertEqual(total_outputs - total_inputs, sum(actual.values()))
                self._assert_sample_stable(oracle, fixture.ordinary_transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-02
    def test_cellbase_changes_equal_positive_rpc_outputs(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                fixture = DETAILS_FIXTURES[oracle.network.name]
                transaction, references, status = self._load_sample(
                    oracle, fixture.cellbase_transaction_hash
                )
                self.assertEqual([], references)
                expected, _counts = self._normal_expected(oracle, transaction, references)
                self.assertTrue(all(capacity > 0 for capacity in expected.values()))
                rows = self._details(oracle, fixture.cellbase_transaction_hash)
                actual = self._normal_actual(rows, require_only_normal=True)
                self.assertEqual(expected, actual)
                self.assertEqual(sum(expected.values()), sum(actual.values()))
                self._assert_sample_stable(oracle, fixture.cellbase_transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-03
    def test_udt_changes_match_rpc_amount_capacity_and_type_hash(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                fixture = DETAILS_FIXTURES[oracle.network.name].udt
                transaction, references, status = self._load_sample(
                    oracle, fixture.transaction_hash
                )
                expected = self._udt_expected(oracle, transaction, references, fixture)
                rows = self._details(oracle, fixture.transaction_hash)
                actual = self._udt_actual(rows, fixture)
                self.assertEqual(expected, actual)
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-04
    @unittest.expectedFailure
    def test_large_ckb_changes_remain_exact_decimal_integers(self) -> None:
        observed_mismatches: list[str] = []
        compared_networks = 0
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DETAILS_FIXTURES[
                    oracle.network.name
                ].large_capacity_transaction_hash
                transaction, references, status = self._load_sample(oracle, transaction_hash)
                expected, _counts = self._normal_expected(oracle, transaction, references)
                self.assertTrue(
                    any(
                        abs(value) > 2**53 and int(float(value)) != value
                        for value in expected.values()
                    ),
                    f"{oracle.network.name} fixture has no inexact >2^53 net capacity",
                )
                rows = self._details(oracle, transaction_hash)
                scientific_capacities: list[str] = []
                for row in rows:
                    for transfer in row["transfers"]:
                        if transfer.get("cell_type") == "normal":
                            rendered = str(transfer.get("capacity"))
                            if "e" in rendered.lower():
                                scientific_capacities.append(rendered)
                actual = self._normal_actual(rows, require_only_normal=True)
                if scientific_capacities or expected != actual:
                    observed_mismatches.append(
                        f"{oracle.network.name}: scientific={scientific_capacities!r}; "
                        f"expected={expected!r}; actual={actual!r}"
                    )
                compared_networks += 1
                self._assert_sample_stable(oracle, transaction_hash, status)
        if compared_networks < len(self.oracles) and not observed_mismatches:
            raise unittest.SkipTest("large-capacity precision oracle was unavailable on a network")
        self.assertEqual([], observed_mismatches, "\n".join(observed_mismatches))

    # TEST-MAP: CKB-TX-VIEWS-RPC-05
    @unittest.expectedFailure
    def test_large_udt_changes_preserve_all_128_bit_integer_digits(self) -> None:
        observed_mismatches: list[str] = []
        compared_networks = 0
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                fixture = DETAILS_FIXTURES[oracle.network.name].large_udt
                transaction, references, status = self._load_sample(
                    oracle, fixture.transaction_hash
                )
                expected = self._udt_expected(oracle, transaction, references, fixture)
                self.assertTrue(
                    any(
                        abs(amount) > 2**53 and int(float(amount)) != amount
                        for _capacity, amount in expected.values()
                    ),
                    f"{oracle.network.name} fixture has no inexact >2^53 UDT amount",
                )
                rows = self._details(oracle, fixture.transaction_hash)
                actual = self._udt_actual(rows, fixture)
                if expected != actual:
                    observed_mismatches.append(
                        f"{oracle.network.name}: expected={expected!r}; actual={actual!r}"
                    )
                compared_networks += 1
                self._assert_sample_stable(oracle, fixture.transaction_hash, status)
        if compared_networks < len(self.oracles) and not observed_mismatches:
            raise unittest.SkipTest("large-UDT precision oracle was unavailable on a network")
        self.assertEqual([], observed_mismatches, "\n".join(observed_mismatches))

    # TEST-MAP: CKB-TX-VIEWS-RPC-06
    def test_dao_deposit_and_withdrawing_capacities_match_rpc(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                transaction_hash = DETAILS_FIXTURES[oracle.network.name].dao_transaction_hash
                transaction, references, status = self._load_sample(oracle, transaction_hash)
                expected: defaultdict[tuple[str, str], int] = defaultdict(int)

                def add_dao(
                    output: Mapping[str, Any], data: object, direction: int, field: str
                ) -> None:
                    type_script = output.get("type")
                    if not isinstance(type_script, dict):
                        return
                    if type_script.get("code_hash") != DAO_CODE_HASH:
                        return
                    self.assertEqual("type", type_script.get("hash_type"), field)
                    self.assertEqual("0x", type_script.get("args"), field)
                    self.assertIsInstance(data, str, f"{field}.data")
                    cell_type = (
                        "nervos_dao_deposit"
                        if data == "0x0000000000000000"
                        else "nervos_dao_withdrawing"
                    )
                    address = output_address(output, oracle.network.address_hrp)
                    expected[(address, cell_type)] += direction * decode_hex_int(
                        output.get("capacity"), f"{field}.capacity"
                    )

                for index, (output, data) in enumerate(references):
                    add_dao(output, data, -1, f"inputs[{index}]")
                outputs = transaction.get("outputs")
                outputs_data = transaction.get("outputs_data")
                self.assertIsInstance(outputs, list)
                self.assertIsInstance(outputs_data, list)
                self.assertEqual(len(outputs), len(outputs_data))
                for index, (output, data) in enumerate(zip(outputs, outputs_data, strict=True)):
                    self.assertIsInstance(output, dict)
                    add_dao(output, data, 1, f"outputs[{index}]")
                self.assertTrue(expected)

                actual: dict[tuple[str, str], int] = {}
                for row in self._details(oracle, transaction_hash):
                    address = str(row["address"])
                    for transfer in row["transfers"]:
                        cell_type = transfer.get("cell_type")
                        if cell_type not in {
                            "nervos_dao_deposit",
                            "nervos_dao_withdrawing",
                        }:
                            continue
                        key = (address, str(cell_type))
                        self.assertNotIn(key, actual, f"duplicate DAO aggregate {key}")
                        actual[key] = self._integer(transfer.get("capacity"), f"{key}.capacity")
                self.assertEqual(dict(expected), actual)
                self._assert_sample_stable(oracle, transaction_hash, status)

    # TEST-MAP: CKB-TX-VIEWS-RPC-07
    def test_spore_nft_capacity_count_and_type_identity_match_rpc(self) -> None:
        for oracle in self.oracles:
            with self.subTest(network=oracle.network.name):
                fixture = DETAILS_FIXTURES[oracle.network.name]
                transaction, references, status = self._load_sample(
                    oracle, fixture.nft_transaction_hash
                )
                expected: defaultdict[tuple[str, str], list[int]] = defaultdict(
                    lambda: [0, 0]
                )

                def add_spore(
                    output: Mapping[str, Any], direction: int, field: str
                ) -> None:
                    type_script = output.get("type")
                    if not isinstance(type_script, dict):
                        return
                    if type_script.get("code_hash") != fixture.nft_code_hash:
                        return
                    self.assertEqual("data1", type_script.get("hash_type"), field)
                    args = type_script.get("args")
                    self.assertIsInstance(args, str, f"{field}.type.args")
                    try:
                        token_id = str(int(args.removeprefix("0x"), 16))
                    except ValueError as error:
                        self.fail(f"{field}.type.args contains invalid hexadecimal bytes: {error}")
                    address = output_address(output, oracle.network.address_hrp)
                    key = (address, token_id)
                    expected[key][0] += direction * decode_hex_int(
                        output.get("capacity"), f"{field}.capacity"
                    )
                    expected[key][1] += direction

                for index, (output, _data) in enumerate(references):
                    add_spore(output, -1, f"inputs[{index}]")
                outputs = transaction.get("outputs")
                self.assertIsInstance(outputs, list)
                for index, output in enumerate(outputs):
                    self.assertIsInstance(output, dict)
                    add_spore(output, 1, f"outputs[{index}]")
                self.assertTrue(expected)

                actual: dict[tuple[str, str], tuple[int, int]] = {}
                for row in self._details(oracle, fixture.nft_transaction_hash):
                    address = str(row["address"])
                    for transfer in row["transfers"]:
                        if transfer.get("cell_type") != "spore_cell":
                            continue
                        token_id = transfer.get("token_id")
                        self.assertIsInstance(token_id, str, f"{address}.spore_cell.token_id")
                        key = (address, token_id)
                        self.assertNotIn(key, actual, f"duplicate Spore Type Script aggregate {key}")
                        actual[key] = (
                            self._integer(transfer.get("capacity"), f"{key}.capacity"),
                            self._integer(transfer.get("count"), f"{key}.count"),
                        )
                self.assertEqual(
                    {key: tuple(value) for key, value in expected.items()},
                    actual,
                )
                self._assert_sample_stable(oracle, fixture.nft_transaction_hash, status)


if __name__ == "__main__":
    unittest.main()
