from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32_GENERATORS = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
BECH32M_CONSTANT = 0x2BC830A3
HALVING_EPOCH = 4 * 365 * 24 // 4
DEFAULT_EPOCH_REWARD = 191_780_821_917_808


@dataclass(frozen=True)
class LockScript:
    code_hash: str
    hash_type: str
    args: str


@dataclass(frozen=True)
class EpochInfo:
    number: int
    index: int
    length: int
    start_number: int


@dataclass(frozen=True)
class MinerReward:
    primary: int
    secondary: int
    proposal: int
    committed: int

    @property
    def reward(self) -> int:
        return self.primary + self.secondary

    @property
    def received_tx_fee(self) -> int:
        return self.proposal + self.committed

    @property
    def total(self) -> int:
        return self.reward + self.received_tx_fee


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
    payload, script_offset, message_offset = _parse_cellbase_table(witness)
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


def _parse_cellbase_table(witness: str) -> tuple[bytes, int, int]:
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
    return payload, script_offset, message_offset


def parse_cellbase_message(witness: str) -> str:
    payload, _script_offset, message_offset = _parse_cellbase_table(witness)
    vector = payload[message_offset:]
    if len(vector) < 4:
        raise ValueError("cellbase message is truncated")
    length = int.from_bytes(vector[:4], "little")
    message = vector[4:]
    if length != len(message):
        raise ValueError("cellbase message length is invalid")
    return f"0x{message.hex()}"


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
    witness = cellbase_witness(block)
    return ckb2021_address(parse_cellbase_lock(witness), hrp)


def cellbase_witness(block: Mapping[str, Any]) -> str:
    transactions = block.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        raise ValueError("RPC block has no Cellbase transaction")
    cellbase = transactions[0]
    witnesses = cellbase.get("witnesses") if isinstance(cellbase, dict) else None
    if not isinstance(witnesses, list) or not witnesses or not witnesses[0]:
        raise ValueError("RPC Cellbase transaction has no witness")
    if not isinstance(witnesses[0], str):
        raise ValueError("RPC Cellbase witness is not a string")
    return witnesses[0]


def derive_miner_message(block: Mapping[str, Any]) -> str:
    return parse_cellbase_message(cellbase_witness(block))


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
    return miner_reward(economic_state).reward


def miner_reward(economic_state: Mapping[str, Any]) -> MinerReward:
    reward = economic_state.get("miner_reward")
    if not isinstance(reward, dict):
        raise ValueError("RPC economic state has no miner_reward")
    return MinerReward(
        primary=decode_hex_int(reward.get("primary"), "miner_reward.primary"),
        secondary=decode_hex_int(reward.get("secondary"), "miner_reward.secondary"),
        proposal=decode_hex_int(reward.get("proposal"), "miner_reward.proposal"),
        committed=decode_hex_int(reward.get("committed"), "miner_reward.committed"),
    )


def decode_epoch(header: Mapping[str, Any]) -> EpochInfo:
    packed = decode_hex_int(header.get("epoch"), "header.epoch")
    height = decode_hex_int(header.get("number"), "header.number")
    number = packed & 0xFFFFFF
    index = (packed >> 24) & 0xFFFF
    length = (packed >> 40) & 0xFFFF
    if length <= 0 or index >= length:
        raise ValueError(f"header.epoch has invalid index/length: {index}/{length}")
    return EpochInfo(number, index, length, height - index)


def compact_to_difficulty(value: object) -> int:
    compact = decode_hex_int(value, "header.compact_target")
    exponent = compact >> 24
    mantissa = compact & 0x00FFFFFF
    target = mantissa >> (8 * (3 - exponent)) if exponent <= 3 else mantissa << (8 * (exponent - 3))
    overflow = mantissa != 0 and exponent > 32
    if target == 0 or overflow:
        return 0
    return (2**256 - 1) if target == 1 else (2**256 // target)


def pending_base_reward(height: int, epoch: EpochInfo) -> int:
    if height < 12:
        return 0
    epoch_reward = DEFAULT_EPOCH_REWARD >> (epoch.number // HALVING_EPOCH)
    base, remainder = divmod(epoch_reward, epoch.length)
    return base + (1 if epoch.start_number <= height < epoch.start_number + remainder else 0)


def _hex_bytes(value: object, field: str) -> bytes:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise ValueError(f"{field} must be a 0x-prefixed hex string")
    try:
        return bytes.fromhex(value[2:])
    except ValueError as error:
        raise ValueError(f"{field} contains invalid hexadecimal bytes") from error


def _script_occupied_bytes(script: object, field: str) -> int:
    if not isinstance(script, dict):
        raise ValueError(f"{field} must be an object")
    code_hash = _hex_bytes(script.get("code_hash"), f"{field}.code_hash")
    args = _hex_bytes(script.get("args"), f"{field}.args")
    if len(code_hash) != 32:
        raise ValueError(f"{field}.code_hash must contain 32 bytes")
    return 32 + 1 + len(args)


def total_output_capacity(block: Mapping[str, Any]) -> int:
    total = 0
    for tx_index, transaction in enumerate(_transactions(block)):
        outputs = transaction.get("outputs")
        if not isinstance(outputs, list):
            raise ValueError(f"transaction {tx_index} outputs are invalid")
        for output_index, output in enumerate(outputs):
            if not isinstance(output, dict):
                raise ValueError(f"transaction {tx_index} output {output_index} is invalid")
            total += decode_hex_int(output.get("capacity"), f"transactions[{tx_index}].outputs[{output_index}].capacity")
    return total


def total_cell_consumed(block: Mapping[str, Any]) -> int:
    total_bytes = 0
    for tx_index, transaction in enumerate(_transactions(block)):
        outputs = transaction.get("outputs")
        outputs_data = transaction.get("outputs_data")
        if not isinstance(outputs, list) or not isinstance(outputs_data, list) or len(outputs) != len(outputs_data):
            raise ValueError(f"transaction {tx_index} outputs and outputs_data do not align")
        for output_index, (output, data) in enumerate(zip(outputs, outputs_data, strict=True)):
            if not isinstance(output, dict):
                raise ValueError(f"transaction {tx_index} output {output_index} is invalid")
            occupied = 8 + len(_hex_bytes(data, f"transactions[{tx_index}].outputs_data[{output_index}]"))
            occupied += _script_occupied_bytes(output.get("lock"), f"transactions[{tx_index}].outputs[{output_index}].lock")
            if output.get("type") is not None:
                occupied += _script_occupied_bytes(output["type"], f"transactions[{tx_index}].outputs[{output_index}].type")
            total_bytes += occupied
    return total_bytes * 100_000_000


def _transactions(block: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    transactions = block.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        raise ValueError("RPC block has no transactions")
    if not all(isinstance(item, dict) for item in transactions):
        raise ValueError("RPC block transactions must be objects")
    return transactions


def block_cycles(result: Mapping[str, Any]) -> int:
    cycles = result.get("cycles")
    if not isinstance(cycles, list):
        raise ValueError("RPC block result has no cycles array")
    return sum(decode_hex_int(value, f"cycles[{index}]") for index, value in enumerate(cycles))


def _bytes_capacity(value: object, field: str) -> int:
    return 4 + len(_hex_bytes("0x" if value is None else value, field))


def _fixvec_capacity(items: object, item_capacity: int, field: str) -> int:
    if not isinstance(items, list):
        raise ValueError(f"{field} must be an array")
    return 4 + len(items) * item_capacity


def _dynvec_capacity(capacities: list[int]) -> int:
    return 4 + 4 * len(capacities) + sum(capacities)


def _script_capacity(script: object, field: str) -> int:
    if not isinstance(script, dict):
        raise ValueError(f"{field} must be an object")
    code_hash = _hex_bytes(script.get("code_hash"), f"{field}.code_hash")
    if len(code_hash) != 32:
        raise ValueError(f"{field}.code_hash must contain 32 bytes")
    return 4 + 3 * 4 + 32 + 1 + _bytes_capacity(script.get("args"), f"{field}.args")


def _output_capacity(output: object, field: str) -> int:
    if not isinstance(output, dict):
        raise ValueError(f"{field} must be an object")
    lock_size = _script_capacity(output.get("lock"), f"{field}.lock")
    type_size = 0 if output.get("type") is None else _script_capacity(output["type"], f"{field}.type")
    return 4 + 3 * 4 + 8 + lock_size + type_size


def _transaction_capacity(transaction: Mapping[str, Any], index: int) -> int:
    cell_deps = transaction.get("cell_deps")
    header_deps = transaction.get("header_deps")
    inputs = transaction.get("inputs")
    outputs = transaction.get("outputs")
    outputs_data = transaction.get("outputs_data")
    witnesses = transaction.get("witnesses")
    if not all(isinstance(value, list) for value in (cell_deps, header_deps, inputs, outputs, outputs_data, witnesses)):
        raise ValueError(f"transaction {index} contains invalid vector fields")
    assert isinstance(cell_deps, list) and isinstance(header_deps, list) and isinstance(inputs, list)
    assert isinstance(outputs, list) and isinstance(outputs_data, list) and isinstance(witnesses, list)
    raw = 4 + 6 * 4
    raw += 4
    raw += _fixvec_capacity(cell_deps, 37, f"transactions[{index}].cell_deps")
    raw += _fixvec_capacity(header_deps, 32, f"transactions[{index}].header_deps")
    raw += _fixvec_capacity(inputs, 44, f"transactions[{index}].inputs")
    raw += _dynvec_capacity([_output_capacity(item, f"transactions[{index}].outputs[{i}]") for i, item in enumerate(outputs)])
    raw += _dynvec_capacity(
        [_bytes_capacity(item, f"transactions[{index}].outputs_data[{i}]") for i, item in enumerate(outputs_data)]
    )
    witness_vector = _dynvec_capacity(
        [_bytes_capacity(item, f"transactions[{index}].witnesses[{i}]") for i, item in enumerate(witnesses)]
    )
    return 4 + 2 * 4 + raw + witness_vector


def serialized_block_size_without_uncle_proposals(block: Mapping[str, Any]) -> int:
    transactions = _transactions(block)
    uncles = block.get("uncles")
    proposals = block.get("proposals")
    if not isinstance(uncles, list) or not isinstance(proposals, list):
        raise ValueError("RPC block uncles/proposals must be arrays")
    uncle_capacities: list[int] = []
    uncle_proposals = 0
    for index, uncle in enumerate(uncles):
        if not isinstance(uncle, dict) or not isinstance(uncle.get("proposals"), list):
            raise ValueError(f"RPC uncle {index} is invalid")
        count = len(uncle["proposals"])
        uncle_proposals += count
        uncle_capacities.append(4 + 2 * 4 + 208 + 4 + count * 10)
    capacity = 4 + 5 * 4
    capacity += 208
    capacity += _dynvec_capacity(uncle_capacities)
    capacity += _dynvec_capacity([_transaction_capacity(tx, index) for index, tx in enumerate(transactions)])
    capacity += _fixvec_capacity(proposals, 10, "block.proposals")
    capacity += _bytes_capacity(block.get("extension"), "block.extension")
    return capacity - uncle_proposals * (10 - 4)
