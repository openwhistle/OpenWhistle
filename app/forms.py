"""Form field types: the limits the page shows, enforced by the server.

``TextN`` for a text field whose form says ``maxlength="N"`` (or whose
column is ``VARCHAR(N)``), ``Multiline`` for one whose route checks the
length itself and answers on the form:

- Line breaks become ``\\n`` before the length is counted. A browser submits a
  textarea's line breaks as CRLF while ``maxlength`` counts each as one, so a
  text filled to its limit arrived longer than the limit: a 500-character
  reason with one line break was refused, a 10 000-character report was cut.
- Longer than ``n`` is a 422. Several fields had no server-side limit at all
  (an admin reply took any length) or only the column's, which made an
  oversized value a 500.

``SortOrder`` is an ``INTEGER`` column: out of its range was a 500 too.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Form
from pydantic import BeforeValidator


def _lf(value: Any) -> Any:
    return value.replace("\r\n", "\n").replace("\r", "\n") if isinstance(value, str) else value


Multiline = Annotated[str, BeforeValidator(_lf), Form()]
Text32 = Annotated[str, BeforeValidator(_lf), Form(max_length=32)]
Text64 = Annotated[str, BeforeValidator(_lf), Form(max_length=64)]
Text128 = Annotated[str, BeforeValidator(_lf), Form(max_length=128)]
Text256 = Annotated[str, BeforeValidator(_lf), Form(max_length=256)]
Text320 = Annotated[str, BeforeValidator(_lf), Form(max_length=320)]
Text512 = Annotated[str, BeforeValidator(_lf), Form(max_length=512)]
Text5000 = Annotated[str, BeforeValidator(_lf), Form(max_length=5000)]

SortOrder = Annotated[int, Form(ge=-(2**31), le=2**31 - 1)]
