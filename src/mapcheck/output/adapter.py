"""Canonical output model and format adapters.

The validation engine never looks at the output file directly — it sees a
:class:`CanonicalOutput`: a nested dict of sections (``order``, ``ship_to``,
...), a ``lines`` list, and a ``summary`` section, addressed by the spec's
Target Field dot paths (``order.po_number``, ``lines[].qty``).

Two reference formats load into that model:

* **JSON** (``.json``) — the nested structure as-is, with native types.
* **Keyed flat** (anything else) — one record per line,
  ``<code>|key=value|key=value``: ``H`` (header → ``order``), ``A``
  (address/party → the section named by its ``role`` key), ``D`` (detail →
  appended to ``lines``), ``S`` (summary). ``#`` lines and blank lines are
  ignored. All values are strings; the engine coerces per the spec's Data
  Type column.

Additional formats mean one function: parse the file into the canonical
dict shape and return ``CanonicalOutput`` with the right ``typed`` flag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


class OutputLoadError(Exception):
    """Raised when the output file cannot be loaded into the canonical model."""


class _Missing:
    """Sentinel distinguishing 'field absent' from a present null/empty value."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - repr only
        return "<MISSING>"


MISSING: Any = _Missing()


@dataclass(frozen=True)
class CanonicalOutput:
    """A loaded output file, addressable by spec Target Field paths."""

    data: dict[str, Any]
    #: True when the format carries native types (JSON); False when all
    #: values are strings (flat) and type checks must be lexical.
    typed: bool
    source_path: str
    format_name: str

    def get(self, path: str, line_index: int | None = None) -> Any:
        """Resolve a Target Field path; returns :data:`MISSING` when absent.

        ``lines[].qty`` requires ``line_index``; plain paths ignore it.
        """
        node: Any = self.data
        for part in path.split("."):
            if part.endswith("[]"):
                if line_index is None:
                    raise ValueError(f"path {path!r} requires a line index")
                node = _dict_get(node, part[:-2])
                if node is MISSING:
                    return MISSING
                if not isinstance(node, list):
                    return MISSING
                if line_index >= len(node):
                    return MISSING
                node = node[line_index]
            else:
                node = _dict_get(node, part)
                if node is MISSING:
                    return MISSING
        return node

    def line_count(self, list_path: str = "lines") -> int:
        """Number of entries in the repeating section (0 when absent)."""
        node = _dict_get(self.data, list_path)
        return len(node) if isinstance(node, list) else 0

    def walk_paths(self) -> Iterator[tuple[str, str, Any]]:
        """Yield ``(normalized_path, concrete_path, value)`` for every leaf.

        Normalized paths use ``lines[]`` notation so they can be matched
        against spec Target Fields; concrete paths keep the index
        (``lines[2].qty``) for reporting.
        """
        yield from _walk("", "", self.data)


def _dict_get(node: Any, key: str) -> Any:
    if isinstance(node, dict) and key in node:
        return node[key]
    return MISSING


def _walk(norm_prefix: str, concrete_prefix: str, node: Any) -> Iterator[tuple[str, str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            norm = f"{norm_prefix}.{key}" if norm_prefix else key
            concrete = f"{concrete_prefix}.{key}" if concrete_prefix else key
            yield from _walk(norm, concrete, value)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(f"{norm_prefix}[]", f"{concrete_prefix}[{index}]", value)
    else:
        yield norm_prefix, concrete_prefix, node


# --------------------------------------------------------------------------
# JSON adapter
# --------------------------------------------------------------------------


def _load_json(path: Path) -> CanonicalOutput:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise OutputLoadError(f"{path}: not valid JSON — {exc}") from exc
    if not isinstance(data, dict):
        raise OutputLoadError(f"{path}: top-level JSON value must be an object")
    return CanonicalOutput(data=data, typed=True, source_path=str(path), format_name="json")


# --------------------------------------------------------------------------
# Keyed flat adapter
# --------------------------------------------------------------------------

_FLAT_SECTIONS = {"H": "order", "S": "summary"}


def _parse_flat_record(line: str, line_no: int, path: Path) -> tuple[str, dict[str, str]]:
    parts = line.split("|")
    code = parts[0].strip()
    fields: dict[str, str] = {}
    for chunk in parts[1:]:
        if not chunk:
            continue
        key, sep, value = chunk.partition("=")
        if not sep or not key.strip():
            raise OutputLoadError(
                f"{path}:{line_no}: malformed field {chunk!r} (expected key=value)"
            )
        fields[key.strip()] = value
    return code, fields


def _load_flat(path: Path) -> CanonicalOutput:
    data: dict[str, Any] = {}
    lines: list[dict[str, str]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.rstrip()
        if not line or line.startswith("#"):
            continue
        code, fields = _parse_flat_record(line, line_no, path)
        if code in _FLAT_SECTIONS:
            data.setdefault(_FLAT_SECTIONS[code], {}).update(fields)
        elif code == "A":
            role = fields.pop("role", None)
            if not role:
                raise OutputLoadError(f"{path}:{line_no}: A record requires a role field")
            data.setdefault(role, {}).update(fields)
        elif code == "D":
            lines.append(fields)
        else:
            raise OutputLoadError(
                f"{path}:{line_no}: unknown record code {code!r} (expected H, A, D, or S)"
            )
    if lines:
        data["lines"] = lines
    if not data:
        raise OutputLoadError(f"{path}: no records found")
    return CanonicalOutput(data=data, typed=False, source_path=str(path), format_name="flat")


def load_output(path: str | Path) -> CanonicalOutput:
    """Load an output file, picking the adapter by extension.

    ``.json`` loads as JSON; anything else as keyed flat.
    """
    path = Path(path)
    if not path.exists():
        raise OutputLoadError(f"output file not found: {path}")
    if path.suffix.lower() == ".json":
        return _load_json(path)
    return _load_flat(path)
