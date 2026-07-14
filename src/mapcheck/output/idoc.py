"""Config-driven IDoc-style output adapters.

The ORDERS05 adapter proved that folding an IDoc into the canonical model
is a handful of *mechanical* routing rules over per-segment field tables —
nothing about it is specific to ORDERS05. This module makes those rules
declarative: an output-format definition (YAML) names the segments, their
field layout (fixed-width offsets or delimited columns), and how each
routes into the canonical dict. One definition drives both the flat reader
and the XML reader, so the two renditions stay byte-identical.

Routing kinds (the whole grammar)::

    object       segment fields merge into a named section dict
    keyed        a qualifier field selects a sub-key; one value field, or
                 a sub-dict of value fields
    partner      keyed, but the sub-key is lowercased (SAP PARVW convention)
    line         start a new entry in the repeating ``lines`` list
    line_child   fold into the current line under a group, qualifier-keyed

Everything else — MISSING semantics (blank/absent omitted), first-wins on
repeated qualifiers, the single-repeating-list constraint — matches the
hand-written ORDERS05 adapter it generalizes.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml

from mapcheck.output.adapter import CanonicalOutput, OutputLoadError, parse_xml_safely

#: (segment name, {FIELD: value}) — the stream both readers emit.
_SegmentStream = Iterator[tuple[str, dict[str, str]]]

_ROUTE_KINDS = {"object", "keyed", "partner", "line", "line_child"}


class DefinitionError(Exception):
    """Raised when an output-format definition is malformed."""


@dataclass(frozen=True)
class Route:
    """How a segment's fields route into the canonical dict."""

    kind: str
    section: str | None = None       # object / keyed / partner
    group: str | None = None         # line_child
    qualifier: str | None = None     # keyed / partner / line_child
    value: str | None = None         # keyed single value
    values: tuple[str, ...] = ()     # keyed multi / partner / line_child


@dataclass(frozen=True)
class SegmentDef:
    """One segment: its field layout and routing."""

    name: str
    #: field -> (offset, length) for fixed layouts, or field -> column index
    #: for delimited layouts.
    fields: dict[str, Any]
    route: Route


@dataclass(frozen=True)
class OutputFormatDef:
    """A declarative output-format definition."""

    format: str
    layout: str                       # 'fixed' | 'delimited'
    segments: dict[str, SegmentDef]
    basic_type: str | None = None     # IDoc control sanity check
    segnam: tuple[int, int] = (0, 30)  # fixed: where the record name lives
    sdata_start: int = 63             # fixed: field offsets measured from here
    delimiter: str = ","              # delimited
    record_id_col: int = 0            # delimited: column holding the record code
    control_record: str = "EDI_DC40"  # flat control-record prefix
    xml_root: str | None = None       # xml detection: expected root tag


# --------------------------------------------------------------------------
# Definition parsing
# --------------------------------------------------------------------------


def _parse_route(seg_name: str, raw: dict) -> Route:
    kind = raw.get("kind")
    if kind not in _ROUTE_KINDS:
        raise DefinitionError(
            f"segment {seg_name}: route kind {kind!r} must be one of {sorted(_ROUTE_KINDS)}"
        )
    values = tuple(raw.get("values", ()) or ())
    route = Route(
        kind=kind,
        section=raw.get("section"),
        group=raw.get("group"),
        qualifier=raw.get("qualifier"),
        value=raw.get("value"),
        values=values,
    )
    if kind in ("object", "keyed", "partner") and not route.section:
        raise DefinitionError(f"segment {seg_name}: {kind} route requires a 'section'")
    if kind == "line_child" and not route.group:
        raise DefinitionError(f"segment {seg_name}: line_child route requires a 'group'")
    if kind in ("keyed", "partner", "line_child") and not route.qualifier:
        raise DefinitionError(f"segment {seg_name}: {kind} route requires a 'qualifier'")
    if kind == "keyed" and not (route.value or route.values):
        raise DefinitionError(
            f"segment {seg_name}: keyed route requires a 'value' or 'values'"
        )
    return route


def parse_definition(data: dict, source: str = "<definition>") -> OutputFormatDef:
    """Build an :class:`OutputFormatDef` from parsed YAML."""
    try:
        fmt = data["format"]
        layout = data.get("layout", "fixed")
        segments_raw = data["segments"]
    except KeyError as exc:
        raise DefinitionError(f"{source}: missing required key {exc.args[0]!r}") from None
    if layout not in ("fixed", "delimited"):
        raise DefinitionError(f"{source}: layout must be 'fixed' or 'delimited'")

    segments: dict[str, SegmentDef] = {}
    for name, raw in segments_raw.items():
        fields = raw.get("fields", {})
        if layout == "fixed":
            fields = {k: tuple(v) for k, v in fields.items()}
        route = _parse_route(name, raw.get("route", {}))
        segments[name] = SegmentDef(name=name, fields=fields, route=route)

    detect = data.get("detect", {})
    flat_detect = detect.get("flat", {})
    xml_detect = detect.get("xml", {})
    segnam = tuple(data.get("segnam", (0, 30)))
    return OutputFormatDef(
        format=fmt,
        layout=layout,
        segments=segments,
        basic_type=data.get("basic_type"),
        segnam=segnam,  # type: ignore[arg-type]
        sdata_start=data.get("sdata_start", 63),
        delimiter=data.get("delimiter", ","),
        record_id_col=data.get("record_id_col", 0),
        control_record=flat_detect.get("control_record", "EDI_DC40"),
        xml_root=xml_detect.get("root"),
    )


# --------------------------------------------------------------------------
# Shared fold: segment stream -> canonical dict
# --------------------------------------------------------------------------


def _fold(segments: _SegmentStream, defn: OutputFormatDef, source: str) -> dict[str, Any]:
    """Fold an in-document-order segment stream into the canonical dict."""
    data: dict[str, Any] = {}
    lines: list[dict[str, Any]] = []

    def qualified(section: dict, key: str, fields: dict[str, str], names: tuple[str, ...]) -> None:
        entry = {name.lower(): fields[name] for name in names if name in fields}
        if entry:
            section.setdefault(key, entry)

    for seg_name, fields in segments:
        seg_def = defn.segments.get(seg_name)
        if seg_def is None:
            continue
        route = seg_def.route
        if route.kind == "object":
            section = data.setdefault(route.section, {})
            for name, value in fields.items():
                section.setdefault(name.lower(), value)
        elif route.kind == "keyed":
            if route.qualifier not in fields:
                continue
            key = fields[route.qualifier]
            section = data.setdefault(route.section, {})
            if route.value is not None:
                if route.value in fields:
                    section.setdefault(key, fields[route.value])
            else:
                qualified(section, key, fields, route.values)
        elif route.kind == "partner":
            if route.qualifier not in fields:
                continue
            qualified(
                data.setdefault(route.section, {}),
                fields[route.qualifier].lower(),
                fields,
                route.values,
            )
        elif route.kind == "line":
            lines.append({name.lower(): value for name, value in fields.items()})
        elif route.kind == "line_child":
            if not lines:
                raise OutputLoadError(
                    f"{source}: {seg_name} item segment appears before any line segment"
                )
            if route.qualifier not in fields:
                continue
            qualified(
                lines[-1].setdefault(route.group, {}),
                fields[route.qualifier],
                fields,
                route.values,
            )

    if lines:
        data["lines"] = lines
    if not data:
        raise OutputLoadError(f"{source}: no in-scope {defn.format} segments found")
    return data


# --------------------------------------------------------------------------
# Flat reader (fixed-width or delimited)
# --------------------------------------------------------------------------


def _read_fields(seg_def: SegmentDef, defn: OutputFormatDef, record: str, parts: list[str]) -> dict:
    fields: dict[str, str] = {}
    if defn.layout == "fixed":
        sdata = record[defn.sdata_start:]
        for name, (offset, length) in seg_def.fields.items():
            value = sdata[offset : offset + length].strip()
            if value:
                fields[name] = value
    else:  # delimited
        for name, col in seg_def.fields.items():
            if col < len(parts):
                value = parts[col].strip()
                if value:
                    fields[name] = value
    return fields


def _flat_segments(text: str, defn: OutputFormatDef, source: str) -> _SegmentStream:
    lines = text.splitlines()
    if defn.layout == "fixed":
        if not lines or not lines[0].startswith(defn.control_record):
            raise OutputLoadError(
                f"{source}: missing {defn.control_record} control record"
            )
        if defn.basic_type and defn.basic_type not in lines[0]:
            raise OutputLoadError(
                f"{source}: control record does not name basic type {defn.basic_type} — "
                f"only {defn.basic_type} IDocs are supported"
            )
        data_lines = lines[1:]
        start, end = defn.segnam
    else:
        data_lines = lines
        start = end = 0

    for line in data_lines:
        if not line.strip():
            continue
        if defn.layout == "fixed":
            seg_name = line[start:end].strip()
            parts: list[str] = []
        else:
            parts = line.split(defn.delimiter)
            if defn.record_id_col >= len(parts):
                continue
            seg_name = parts[defn.record_id_col].strip()
        seg_def = defn.segments.get(seg_name)
        if seg_def is None:
            continue
        yield seg_name, _read_fields(seg_def, defn, line, parts)


def load_idoc_flat(path: Path, defn: OutputFormatDef) -> CanonicalOutput:
    """Parse a flat (fixed-width or delimited) file per a format definition."""
    text = Path(path).read_text(encoding="utf-8")
    data = _fold(_flat_segments(text, defn, str(path)), defn, str(path))
    return CanonicalOutput(
        data=data, typed=False, source_path=str(path), format_name=defn.format
    )


# --------------------------------------------------------------------------
# XML reader (tag = field name; positions ignored)
# --------------------------------------------------------------------------


def _xml_segments(element: ET.Element, defn: OutputFormatDef) -> _SegmentStream:
    """Preorder walk emitting segments; nesting becomes document order."""
    for child in element:
        seg_def = defn.segments.get(child.tag)
        if seg_def is not None:
            fields = {}
            for sub in child:
                if sub.tag in defn.segments:
                    continue  # nested segment, handled by recursion
                name = sub.tag.upper()
                if name in seg_def.fields:
                    value = (sub.text or "").strip()
                    if value:
                        fields[name] = value
            yield child.tag, fields
        yield from _xml_segments(child, defn)


def load_idoc_xml(path: Path, defn: OutputFormatDef) -> CanonicalOutput:
    """Parse an IDoc XML file per a format definition."""
    root = parse_xml_safely(path)
    expected_root = defn.xml_root or defn.basic_type
    if expected_root and root.tag != expected_root:
        raise OutputLoadError(
            f"{path}: expected a {expected_root} IDoc XML root, found <{root.tag}>"
        )
    idoc = root.find("IDOC")
    if idoc is None:
        raise OutputLoadError(f"{path}: no IDOC element under the {root.tag} root")
    control = idoc.find("EDI_DC40")
    if control is not None and defn.basic_type:
        idoctyp = control.findtext("IDOCTYP", "").strip()
        if idoctyp and idoctyp != defn.basic_type:
            raise OutputLoadError(
                f"{path}: control record names basic type {idoctyp!r} — "
                f"only {defn.basic_type} IDocs are supported"
            )
    data = _fold(_xml_segments(idoc, defn), defn, str(path))
    return CanonicalOutput(
        data=data, typed=False, source_path=str(path), format_name=defn.format
    )


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

_DEFINITIONS_DIR = Path(__file__).parent / "definitions"


class OutputFormatRegistry:
    """Discovers bundled output-format definitions and holds user ones."""

    def __init__(self) -> None:
        self._by_format: dict[str, OutputFormatDef] = {}
        self._bundled_loaded = False

    def _load_bundled(self) -> None:
        if self._bundled_loaded:
            return
        self._bundled_loaded = True
        if not _DEFINITIONS_DIR.is_dir():
            return
        for entry in sorted(_DEFINITIONS_DIR.iterdir()):
            if entry.suffix in (".yaml", ".yml"):
                data = yaml.safe_load(entry.read_text(encoding="utf-8"))
                defn = parse_definition(data, source=entry.name)
                self._by_format[defn.format] = defn

    def register(self, defn: OutputFormatDef) -> None:
        self._load_bundled()
        self._by_format[defn.format] = defn

    def register_file(self, path: str | Path) -> OutputFormatDef:
        path = Path(path)
        if not path.exists():
            raise DefinitionError(f"output definition not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        defn = parse_definition(data, source=str(path))
        self.register(defn)
        return defn

    def get(self, format_name: str) -> OutputFormatDef:
        self._load_bundled()
        if format_name not in self._by_format:
            raise DefinitionError(
                f"unknown output format {format_name!r} "
                f"(known: {', '.join(sorted(self._by_format)) or 'none'})"
            )
        return self._by_format[format_name]

    def all(self) -> list[OutputFormatDef]:
        self._load_bundled()
        return list(self._by_format.values())

    def detect_flat(self, first_line: str) -> OutputFormatDef | None:
        """A fixed IDoc definition whose control record + basic type match."""
        self._load_bundled()
        for defn in self._by_format.values():
            if defn.layout != "fixed":
                continue
            if first_line.startswith(defn.control_record) and (
                defn.basic_type is None or defn.basic_type in first_line
            ):
                return defn
        return None

    def detect_xml(self, root_tag: str) -> OutputFormatDef | None:
        self._load_bundled()
        for defn in self._by_format.values():
            if (defn.xml_root or defn.basic_type) == root_tag:
                return defn
        return None


default_output_registry = OutputFormatRegistry()


def register_output_definition(path: str | Path) -> OutputFormatDef:
    """Register a user-supplied output-format definition from a YAML file."""
    return default_output_registry.register_file(path)
