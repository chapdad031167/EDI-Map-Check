"""Mapping specification: Excel template, rule model, and parser."""

from mapcheck.spec.model import (
    CodeList,
    Condition,
    DataType,
    LoopContext,
    MappingRule,
    MappingSpec,
    Outcome,
    OutcomeKind,
    Predicate,
    RuleType,
)
from mapcheck.spec.parser import SpecLoadError, load_spec
from mapcheck.spec.template import create_template

__all__ = [
    "CodeList",
    "Condition",
    "DataType",
    "LoopContext",
    "MappingRule",
    "MappingSpec",
    "Outcome",
    "OutcomeKind",
    "Predicate",
    "RuleType",
    "SpecLoadError",
    "create_template",
    "load_spec",
]
