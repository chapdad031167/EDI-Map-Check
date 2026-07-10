"""SAP IDoc ORDERS05 output adapter.

Thin compatibility shim: the parsing is now driven by the declarative
definition ``definitions/orders05.yaml`` through the generic
:mod:`mapcheck.output.idoc` engine. These entry points remain for callers
that want ORDERS05 specifically (and for the flat-file sniff in
``adapter.load_output``).
"""

from __future__ import annotations

from pathlib import Path

from mapcheck.output.adapter import CanonicalOutput
from mapcheck.output.idoc import (
    default_output_registry,
    load_idoc_flat,
    load_idoc_xml,
)


def _orders05() -> "object":
    return default_output_registry.get("idoc-orders05")


#: Backward-compatible field table (segment -> {FIELD: (offset, length)}),
#: derived from the definition for test fixtures.
_FLAT_FIELDS = {
    name: dict(seg.fields) for name, seg in _orders05().segments.items()
}


def is_idoc_flat(first_line: str) -> bool:
    """True when a file's first line is an IDoc control record."""
    return first_line.startswith("EDI_DC40")


def load_orders05_flat(path: Path) -> CanonicalOutput:
    """Parse an ORDERS05 IDoc flat file into the canonical model."""
    return load_idoc_flat(Path(path), _orders05())


def load_orders05_xml(path: Path) -> CanonicalOutput:
    """Parse a standard SAP ORDERS05 IDoc XML file into the canonical model."""
    return load_idoc_xml(Path(path), _orders05())
