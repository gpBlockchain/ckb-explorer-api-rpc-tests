from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlencode

from .ckb import (
    block_cycles,
    calculate_live_cell_changes,
    decode_hex_int,
    serialized_block_size_without_uncle_proposals,
)
from .http import HttpClientError, JsonHttpClient
from .settings import NetworkSettings, Settings


V1_HEADERS = {
    "Accept": "application/vnd.api+json",
    "Content-Type": "application/vnd.api+json",
}


class OracleUnavailable(RuntimeError):
    pass


class ReorgObserved(OracleUnavailable):
    pass


@dataclass(frozen=True)
class BlockSample:
    network: str
    height: int
    attributes: Mapping[str, Any]
    rpc_block: Mapping[str, Any]


@dataclass(frozen=True)
class EpochExtrema:
    network: str
    epoch: int
    start_height: int
    length: int
    attributes: Mapping[str, Any]
    largest_block: int
    max_cycles: int | None


class NetworkOracle:
    def __init__(self, network: NetworkSettings, settings: Settings, client: JsonHttpClient | None = None) -> None:
        self.network = network
        self.settings = settings
        self.client = client or JsonHttpClient(
            timeout=settings.timeout_seconds,
            retries=settings.transport_retries,
        )
        self._row_pages: dict[int, list[Mapping[str, Any]]] = {}
        self._rpc_tip: Mapping[str, Any] | None = None
        self._blocks: dict[int, Mapping[str, Any]] = {}
        self._blocks_with_cycles: dict[int, Mapping[str, Any]] = {}
        self._details: dict[str, Mapping[str, Any]] = {}
        self._samples: dict[str, BlockSample] = {}
        self._economic_states: dict[str, Mapping[str, Any]] = {}
        self._completed_epoch: EpochExtrema | None = None

    def explorer_json(self, path: str, query: Mapping[str, object] | None = None) -> Any:
        url = self.network.explorer_api_url + path
        if query:
            url += "?" + urlencode(query)
        try:
            return self.client.request_json(url, headers=V1_HEADERS)
        except HttpClientError as error:
            raise OracleUnavailable(f"{self.network.name} Explorer unavailable: {error}") from error

    def rpc_result(self, method: str, params: list[object]) -> Any:
        payload = {"id": 1, "jsonrpc": "2.0", "method": method, "params": params}
        try:
            response = self.client.request_json(
                self.network.ckb_rpc_url,
                method="POST",
                headers={"Content-Type": "application/json"},
                json_body=payload,
            )
        except HttpClientError as error:
            raise OracleUnavailable(f"{self.network.name} RPC unavailable: {error}") from error
        if not isinstance(response, dict):
            raise OracleUnavailable(f"{self.network.name} RPC {method} returned a non-object")
        if response.get("error") is not None:
            raise OracleUnavailable(f"{self.network.name} RPC {method} error: {response['error']!r}")
        return response.get("result")

    def rpc_batch_results(self, calls: list[tuple[str, list[object]]]) -> list[Any]:
        payload = [
            {"id": index, "jsonrpc": "2.0", "method": method, "params": params}
            for index, (method, params) in enumerate(calls)
        ]
        try:
            response = self.client.request_json(
                self.network.ckb_rpc_url,
                method="POST",
                headers={"Content-Type": "application/json"},
                json_body=payload,
            )
        except HttpClientError as error:
            raise OracleUnavailable(f"{self.network.name} RPC batch unavailable: {error}") from error
        if not isinstance(response, list):
            raise OracleUnavailable(f"{self.network.name} RPC batch returned a non-array")
        indexed: dict[int, Mapping[str, Any]] = {}
        for item in response:
            if not isinstance(item, dict) or not isinstance(item.get("id"), int):
                raise OracleUnavailable(f"{self.network.name} RPC batch contains an invalid response")
            indexed[item["id"]] = item
        results: list[Any] = []
        for index, (method, _params) in enumerate(calls):
            item = indexed.get(index)
            if item is None:
                raise OracleUnavailable(f"{self.network.name} RPC batch omitted response {index}")
            if item.get("error") is not None:
                raise OracleUnavailable(f"{self.network.name} RPC {method} batch error: {item['error']!r}")
            results.append(item.get("result"))
        return results

    def list_rows(self, page: int = 1) -> list[Mapping[str, Any]]:
        if page not in self._row_pages:
            payload = self.explorer_json(
                "/v1/blocks",
                {"page": page, "page_size": self.settings.list_page_size, "sort": "number.desc"},
            )
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                raise OracleUnavailable(f"{self.network.name} Explorer block list page {page} has invalid data")
            if page == 1 and not data:
                raise OracleUnavailable(f"{self.network.name} Explorer block list has no data")
            rows: list[Mapping[str, Any]] = []
            for index, row in enumerate(data):
                attributes = row.get("attributes") if isinstance(row, dict) else None
                if not isinstance(attributes, dict):
                    raise OracleUnavailable(f"{self.network.name} Explorer page {page} row {index} has no attributes")
                rows.append(attributes)
            self._row_pages[page] = rows
        return self._row_pages[page]

    def api_tip_height(self) -> int:
        try:
            return int(self.list_rows()[0]["number"])
        except (KeyError, TypeError, ValueError) as error:
            raise OracleUnavailable(f"{self.network.name} Explorer tip number is invalid") from error

    def rpc_tip(self) -> Mapping[str, Any]:
        if self._rpc_tip is None:
            result = self.rpc_result("get_tip_header", [])
            if not isinstance(result, dict):
                raise OracleUnavailable(f"{self.network.name} RPC get_tip_header returned no header")
            self._rpc_tip = result
        return self._rpc_tip

    def rpc_tip_height(self) -> int:
        try:
            return decode_hex_int(self.rpc_tip().get("number"), "tip.number")
        except ValueError as error:
            raise OracleUnavailable(f"{self.network.name} RPC tip number is invalid: {error}") from error

    def block(self, height: int, *, refresh: bool = False) -> Mapping[str, Any]:
        if not refresh and height in self._blocks:
            return self._blocks[height]
        result = self.rpc_result("get_block_by_number", [hex(height)])
        if not isinstance(result, dict):
            raise OracleUnavailable(f"{self.network.name} RPC has no block at height {height}")
        if not refresh:
            self._blocks[height] = result
        return result

    def block_by_hash(self, block_hash: str) -> Mapping[str, Any]:
        result = self.rpc_result("get_block", [block_hash])
        if not isinstance(result, dict):
            raise OracleUnavailable(f"{self.network.name} RPC has no block for hash {block_hash}")
        return result

    def block_with_cycles(self, height: int) -> Mapping[str, Any]:
        if height not in self._blocks_with_cycles:
            result = self.rpc_result("get_block_by_number", [hex(height), "0x2", True])
            if not isinstance(result, dict) or not isinstance(result.get("block"), dict):
                raise OracleUnavailable(f"{self.network.name} RPC has no block-with-cycles at height {height}")
            self._blocks_with_cycles[height] = result
        return self._blocks_with_cycles[height]

    def prefetch_blocks(self, heights: list[int]) -> None:
        missing = [height for height in heights if height not in self._blocks]
        for offset in range(0, len(missing), self.settings.rpc_batch_size):
            batch = missing[offset : offset + self.settings.rpc_batch_size]
            results = self.rpc_batch_results([("get_block_by_number", [hex(height)]) for height in batch])
            for height, result in zip(batch, results, strict=True):
                if not isinstance(result, dict):
                    raise OracleUnavailable(f"{self.network.name} RPC has no prefetched block at height {height}")
                self._blocks[height] = result

    def detail_attributes(self, identifier: int | str) -> Mapping[str, Any]:
        key = str(identifier)
        if key not in self._details:
            payload = self.explorer_json(f"/v1/blocks/{identifier}")
            data = payload.get("data") if isinstance(payload, dict) else None
            attributes = data.get("attributes") if isinstance(data, dict) else None
            if not isinstance(attributes, dict):
                raise OracleUnavailable(f"{self.network.name} Explorer detail has no attributes for {identifier}")
            self._details[key] = attributes
        return self._details[key]

    def _eligible_rows(self) -> list[Mapping[str, Any]]:
        minimum_depth = self.settings.proposal_window + 1
        tip = self.rpc_tip_height()
        eligible: list[Mapping[str, Any]] = []
        seen_heights: set[int] = set()
        for page in range(1, self.settings.sample_search_pages + 1):
            rows = self.list_rows(page)
            if not rows:
                break
            for attributes in rows:
                try:
                    height = int(attributes["number"])
                except (KeyError, TypeError, ValueError):
                    continue
                if height in seen_heights:
                    continue
                seen_heights.add(height)
                if tip - height >= minimum_depth:
                    eligible.append(attributes)
        if not eligible:
            raise OracleUnavailable(
                f"{self.network.name} first {self.settings.sample_search_pages} block-list pages have no sample "
                f"at least {minimum_depth} blocks behind RPC tip"
            )
        return eligible

    def _find_sample(
        self,
        key: str,
        predicate: Callable[[Mapping[str, Any], Mapping[str, Any]], bool],
        *,
        priority: Callable[[Mapping[str, Any]], tuple[object, ...]] | None = None,
    ) -> BlockSample:
        if key in self._samples:
            return self._samples[key]
        rows = self._eligible_rows()
        if priority is not None:
            rows = sorted(rows, key=priority)
        for attributes in rows:
            height = int(attributes["number"])
            block = self.block(height)
            if predicate(attributes, block):
                sample = BlockSample(self.network.name, height, attributes, block)
                self._samples[key] = sample
                return sample
        raise OracleUnavailable(f"{self.network.name} has no live fixture for sample {key}")

    def confirmed_sample(self) -> BlockSample:
        return self._find_sample("confirmed", lambda _attributes, _block: True)

    def transaction_sample(self) -> BlockSample:
        return self._find_sample(
            "transaction",
            lambda _attributes, block: isinstance(block.get("transactions"), list)
            and len(block["transactions"]) > 1,
            priority=lambda attributes: (int(attributes.get("transactions_count", "0")) <= 1,),
        )

    def live_change_sample(self) -> BlockSample:
        return self._find_sample(
            "live-change",
            lambda _attributes, block: calculate_live_cell_changes(block) != 1,
            priority=lambda attributes: (
                int(attributes.get("live_cell_changes", "1")) == 1,
                int(attributes.get("transactions_count", "0")) <= 1,
            ),
        )

    def miner_sample(self) -> BlockSample:
        def has_witness(_attributes: Mapping[str, Any], block: Mapping[str, Any]) -> bool:
            transactions = block.get("transactions")
            if not isinstance(transactions, list) or not transactions or not isinstance(transactions[0], dict):
                return False
            witnesses = transactions[0].get("witnesses")
            return isinstance(witnesses, list) and bool(witnesses) and bool(witnesses[0])

        return self._find_sample("miner", has_witness)

    def detail_sample(self, kind: str = "confirmed") -> BlockSample:
        source = {
            "confirmed": self.confirmed_sample,
            "transaction": self.transaction_sample,
            "miner": self.miner_sample,
        }[kind]()
        key = f"detail-{kind}"
        if key not in self._samples:
            self._samples[key] = BlockSample(
                source.network,
                source.height,
                self.detail_attributes(source.height),
                source.rpc_block,
            )
        return self._samples[key]

    def proposal_sample(self) -> BlockSample:
        source = self._find_sample(
            "proposal",
            lambda _attributes, block: isinstance(block.get("proposals"), list) and bool(block["proposals"]),
        )
        return BlockSample(source.network, source.height, self.detail_attributes(source.height), source.rpc_block)

    def output_sample(self, *, typed_or_data: bool = False) -> BlockSample:
        def matches(_attributes: Mapping[str, Any], block: Mapping[str, Any]) -> bool:
            transactions = block.get("transactions")
            if not isinstance(transactions, list):
                return False
            output_count = 0
            has_typed_or_data = False
            for transaction in transactions:
                if not isinstance(transaction, dict):
                    return False
                outputs = transaction.get("outputs")
                outputs_data = transaction.get("outputs_data")
                if not isinstance(outputs, list) or not isinstance(outputs_data, list):
                    return False
                output_count += len(outputs)
                has_typed_or_data = has_typed_or_data or any(
                    isinstance(output, dict) and output.get("type") is not None for output in outputs
                )
                has_typed_or_data = has_typed_or_data or any(data not in {None, "0x"} for data in outputs_data)
            return output_count > 1 and (has_typed_or_data or not typed_or_data)

        key = "output-typed-data" if typed_or_data else "output"
        source = self._find_sample(key, matches)
        return BlockSample(source.network, source.height, self.detail_attributes(source.height), source.rpc_block)

    def uncle_sample(self, *, present: bool) -> BlockSample:
        key = "uncle-present" if present else "uncle-empty"
        if present and key not in self._samples:
            self.prefetch_blocks([int(attributes["number"]) for attributes in self._eligible_rows()])
        source = self._find_sample(
            key,
            lambda _attributes, block: isinstance(block.get("uncles"), list) and bool(block["uncles"]) is present,
        )
        return BlockSample(source.network, source.height, self.detail_attributes(source.height), source.rpc_block)

    def pending_sample(self) -> BlockSample:
        if "detail-pending" not in self._samples:
            height = self.api_tip_height()
            block = self.block(height)
            self._samples["detail-pending"] = BlockSample(
                self.network.name,
                height,
                self.detail_attributes(height),
                block,
            )
        return self._samples["detail-pending"]

    def economic_state(self, block_hash: str) -> Mapping[str, Any]:
        if block_hash not in self._economic_states:
            result = self.rpc_result("get_block_economic_state", [block_hash])
            if not isinstance(result, dict):
                raise OracleUnavailable(f"{self.network.name} RPC economic state unavailable for {block_hash}")
            self._economic_states[block_hash] = result
        return self._economic_states[block_hash]

    def reward_sample(self) -> tuple[BlockSample, Mapping[str, Any]]:
        sample = self.confirmed_sample()
        header = sample.rpc_block.get("header")
        block_hash = header.get("hash") if isinstance(header, dict) else None
        if not isinstance(block_hash, str):
            raise OracleUnavailable(f"{self.network.name} RPC reward sample has no block hash")
        return sample, self.economic_state(block_hash)

    def detail_reward_sample(self) -> tuple[BlockSample, Mapping[str, Any]]:
        sample, state = self.reward_sample()
        return BlockSample(sample.network, sample.height, self.detail_attributes(sample.height), sample.rpc_block), state

    def fee_sample(self) -> tuple[BlockSample, Mapping[str, Any]]:
        if "detail-fee" in self._samples:
            sample = self._samples["detail-fee"]
            header = sample.rpc_block.get("header")
            block_hash = header.get("hash") if isinstance(header, dict) else None
            if not isinstance(block_hash, str):
                raise OracleUnavailable(f"{self.network.name} cached fee sample has no hash")
            return sample, self.economic_state(block_hash)
        rows = sorted(
            self._eligible_rows(),
            key=lambda attributes: (int(attributes.get("transactions_count", "0")) <= 1,),
        )
        for attributes in rows:
            height = int(attributes["number"])
            block = self.block(height)
            transactions = block.get("transactions")
            if not isinstance(transactions, list) or len(transactions) <= 1:
                continue
            header = block.get("header")
            block_hash = header.get("hash") if isinstance(header, dict) else None
            if not isinstance(block_hash, str):
                continue
            state = self.economic_state(block_hash)
            try:
                fee = decode_hex_int(state.get("txs_fee"), "economic_state.txs_fee")
            except ValueError:
                continue
            if fee > 0:
                sample = BlockSample(self.network.name, height, self.detail_attributes(height), block)
                self._samples["detail-fee"] = sample
                return sample, state
        raise OracleUnavailable(f"{self.network.name} has no mature non-zero-fee block fixture")

    def completed_epoch_extrema(self) -> EpochExtrema:
        if self._completed_epoch is not None:
            return self._completed_epoch
        current = self.detail_attributes(self.api_tip_height())
        try:
            previous_height = int(current["start_number"]) - 1
        except (KeyError, TypeError, ValueError) as error:
            raise OracleUnavailable(f"{self.network.name} current detail has invalid start_number") from error
        previous = self.detail_attributes(previous_height)
        try:
            epoch = int(previous["epoch"])
            start = int(previous["start_number"])
            length = int(previous["length"])
        except (KeyError, TypeError, ValueError) as error:
            raise OracleUnavailable(f"{self.network.name} previous Epoch fields are invalid") from error
        heights = list(range(start, start + length))
        largest = 0
        maximum_cycles: int | None = None
        for offset in range(0, len(heights), self.settings.rpc_batch_size):
            batch = heights[offset : offset + self.settings.rpc_batch_size]
            results = self.rpc_batch_results(
                [("get_block_by_number", [hex(height), "0x2", True]) for height in batch]
            )
            for height, result in zip(batch, results, strict=True):
                if not isinstance(result, dict) or not isinstance(result.get("block"), dict):
                    raise OracleUnavailable(f"{self.network.name} missing Epoch block {height}")
                self._blocks_with_cycles[height] = result
                try:
                    largest = max(largest, serialized_block_size_without_uncle_proposals(result["block"]))
                    cycles = block_cycles(result)
                except ValueError as error:
                    raise OracleUnavailable(f"{self.network.name} invalid Epoch block {height}: {error}") from error
                raw_cycles = result.get("cycles")
                if isinstance(raw_cycles, list) and raw_cycles:
                    maximum_cycles = max(maximum_cycles or 0, cycles)
        self._completed_epoch = EpochExtrema(
            self.network.name,
            epoch,
            start,
            length,
            previous,
            largest,
            maximum_cycles,
        )
        return self._completed_epoch

    def epoch_statistics(self) -> list[Mapping[str, Any]]:
        payload = self.explorer_json("/v1/epoch_statistics/updated_at")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            raise OracleUnavailable(f"{self.network.name} Explorer epoch statistics have no data")
        attributes: list[Mapping[str, Any]] = []
        for index, row in enumerate(data):
            item = row.get("attributes") if isinstance(row, dict) else None
            if not isinstance(item, dict):
                raise OracleUnavailable(f"{self.network.name} Epoch statistic {index} has no attributes")
            attributes.append(item)
        return attributes

    def ensure_stable(self, sample: BlockSample) -> None:
        original_header = sample.rpc_block.get("header")
        original_hash = original_header.get("hash") if isinstance(original_header, dict) else None
        fresh = self.block(sample.height, refresh=True)
        fresh_header = fresh.get("header")
        fresh_hash = fresh_header.get("hash") if isinstance(fresh_header, dict) else None
        if not original_hash or not fresh_hash or original_hash.lower() != fresh_hash.lower():
            raise ReorgObserved(
                f"{self.network.name} RPC hash changed at height {sample.height}: {original_hash!r} -> {fresh_hash!r}"
            )
