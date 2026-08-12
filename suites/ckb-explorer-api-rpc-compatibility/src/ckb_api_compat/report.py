from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import ComparisonResult
from .redact import MASK, is_secret_name, redact_headers, redact_url, redact_value


def result_dict(result: ComparisonResult, *, max_body_chars: int = 200_000) -> dict:
    payload = result.to_dict(max_body_chars=max_body_chars)
    for difference in payload["differences"]:
        leaf = difference["path"].rsplit(".", 1)[-1].split("[", 1)[0].strip("$/")
        if is_secret_name(leaf):
            difference["baseline"] = MASK
            difference["candidate"] = MASK
        else:
            difference["baseline"] = redact_value(difference["baseline"])
            difference["candidate"] = redact_value(difference["candidate"])
    for side in ("baseline", "candidate"):
        payload[side]["url"] = redact_url(payload[side]["url"])
        payload[side]["headers"] = redact_headers(payload[side]["headers"])
        if payload[side]["body_encoding"] == "utf-8":
            media_type = payload[side]["headers"].get("content-type", "").lower()
            if "json" in media_type:
                try:
                    decoded = json.loads(payload[side]["body"])
                except (TypeError, json.JSONDecodeError):
                    pass
                else:
                    payload[side]["body"] = json.dumps(
                        redact_value(decoded), ensure_ascii=False, separators=(",", ":")
                    )
    return payload


def report_payload(results: Iterable[ComparisonResult], *, max_body_chars: int = 200_000) -> dict:
    items = [result_dict(result, max_body_chars=max_body_chars) for result in results]
    return {
        "summary": {
            "total": len(items),
            "matched": sum(item["matched"] for item in items),
            "mismatched": sum(not item["matched"] and not item["skipped"] for item in items),
            "skipped": sum(item["skipped"] for item in items),
        },
        "results": items,
    }


def write_report(path: str | Path, payload: dict) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
