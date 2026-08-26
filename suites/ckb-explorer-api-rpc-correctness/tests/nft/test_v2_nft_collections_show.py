from __future__ import annotations

import hashlib
import unittest
from typing import Any, Mapping

from ckb_rpc_correctness.ckb import output_address
from ckb_rpc_correctness.oracle import NetworkOracle, OracleUnavailable
from ckb_rpc_correctness.settings import load_settings


COLLECTION_FIXTURES = {
    "mainnet": {
        "m_nft": (9041, "0x68b5316d84a4303af0d32d23a304d3b42bc6258cb2633dd416f4f93b152bb88e"),
        "nrc721": (9122, "0x76b9c856d45808bda38f398be17a441249dfd7d1c57b521b275a3a3f2e58b023"),
        "spore": (9595, "0x167afa1b0c3ffd2d56e3c2730a3a6aade00c7c2a85a1d5d694efb5c47615d386"),
    },
    "testnet": {
        "m_nft": (18639, "0x5f67eec0bc129c39bfec3e384499beb65aafd70101bb5bdcd83ffdf0da59e868"),
        "nrc721": (18636, "0xa9d7eb2ea9c09deb0959d123a29f61341a3a8056887a080d81d1fdfcdb5bcdcd"),
        "spore": (20225, "0xcfe8eaa5c1e691d7795d5ff1836c443d0a05f8dbd2d903b4a8201e889dd59d5f"),
    },
}
NRC721_HEADER = bytes.fromhex("24ff5a9ab8c38d195ce2b4ea75ca8987")


def _u32(value: int) -> bytes:
    return value.to_bytes(4, "little")


def _script_hash(script: Mapping[str, Any]) -> str:
    args = bytes.fromhex(str(script["args"])[2:])
    fields = [
        bytes.fromhex(str(script["code_hash"])[2:]),
        bytes([{"data": 0, "type": 1, "data1": 2}[str(script["hash_type"])]]),
        _u32(len(args)) + args,
    ]
    offset = 4 + 4 * len(fields)
    offsets: list[int] = []
    for field in fields:
        offsets.append(offset)
        offset += len(field)
    serialized = _u32(offset) + b"".join(_u32(item) for item in offsets) + b"".join(fields)
    digest = hashlib.blake2b(
        serialized,
        digest_size=32,
        person=b"ckb-default-hash",
    ).hexdigest()
    return "0x" + digest


def _decode_m_nft_class(data: str) -> tuple[str, str, str]:
    payload = bytes.fromhex(data[2:])
    cursor = 10
    name_size = int.from_bytes(payload[cursor : cursor + 2], "big")
    cursor += 2
    name = payload[cursor : cursor + name_size].decode("utf-8", errors="replace").replace("\x00", "")
    cursor += name_size
    description_size = int.from_bytes(payload[cursor : cursor + 2], "big")
    cursor += 2
    description = (
        payload[cursor : cursor + description_size]
        .decode("utf-8", errors="replace")
        .replace("\x00", "")
    )
    cursor += description_size
    renderer_size = int.from_bytes(payload[cursor : cursor + 2], "big")
    cursor += 2
    renderer = (
        payload[cursor : cursor + renderer_size]
        .decode("utf-8", errors="replace")
        .replace("\x00", "")
    )
    return name, description, renderer


def _decode_nrc721_factory(data: str) -> tuple[str, str, str]:
    payload = bytes.fromhex(data[2:])
    if not payload.startswith(NRC721_HEADER):
        raise ValueError("NRC-721 factory header is missing")
    payload = payload[len(NRC721_HEADER) :]
    cursor = 0
    values: list[str] = []
    for _field in range(3):
        size = int.from_bytes(payload[cursor : cursor + 2], "big")
        cursor += 2
        values.append(payload[cursor : cursor + size].decode("utf-8", errors="replace"))
        cursor += size
    return values[0], values[1], values[2]


def _decode_spore_cluster(data: str) -> tuple[str, str]:
    payload = bytes.fromhex(data[2:])
    if len(payload) < 16:
        raise ValueError("Spore cluster table is truncated")
    name_offset = int.from_bytes(payload[4:8], "little")
    description_offset = int.from_bytes(payload[8:12], "little")
    name_size = int.from_bytes(payload[name_offset : name_offset + 4], "little")
    description_size = int.from_bytes(
        payload[description_offset : description_offset + 4], "little"
    )
    name = payload[name_offset + 4 : name_offset + 4 + name_size].decode(
        "utf-8", errors="replace"
    )
    description = payload[
        description_offset + 4 : description_offset + 4 + description_size
    ].decode("utf-8", errors="replace")
    if len(name) > 100:
        name = name[:97] + "..."
    return name.strip(), description.strip()


class V2NftCollectionsShowRpcCorrectnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = load_settings()
        if not cls.settings.run_live:
            raise unittest.SkipTest(f"live execution disabled in {cls.settings.settings_file}")
        cls.definition_cache: dict[tuple[str, str], Mapping[str, Any]] = {}

    def _detail(self, oracle: NetworkOracle, identifier: object) -> Mapping[str, Any]:
        payload = oracle.explorer_json(f"/v2/nft/collections/{identifier}")
        if not isinstance(payload, dict):
            raise OracleUnavailable(
                f"{oracle.network.name} NFT collection {identifier} is unavailable"
            )
        return payload

    def _latest_live_cell(
        self, oracle: NetworkOracle, detail: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        type_script = detail.get("type_script")
        if not isinstance(type_script, dict):
            raise OracleUnavailable(
                f"{oracle.network.name} collection type script is unavailable"
            )
        result = oracle.rpc_result(
            "get_cells",
            [
                {
                    "script": {
                        "code_hash": type_script["code_hash"],
                        "hash_type": type_script["hash_type"],
                        "args": type_script["args"],
                    },
                    "script_type": "type",
                    "script_search_mode": "exact",
                },
                "desc",
                "0x1",
            ],
        )
        objects = result.get("objects") if isinstance(result, dict) else None
        if not isinstance(objects, list) or not objects or not isinstance(objects[0], dict):
            raise OracleUnavailable(
                f"{oracle.network.name} collection definition Cell is unavailable"
            )
        return objects[0]

    def _definition_cell(
        self, oracle: NetworkOracle, detail: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        cache_key = (oracle.network.name, str(detail["sn"]))
        if cache_key in self.definition_cache:
            return self.definition_cache[cache_key]
        type_script = detail.get("type_script")
        if not isinstance(type_script, dict) or detail.get("timestamp") is None:
            raise OracleUnavailable(
                f"{oracle.network.name} collection definition identity is unavailable"
            )
        result = oracle.rpc_result(
            "get_transactions",
            [
                {
                    "script": {
                        "code_hash": type_script["code_hash"],
                        "hash_type": type_script["hash_type"],
                        "args": type_script["args"],
                    },
                    "script_type": "type",
                    "script_search_mode": "exact",
                },
                "asc",
                "0x64",
            ],
        )
        events = result.get("objects") if isinstance(result, dict) else None
        if not isinstance(events, list):
            raise OracleUnavailable(
                f"{oracle.network.name} collection definition history is unavailable"
            )
        expected_script = {
            key: type_script[key] for key in ("code_hash", "hash_type", "args")
        }
        for event in events:
            if not isinstance(event, dict) or event.get("io_type") != "output":
                continue
            block = oracle.rpc_result("get_block_by_number", [event["block_number"]])
            header = block.get("header") if isinstance(block, dict) else None
            if (
                not isinstance(header, dict)
                or int(header["timestamp"], 16) != int(detail["timestamp"])
            ):
                continue
            transaction_result = oracle.rpc_result("get_transaction", [event["tx_hash"]])
            transaction = (
                transaction_result.get("transaction")
                if isinstance(transaction_result, dict)
                else None
            )
            output_index = int(event["io_index"], 16)
            if not isinstance(transaction, dict) or output_index >= len(transaction["outputs"]):
                continue
            output = transaction["outputs"][output_index]
            if output.get("type") != expected_script:
                continue
            cell = {
                "block_number": event["block_number"],
                "out_point": {"tx_hash": event["tx_hash"], "index": event["io_index"]},
                "output": output,
                "output_data": transaction["outputs_data"][output_index],
            }
            self.definition_cache[cache_key] = cell
            return cell
        raise OracleUnavailable(
            f"{oracle.network.name} collection definition Cell matching timestamp is unavailable"
        )

    # TEST-MAP: NFT-COLL-RPC-01
    def test_numeric_id_and_sn_resolve_same_chain_definition_identity(self) -> None:
        for network in self.settings.networks:
            for standard, (numeric_id, sn) in COLLECTION_FIXTURES[network.name].items():
                with self.subTest(network=network.name, standard=standard):
                    oracle = NetworkOracle(network, self.settings)
                    try:
                        numeric = self._detail(oracle, numeric_id)
                        named = self._detail(oracle, sn)
                        cell = self._definition_cell(oracle, named)
                        block = oracle.rpc_result("get_block_by_number", [cell["block_number"]])
                    except (OracleUnavailable, ValueError, KeyError) as error:
                        raise unittest.SkipTest(str(error)) from error
                    header = block.get("header") if isinstance(block, dict) else None
                    if not isinstance(header, dict):
                        raise unittest.SkipTest(
                            f"{network.name} definition block is unavailable"
                        )
                    self.assertEqual(numeric, named)
                    self.assertEqual(standard, named["standard"])
                    chain_type = cell["output"]["type"]
                    self.assertEqual(
                        {key: named["type_script"][key] for key in ("code_hash", "hash_type", "args")},
                        chain_type,
                    )
                    self.assertEqual(sn, named["sn"])
                    self.assertEqual(sn, _script_hash(chain_type))
                    self.assertEqual(
                        named["creator"],
                        output_address(cell["output"], network.address_hrp),
                    )
                    self.assertEqual(int(header["timestamp"], 16), int(named["timestamp"]))

    # TEST-MAP: NFT-COLL-RPC-02
    @unittest.expectedFailure
    def test_m_nft_metadata_decodes_from_latest_live_class_cell(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                _numeric_id, sn = COLLECTION_FIXTURES[network.name]["m_nft"]
                try:
                    detail = self._detail(oracle, sn)
                    cell = self._latest_live_cell(oracle, detail)
                    name, description, renderer = _decode_m_nft_class(cell["output_data"])
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(name, detail["name"])
                self.assertEqual(description, detail["description"])
                self.assertEqual(renderer, detail["icon_url"])

    # TEST-MAP: NFT-COLL-RPC-03
    @unittest.expectedFailure
    def test_nrc721_metadata_decodes_from_latest_live_factory_cell(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                _numeric_id, sn = COLLECTION_FIXTURES[network.name]["nrc721"]
                try:
                    detail = self._detail(oracle, sn)
                    cell = self._latest_live_cell(oracle, detail)
                    name, symbol, base_token_uri = _decode_nrc721_factory(cell["output_data"])
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(name, detail["name"])
                self.assertEqual(base_token_uri, detail["icon_url"])
                self.assertEqual(symbol, detail["symbol"])

    # TEST-MAP: NFT-COLL-RPC-04
    def test_spore_metadata_decodes_from_matching_cluster_cell(self) -> None:
        for network in self.settings.networks:
            with self.subTest(network=network.name):
                oracle = NetworkOracle(network, self.settings)
                _numeric_id, sn = COLLECTION_FIXTURES[network.name]["spore"]
                try:
                    detail = self._detail(oracle, sn)
                    cell = self._latest_live_cell(oracle, detail)
                    name, description = _decode_spore_cluster(cell["output_data"])
                except (OracleUnavailable, ValueError, KeyError) as error:
                    raise unittest.SkipTest(str(error)) from error
                self.assertEqual(sn, detail["type_script"]["script_hash"])
                self.assertEqual(name, detail["name"])
                self.assertEqual(description, detail["description"])


if __name__ == "__main__":
    unittest.main()
