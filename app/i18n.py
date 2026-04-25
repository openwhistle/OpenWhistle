"""Per-request language detection and JSON-backed translation."""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.requests import Request

_LOCALES_DIR = Path(__file__).parent / "locales"
_SUPPORTED = frozenset({"en", "de"})
_DEFAULT = "en"

_cache: dict[str, dict[str, str]] = {}


def _load(lang: str) -> dict[str, str]:
    # Restrict to known-good values before using in a file path.
    safe_lang = lang if lang in _SUPPORTED else _DEFAULT
    if safe_lang not in _cache:
        path = _LOCALES_DIR / f"{safe_lang}.json"
        _cache[safe_lang] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return _cache[safe_lang]


def get_lang(request: Request) -> str:
    lang = request.cookies.get("ow-lang", "")
    if lang in _SUPPORTED:
        return lang
    accept = request.headers.get("accept-language", "")
    for part in re.split(r"[,;]", accept):
        code = part.strip().split("-")[0].lower()
        if code in _SUPPORTED:
            return code
    return _DEFAULT


def make_translator(lang: str) -> Callable[..., str]:
    strings = _load(lang)
    fallback = _load(_DEFAULT)

    def t(key: str, **kwargs: Any) -> str:
        template = strings.get(key) or fallback.get(key) or key
        return template.format(**kwargs) if kwargs else template

    return t
