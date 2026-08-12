from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


MASK = "<redacted>"
DEFAULT_SECRET_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "apikey",
        "api_key",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "signature",
        "token",
    }
)


def is_secret_name(name: str, secret_names: Iterable[str] = DEFAULT_SECRET_NAMES) -> bool:
    lowered = name.lower()
    names = {item.lower() for item in secret_names}
    return lowered in names or lowered.endswith("_token") or lowered.endswith("_secret")


def redact_headers(
    headers: dict[str, str], secret_names: Iterable[str] = DEFAULT_SECRET_NAMES
) -> dict[str, str]:
    return {
        name: MASK if is_secret_name(name, secret_names) else value
        for name, value in headers.items()
    }


def redact_url(url: str, secret_names: Iterable[str] = DEFAULT_SECRET_NAMES) -> str:
    parts = urlsplit(url)
    query = [
        (name, MASK if is_secret_name(name, secret_names) else value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def redact_value(value: Any, secret_names: Iterable[str] = DEFAULT_SECRET_NAMES) -> Any:
    if isinstance(value, dict):
        return {
            key: MASK if is_secret_name(str(key), secret_names) else redact_value(item, secret_names)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, secret_names) for item in value]
    return value
