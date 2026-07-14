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
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


class OutputLoadError(Exception):
    """Raised when the output file cannot be loaded into the canonical model."""


def parse_xml_safely(path: Path) -> "ET.Element":
    """Parse an XML file, refusing a DOCTYPE.

    ElementTree does not resolve *external* entities (no XXE), but it does
    expand *internal* ones, so a DTD entity bomb could amplify memory/CPU.
    IDoc/EDI XML never needs a DOCTYPE, so any is rejected outright — a
    dependency-free block on entity-expansion attacks. Raises
    :class:`OutputLoadError` on a DOCTYPE or malformed XML.
    """
    data = path.read_bytes()
    if b"<!DOCTYPE" in data.upper():
        raise OutputLoadError(f"{path}: XML DOCTYPE declarations are not allowed")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise OutputLoadError(f"{path}: not valid XML — {exc}") from exc


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


def _read_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise OutputLoadError(f"{path}: not valid JSON — {exc}") from exc


def _json_document(data: Any, path: Path, index: int | None = None) -> CanonicalOutput:
    """Wrap one parsed JSON object as a document; ``index`` labels array members."""
    if not isinstance(data, dict):
        where = f"element {index}" if index is not None else "top-level JSON value"
        raise OutputLoadError(f"{path}: {where} must be an object")
    return CanonicalOutput(data=data, typed=True, source_path=str(path), format_name="json")


def _load_json(path: Path) -> CanonicalOutput:
    data = _read_json(path)
    if isinstance(data, list):
        raise OutputLoadError(
            f"{path}: top-level JSON is an array of {len(data)} document(s) — "
            "use interchange validation for multi-document output"
        )
    return _json_document(data, path)


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


def load_output(path: str | Path, output_format: str | None = None) -> CanonicalOutput:
    """Load an output file, picking the adapter by extension/content.

    ``.json`` loads as JSON; ``.xml`` and IDoc flat files are matched
    against the registered output-format definitions (ORDERS05, DESADV01,
    INVOIC02, ...); anything else is keyed flat. Passing ``output_format``
    names a registered definition explicitly — used for user-supplied
    formats (e.g. a delimited layout) that can't be auto-detected.
    """
    from mapcheck.output import idoc

    path = Path(path)
    if not path.exists():
        raise OutputLoadError(f"output file not found: {path}")

    if output_format is not None:
        defn = idoc.default_output_registry.get(output_format)
        if path.suffix.lower() == ".xml":
            return idoc.load_idoc_xml(path, defn)
        return idoc.load_idoc_flat(path, defn)

    if path.suffix.lower() == ".json":
        return _load_json(path)
    if path.suffix.lower() == ".xml":
        root = parse_xml_safely(path)
        defn = idoc.default_output_registry.detect_xml(root.tag)
        if defn is None:
            raise OutputLoadError(
                f"{path}: no registered IDoc XML format matches root <{root.tag}>"
            )
        return idoc.load_idoc_xml(path, defn)
    with path.open(encoding="utf-8") as fh:
        first_line = fh.readline()
    defn = idoc.default_output_registry.detect_flat(first_line)
    if defn is not None:
        return idoc.load_idoc_flat(path, defn)
    return _load_flat(path)


def load_output_documents(
    path: str | Path, output_format: str | None = None
) -> list[CanonicalOutput]:
    """Load an output file as one or more canonical documents.

    A JSON array yields one document per element; every other container is
    a single document (multi-document flat/IDoc is a planned follow-on).
    Used by interchange validation; single-document callers use
    :func:`load_output`.
    """
    path = Path(path)
    if not path.exists():
        raise OutputLoadError(f"output file not found: {path}")
    if output_format is None and path.suffix.lower() == ".json":
        data = _read_json(path)
        if isinstance(data, list):
            if not data:
                raise OutputLoadError(f"{path}: JSON array is empty — no output documents")
            return [_json_document(item, path, index=i) for i, item in enumerate(data)]
        return [_json_document(data, path)]
    return [load_output(path, output_format=output_format)]
