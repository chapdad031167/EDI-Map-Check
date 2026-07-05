"""Declarative transaction definitions: schema, YAML loader, and registry."""

from mapcheck.transactions.loader import DefinitionError, load_definition
from mapcheck.transactions.registry import TransactionRegistry, default_registry
from mapcheck.transactions.schema import (
    AreaDef,
    HierarchyDef,
    LevelDef,
    LoopDef,
    Operand,
    OutputPairing,
    ReconRule,
    TransactionDefinition,
)

__all__ = [
    "AreaDef",
    "DefinitionError",
    "HierarchyDef",
    "LevelDef",
    "LoopDef",
    "Operand",
    "OutputPairing",
    "ReconRule",
    "TransactionDefinition",
    "TransactionRegistry",
    "default_registry",
    "load_definition",
]
