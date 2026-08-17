from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_SETTINGS_FILE = Path(__file__).resolve().parents[2] / "config" / "networks.json"


@dataclass(frozen=True)
class NetworkSettings:
    name: str
    explorer_api_url: str
    ckb_rpc_url: str
    address_hrp: str


@dataclass(frozen=True)
class Settings:
    settings_file: Path
    run_live: bool
    timeout_seconds: float
    transport_retries: int
    max_lag_blocks: int
    proposal_window: int
    list_page_size: int
    sample_search_pages: int
    networks: tuple[NetworkSettings, ...]


def _boolean(value: object, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{field} must be a boolean, got {value!r}")


def load_settings(
    settings_file: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    path = Path(settings_file or os.getenv("CKB_RPC_CORRECTNESS_SETTINGS", DEFAULT_SETTINGS_FILE)).resolve()
    payload = json.loads(path.read_text())
    env = dict(os.environ if environ is None else environ)

    networks: list[NetworkSettings] = []
    for item in payload.get("networks", []):
        name = str(item["name"]).strip().lower()
        prefix = name.upper()
        explorer_url = env.get(f"{prefix}_EXPLORER_API_URL", str(item["explorer_api_url"])).rstrip("/")
        rpc_url = env.get(f"{prefix}_CKB_RPC_URL", str(item["ckb_rpc_url"])).rstrip("/")
        hrp = str(item["address_hrp"]).strip()
        if not name or not explorer_url or not rpc_url or hrp not in {"ckb", "ckt"}:
            raise ValueError(f"invalid network settings: {item!r}")
        networks.append(NetworkSettings(name, explorer_url, rpc_url, hrp))
    if not networks:
        raise ValueError("settings must declare at least one network")
    if len({item.name for item in networks}) != len(networks):
        raise ValueError("network names must be unique")

    run_live = _boolean(env.get("RUN_LIVE_RPC_CORRECTNESS", payload.get("run_live", True)), field="run_live")
    timeout_seconds = float(payload.get("timeout_seconds", 30))
    retries = int(payload.get("transport_retries", 1))
    max_lag = int(payload.get("max_lag_blocks", 5))
    proposal_window = int(payload.get("proposal_window", 10))
    page_size = int(payload.get("list_page_size", 100))
    search_pages = int(payload.get("sample_search_pages", 5))
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if retries < 0 or max_lag < 0 or proposal_window < 0:
        raise ValueError("retry, lag, and proposal-window values must be non-negative")
    if not 1 <= page_size <= 100:
        raise ValueError("list_page_size must be between 1 and 100")
    if not 1 <= search_pages <= 50:
        raise ValueError("sample_search_pages must be between 1 and 50")

    return Settings(
        path,
        run_live,
        timeout_seconds,
        retries,
        max_lag,
        proposal_window,
        page_size,
        search_pages,
        tuple(networks),
    )
