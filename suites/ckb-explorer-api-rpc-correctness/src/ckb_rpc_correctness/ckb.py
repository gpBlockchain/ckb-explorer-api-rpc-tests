from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32_GENERATORS = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
BECH32M_CONSTANT = 0x2BC830A3


@dataclass(frozen=True)
class LockScript:
    code_hash: str
    hash_type: str
    args: str


def decode_hex_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer, got boolean")
    if isinstance(value, int):
        return value
    if not isinstance(value, str) or not value.startswith("0x") or len(value) <= 2:
        raise ValueError(f"{field} must be a 0x-prefixed hexadecimal integer, got {value!r}")
    try:
        return int(value, 16)
    except ValueError as error:
        raise ValueError(f"{field} contains invalid hexadecimal digits: {value!r}") from error


def _little_u32(data: bytes, offset: int, field: str) -> int:
    end = offset + 4
    if end > len(data):
        raise ValueError(f"{field} offset exceeds payload")
    return int.from_bytes(data[offset:end], "little")


def parse_cellbase_lock(witness: str) -> LockScript:
    if not isinstance(witness, str) or not witness.startswith("0x"):
        raise ValueError("cellbase witness must be a 0x-prefixed hex string")
    try:
        payload = bytes.fromhex(witness[2:])
    except ValueError as error:
        raise ValueError("cellbase witness contains invalid hex") from error
    if len(payload) < 12:
        raise ValueError("cellbase witness table is truncated")

    script_offset = _little_u32(payload, 4, "cellbase script")
    message_offset = _little_u32(payload, 8, "cellbase message")
    if not 12 <= script_offset < message_offset <= len(payload):
        raise ValueError("cellbase witness table offsets are invalid")
    script = payload[script_offset:message_offset]
    if len(script) < 16:
        raise ValueError("cellbase lock script is truncated")

    code_hash_offset = _little_u32(script, 4, "code_hash")
    hash_type_offset = _little_u32(script, 8, "hash_type")
    args_offset = _little_u32(script, 12, "args")
    if not 16 <= code_hash_offset < hash_type_offset < args_offset <= len(script):
        raise ValueError("cellbase lock script offsets are invalid")
    code_hash = script[code_hash_offset:hash_type_offset]
    hash_type_payload = script[hash_type_offset:args_offset]
    args_vector = script[args_offset:]
    if len(code_hash) != 32 or len(hash_type_payload) != 1 or len(args_vector) < 4:
        raise ValueError("cellbase lock script fields have invalid lengths")
    args_length = int.from_bytes(args_vector[:4], "little")
    args = args_vector[4:]
    if args_length != len(args):
        raise ValueError("cellbase lock script args length is invalid")
    hash_type = {0: "data", 1: "type", 2: "data1"}.get(hash_type_payload[0])
    if hash_type is None:
        raise ValueError(f"unsupported CKB hash type byte: {hash_type_payload[0]}")
    return LockScript(f"0x{code_hash.hex()}", hash_type, f"0x{args.hex()}")


def _convert_bits(payload: bytes) -> list[int]:
    accumulator = 0
    bit_count = 0
    result: list[int] = []
    for value in payload:
        accumulator = (accumulator << 8) | value
        bit_count += 8
        while bit_count >= 5:
            bit_count -= 5
            result.append((accumulator >> bit_count) & 31)
    if bit_count:
        result.append((accumulator << (5 - bit_count)) & 31)
    return result


def _bech32_polymod(values: list[int]) -> int:
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(BECH32_GENERATORS):
            if (top >> index) & 1:
                checksum ^= generator
    return checksum


def ckb2021_address(lock: LockScript, hrp: str) -> str:
    if hrp not in {"ckb", "ckt"}:
        raise ValueError(f"unsupported CKB address HRP: {hrp!r}")
    hash_type_byte = {"data": 0, "type": 1, "data1": 2}[lock.hash_type]
    try:
        code_hash = bytes.fromhex(lock.code_hash.removeprefix("0x"))
        args = bytes.fromhex(lock.args.removeprefix("0x"))
    except ValueError as error:
        raise ValueError("lock script contains invalid hex") from error
    if len(code_hash) != 32:
        raise ValueError("lock script code_hash must contain 32 bytes")
    data = _convert_bits(bytes([0]) + code_hash + bytes([hash_type_byte]) + args)
    expanded_hrp = [ord(char) >> 5 for char in hrp] + [0] + [ord(char) & 31 for char in hrp]
    polymod = _bech32_polymod(expanded_hrp + data + [0] * 6) ^ BECH32M_CONSTANT
    checksum = [(polymod >> (5 * (5 - index))) & 31 for index in range(6)]
    return hrp + "1" + "".join(BECH32_CHARSET[value] for value in data + checksum)


def derive_miner_address(block: Mapping[str, Any], hrp: str) -> str:
    transactions = block.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        raise ValueError("RPC block has no Cellbase transaction")
    cellbase = transactions[0]
    witnesses = cellbase.get("witnesses") if isinstance(cellbase, dict) else None
    if not isinstance(witnesses, list) or not witnesses or not witnesses[0]:
        raise ValueError("RPC Cellbase transaction has no witness")
    return ckb2021_address(parse_cellbase_lock(witnesses[0]), hrp)


def calculate_live_cell_changes(block: Mapping[str, Any]) -> int:
    transactions = block.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        raise ValueError("RPC block has no transactions")
    total = 1
    for index, transaction in enumerate(transactions[1:], start=1):
        if not isinstance(transaction, dict):
            raise ValueError(f"RPC transaction {index} is not an object")
        inputs = transaction.get("inputs")
        outputs = transaction.get("outputs")
        if not isinstance(inputs, list) or not isinstance(outputs, list):
            raise ValueError(f"RPC transaction {index} inputs/outputs are invalid")
        total += len(outputs) - len(inputs)
    return total


def mature_block_reward(economic_state: Mapping[str, Any]) -> int:
    reward = economic_state.get("miner_reward")
    if not isinstance(reward, dict):
        raise ValueError("RPC economic state has no miner_reward")
    return decode_hex_int(reward.get("primary"), "miner_reward.primary") + decode_hex_int(
        reward.get("secondary"), "miner_reward.secondary"
    )
