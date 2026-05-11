"""Per-request language detection and JSON-backed translation."""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.requests import Request

_LOCALES_DIR = Path(__file__).parent / "locales"
_SUPPORTED = frozenset({"en", "de", "fr", "pt-br"})
_DEFAULT = "en"
# Explicit dict lookup severs CodeQL taint flow from user input to file path.
_LANG_MAP: dict[str, str] = {"en": "en", "de": "de", "fr": "fr", "pt-br": "pt-br"}
# "pt" is treated as an alias for "pt-br" in Accept-Language negotiation.
_LANG_ALIAS: dict[str, str] = {"pt": "pt-br"}

_cache: dict[str, dict[str, str]] = {}


def _load(lang: str) -> dict[str, str]:
    safe_lang = _LANG_MAP.get(lang, _DEFAULT)
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
        raw = part.strip().lower()
        # Check full subtag (e.g. "pt-br") before falling back to primary tag.
        if raw in _SUPPORTED:
            return raw
        alias = _LANG_ALIAS.get(raw)
        if alias:
            return alias
        code = raw.split("-")[0]
        if code in _SUPPORTED:
            return code
        alias = _LANG_ALIAS.get(code)
        if alias:
            return alias
    return _DEFAULT


def make_translator(lang: str) -> Callable[..., str]:
    strings = _load(lang)
    fallback = _load(_DEFAULT)

    def t(key: str, **kwargs: Any) -> str:
        template = strings.get(key) or fallback.get(key) or key
        return template.format(**kwargs) if kwargs else template

    return t
