"""YAML loader for transaction definitions.

Strict by design, like the spec loader: a definition that doesn't match the
schema fails at load time with the file name and every problem found, so a
bad definition can never half-work at parse time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

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


class DefinitionError(Exception):
    """Raised when a transaction definition file is invalid."""

    def __init__(self, source: str, errors: list[str]) -> None:
        self.source = source
        self.errors = errors
        super().__init__(
            f"{len(errors)} problem(s) in transaction definition {source}:\n  - "
            + "\n  - ".join(errors)
        )


class _Ctx:
    """Collects errors with a dotted path to the offending YAML node."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.errors: list[str] = []

    def err(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def str_at(self, node: dict, path: str, key: str, required: bool = True) -> str | None:
        value = node.get(key)
        if value is None:
            if required:
                self.err(f"{path}.{key}", "is required")
            return None
        if not isinstance(value, str):
            # YAML happily parses `set: 850` as an int; be forgiving there.
            if isinstance(value, (int, float)):
                return str(value)
            self.err(f"{path}.{key}", f"expected a string, got {type(value).__name__}")
            return None
        return value

    def int_at(self, node: dict, path: str, key: str, default: int | None = None) -> int | None:
        value = node.get(key, default)
        if value is default:
            return default
        if not isinstance(value, int) or isinstance(value, bool):
            self.err(f"{path}.{key}", f"expected an integer, got {value!r}")
            return default
        return value

    def seg_list(self, node: dict, path: str, key: str) -> tuple[str, ...]:
        value = node.get(key, [])
        if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
            self.err(f"{path}.{key}", "expected a list of segment ids")
            return ()
        return tuple(s.upper() for s in value)


def _parse_hierarchy(node: Any, path: str, ctx: _Ctx) -> HierarchyDef | None:
    if not isinstance(node, dict):
        ctx.err(path, "expected a mapping with id_element/parent_element/level_element")
        return None
    id_el = ctx.int_at(node, path, "id_element")
    parent_el = ctx.int_at(node, path, "parent_element")
    level_el = ctx.int_at(node, path, "level_element")
    if None in (id_el, parent_el, level_el):
        ctx.err(path, "id_element, parent_element and level_element are all required")
        return None
    return HierarchyDef(id_element=id_el, parent_element=parent_el, level_element=level_el)


def _parse_levels(node: Any, path: str, ctx: _Ctx) -> tuple[LevelDef, ...]:
    if not isinstance(node, dict):
        ctx.err(path, "expected a mapping of level code -> {children, segments}")
        return ()
    levels = []
    for code, body in node.items():
        body = body or {}
        if not isinstance(body, dict):
            ctx.err(f"{path}.{code}", "expected a mapping")
            continue
        levels.append(
            LevelDef(
                code=str(code),
                children=tuple(str(c) for c in body.get("children", []) or []),
                segments=ctx.seg_list(body, f"{path}.{code}", "segments"),
            )
        )
    codes = [lv.code for lv in levels]
    for level in levels:
        for child in level.children:
            if child not in codes:
                ctx.err(path, f"level {level.code!r} lists unknown child level {child!r}")
    return tuple(levels)


def _parse_loop(node: Any, path: str, ctx: _Ctx) -> LoopDef | None:
    if not isinstance(node, dict):
        ctx.err(path, "expected a mapping")
        return None
    loop_id = ctx.str_at(node, path, "id")
    trigger = ctx.str_at(node, path, "trigger")
    if not loop_id or not trigger:
        return None
    hierarchy = None
    levels: tuple[LevelDef, ...] = ()
    if "hierarchical" in node:
        hierarchy = _parse_hierarchy(node["hierarchical"], f"{path}.hierarchical", ctx)
        levels = _parse_levels(node.get("levels", {}), f"{path}.levels", ctx)
        if hierarchy and not levels:
            ctx.err(f"{path}.levels", "hierarchical loops must declare at least one level")
    elif "levels" in node:
        ctx.err(f"{path}.levels", "levels are only allowed on hierarchical loops")

    nested = []
    for index, child in enumerate(node.get("loops", []) or []):
        parsed = _parse_loop(child, f"{path}.loops[{index}]", ctx)
        if parsed:
            nested.append(parsed)

    qualifier = ctx.int_at(node, path, "qualifier", default=None)
    if hierarchy is not None:
        if qualifier is not None and qualifier != hierarchy.level_element:
            ctx.err(
                f"{path}.qualifier",
                "hierarchical loops always qualify on level_element; omit qualifier",
            )
        qualifier = hierarchy.level_element
    return LoopDef(
        id=loop_id.upper(),
        trigger=trigger.upper(),
        qualifier=qualifier if qualifier is not None else 1,
        segments=ctx.seg_list(node, path, "segments"),
        loops=tuple(nested),
        max_repeats=ctx.int_at(node, path, "max_repeats", default=None),
        hierarchy=hierarchy,
        levels=levels,
    )


def _parse_operand(node: Any, path: str, ctx: _Ctx) -> Operand:
    if not isinstance(node, dict):
        ctx.err(path, "expected a mapping like {value: CTT01} or {count: PO1}")
        return Operand()
    keys = {k for k in ("value", "count") if k in node}
    if len(keys) != 1:
        ctx.err(path, "exactly one of 'value' or 'count' is required")
        return Operand()
    return Operand(
        value=str(node["value"]).upper() if "value" in node else None,
        count=str(node["count"]).upper() if "count" in node else None,
        implied=ctx.int_at(node, path, "implied", default=None),
    )


def _parse_recon(node: Any, index: int, ctx: _Ctx) -> ReconRule | None:
    path = f"reconciliation[{index}]"
    if not isinstance(node, dict):
        ctx.err(path, "expected a mapping")
        return None
    rule_id = ctx.str_at(node, path, "id")
    if not rule_id:
        return None
    check = node.get("check", "equals")
    if check != "equals":
        ctx.err(f"{path}.check", f"unsupported check {check!r} (only 'equals' so far)")
    severity = node.get("severity", "warning")
    if severity not in ("warning", "error"):
        ctx.err(f"{path}.severity", f"expected 'warning' or 'error', got {severity!r}")
    when = node.get("when")
    when_exists = None
    if when is not None:
        if isinstance(when, dict) and isinstance(when.get("exists"), str):
            when_exists = when["exists"].upper()
        else:
            ctx.err(f"{path}.when", "expected {exists: SEGnn}")
    return ReconRule(
        id=rule_id,
        left=_parse_operand(node.get("left"), f"{path}.left", ctx),
        right=_parse_operand(node.get("right"), f"{path}.right", ctx),
        check="equals",
        when_exists=when_exists,
        severity=severity if severity in ("warning", "error") else "warning",
        description=node.get("description", "") or "",
    )


def parse_definition(data: Any, source: str) -> TransactionDefinition:
    """Build a validated :class:`TransactionDefinition` from parsed YAML data.

    Raises :class:`DefinitionError` listing every problem found.
    """
    ctx = _Ctx(source)
    if not isinstance(data, dict):
        raise DefinitionError(source, ["top level must be a mapping"])

    tx_node = data.get("transaction")
    if not isinstance(tx_node, dict):
        raise DefinitionError(source, ["'transaction' block is required"])
    set_code = ctx.str_at(tx_node, "transaction", "set")
    name = ctx.str_at(tx_node, "transaction", "name")
    group = ctx.str_at(tx_node, "transaction", "functional_group")
    version = ctx.str_at(tx_node, "transaction", "version", required=False)

    areas: list[AreaDef] = []
    structure = data.get("structure")
    if not isinstance(structure, list) or not structure:
        ctx.err("structure", "at least one area is required")
        structure = []
    for index, area_node in enumerate(structure):
        path = f"structure[{index}]"
        if not isinstance(area_node, dict):
            ctx.err(path, "expected a mapping")
            continue
        area_id = ctx.str_at(area_node, path, "area")
        if not area_id:
            continue
        loops = []
        for loop_index, loop_node in enumerate(area_node.get("loops", []) or []):
            parsed = _parse_loop(loop_node, f"{path}.loops[{loop_index}]", ctx)
            if parsed:
                loops.append(parsed)
        if index == 0 and area_node.get("opens_area"):
            ctx.err(f"{path}.opens_area", "the first area is entered implicitly")
        areas.append(
            AreaDef(
                id=area_id,
                opens_with=ctx.seg_list(area_node, path, "opens_area"),
                segments=ctx.seg_list(area_node, path, "segments"),
                loops=tuple(loops),
            )
        )
    for index, area in enumerate(areas[1:], start=1):
        if not area.opens_with:
            ctx.err(f"structure[{index}].opens_area", f"area {area.id!r} needs opens_area")

    pairing = None
    pairing_node = data.get("output_pairing")
    if pairing_node is not None:
        if not isinstance(pairing_node, dict):
            ctx.err("output_pairing", "expected a mapping with list_path and loop")
        else:
            list_path = ctx.str_at(pairing_node, "output_pairing", "list_path")
            loop_ref = ctx.str_at(pairing_node, "output_pairing", "loop")
            if list_path and loop_ref:
                pairing = OutputPairing(list_path=list_path, loop=loop_ref.upper())

    recon = []
    for index, rule_node in enumerate(data.get("reconciliation", []) or []):
        parsed = _parse_recon(rule_node, index, ctx)
        if parsed:
            recon.append(parsed)
    seen_ids = set()
    for rule in recon:
        if rule.id in seen_ids:
            ctx.err("reconciliation", f"duplicate rule id {rule.id!r}")
        seen_ids.add(rule.id)

    if ctx.errors or not (set_code and name and group):
        if not ctx.errors:
            ctx.err("transaction", "set, name and functional_group are required")
        raise DefinitionError(source, ctx.errors)

    definition = TransactionDefinition(
        set_code=set_code,
        name=name,
        functional_group=group,
        version=version,
        areas=tuple(areas),
        output_pairing=pairing,
        reconciliation=tuple(recon),
        source=source,
    )

    if pairing and definition.loop(pairing.loop) is None:
        raise DefinitionError(
            source, [f"output_pairing.loop {pairing.loop!r} is not a declared loop"]
        )
    trigger_seen: dict[str, str] = {}
    for loop in definition.all_loops():
        if loop.id in trigger_seen:
            raise DefinitionError(source, [f"duplicate loop id {loop.id!r}"])
        trigger_seen[loop.id] = loop.trigger
    return definition


def load_definition(path: str | Path) -> TransactionDefinition:
    """Load and validate a definition from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise DefinitionError(str(path), ["file not found"])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DefinitionError(str(path), [f"invalid YAML: {exc}"]) from exc
    return parse_definition(data, source=str(path))
