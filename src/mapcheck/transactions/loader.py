"""YAML loader for transaction definitions.

Strict by design, like the spec loader: a definition that doesn't match the
schema fails at load time with the file name and every problem found, so a
bad definition can never half-work at parse time.
"""

from __future__ import annotations

import re
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
    RequiredElementDef,
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


def _parse_expr(text: str, path: str, ctx: _Ctx) -> tuple[str, ...]:
    """Parse a product expression like ``IT102 * IT104`` into element refs."""
    refs = [part.strip().upper() for part in text.split("*")]
    if not refs or any(not re.match(r"^[A-Z][A-Z0-9]{1,2}\d{2}$", ref) for ref in refs):
        ctx.err(
            path,
            f"invalid expression {text!r} (expected element refs joined by *, "
            "e.g. 'IT102 * IT104')",
        )
        return ()
    return tuple(refs)


def _parse_operand(node: Any, path: str, ctx: _Ctx) -> Operand:
    if not isinstance(node, dict):
        ctx.err(
            path,
            "expected a mapping like {value: CTT01}, {count: PO1}, "
            "{sum: {loop: 'HL[I]', value: SN102}}, or {combine: {add: [...]}}",
        )
        return Operand()
    keys = {k for k in ("value", "count", "sum", "combine") if k in node}
    if len(keys) != 1:
        ctx.err(path, "exactly one of 'value', 'count', 'sum', or 'combine' is required")
        return Operand()
    sum_loop = sum_value = None
    sum_expr: tuple[str, ...] = ()
    add: list[Operand] = []
    subtract: list[Operand] = []
    if "sum" in node:
        sum_node = node["sum"]
        has_value = isinstance(sum_node, dict) and isinstance(sum_node.get("value"), str)
        has_expr = isinstance(sum_node, dict) and isinstance(sum_node.get("expr"), str)
        if (
            not isinstance(sum_node, dict)
            or not isinstance(sum_node.get("loop"), str)
            or has_value == has_expr  # exactly one of value/expr
        ):
            ctx.err(
                f"{path}.sum",
                "expected {loop: 'HL[I]', value: SN102} or {loop: IT1, expr: 'IT102 * IT104'}",
            )
        else:
            sum_loop = sum_node["loop"].upper()
            if has_value:
                sum_value = sum_node["value"].upper()
            else:
                sum_expr = _parse_expr(sum_node["expr"], f"{path}.sum.expr", ctx)
            # implied may sit inside the sum block, next to the value it shifts
            if "implied" in sum_node and "implied" not in node:
                node = {**node, "implied": sum_node["implied"]}
    if "combine" in node:
        combine_node = node["combine"]
        if not isinstance(combine_node, dict) or not (
            combine_node.get("add") or combine_node.get("subtract")
        ):
            ctx.err(f"{path}.combine", "expected {add: [operands], subtract: [operands]}")
        else:
            for key, bucket in (("add", add), ("subtract", subtract)):
                for index, child in enumerate(combine_node.get(key, []) or []):
                    bucket.append(_parse_operand(child, f"{path}.combine.{key}[{index}]", ctx))
    context = node.get("context")
    if context is not None and not isinstance(context, str):
        ctx.err(f"{path}.context", "expected a Loop Context string like HL[S]")
        context = None
    if context is not None and "value" not in node:
        ctx.err(f"{path}.context", "context only applies to value operands")
        context = None
    return Operand(
        value=str(node["value"]).upper() if "value" in node else None,
        context=context.upper() if context else None,
        count=str(node["count"]).upper() if "count" in node else None,
        sum_loop=sum_loop,
        sum_value=sum_value,
        sum_expr=sum_expr,
        add=tuple(add),
        subtract=tuple(subtract),
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
    if check not in ("equals", "not_after", "not_greater"):
        ctx.err(
            f"{path}.check",
            f"unsupported check {check!r} (expected 'equals', 'not_after', or 'not_greater')",
        )
        check = "equals"
    severity = node.get("severity", "warning")
    if severity not in ("warning", "error"):
        ctx.err(f"{path}.severity", f"expected 'warning' or 'error', got {severity!r}")
    when = node.get("when")
    when_exists = when_context = None
    if when is not None:
        if isinstance(when, dict) and isinstance(when.get("exists"), str):
            when_exists = when["exists"].upper()
            raw_context = when.get("context")
            if raw_context is not None:
                if isinstance(raw_context, str):
                    when_context = raw_context.upper()
                else:
                    ctx.err(f"{path}.when.context", "expected a Loop Context string")
        else:
            ctx.err(f"{path}.when", "expected {exists: SEGnn} with optional context")
    return ReconRule(
        id=rule_id,
        left=_parse_operand(node.get("left"), f"{path}.left", ctx),
        right=_parse_operand(node.get("right"), f"{path}.right", ctx),
        check=check,
        when_exists=when_exists,
        when_context=when_context,
        severity=severity if severity in ("warning", "error") else "warning",
        description=node.get("description", "") or "",
    )


def _parse_required(node: Any, index: int, ctx: _Ctx) -> RequiredElementDef | None:
    path = f"required_elements[{index}]"
    if not isinstance(node, dict):
        ctx.err(path, "expected a mapping with segment and element")
        return None
    segment = ctx.str_at(node, path, "segment")
    element = ctx.int_at(node, path, "element")
    if not segment or element is None:
        return None
    if element < 1:
        ctx.err(f"{path}.element", "expected a 1-based element position")
        return None
    when_present = ctx.int_at(node, path, "when_present", default=None)
    if when_present is not None and when_present < 1:
        ctx.err(f"{path}.when_present", "expected a 1-based element position")
        when_present = None
    return RequiredElementDef(
        segment=segment.upper(),
        element=element,
        name=ctx.str_at(node, path, "name", required=False) or "",
        when_present=when_present,
        when_name=ctx.str_at(node, path, "when_name", required=False) or "",
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

    required: list[RequiredElementDef] = []
    required_node = data.get("required_elements", []) or []
    if not isinstance(required_node, list):
        ctx.err("required_elements", "expected a list")
        required_node = []
    for index, req_node in enumerate(required_node):
        parsed_req = _parse_required(req_node, index, ctx)
        if parsed_req:
            required.append(parsed_req)

    elements: dict[str, tuple[str, ...]] = {}
    elements_node = data.get("elements", {}) or {}
    if not isinstance(elements_node, dict):
        ctx.err("elements", "expected a mapping of segment id -> list of element names")
    else:
        for seg_id, names in elements_node.items():
            if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
                ctx.err(f"elements.{seg_id}", "expected a list of element names")
                continue
            elements[str(seg_id).upper()] = tuple(names)

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
        required_elements=tuple(required),
        elements=elements,
        source=source,
    )

    def _base_loop(reference: str) -> str:
        return reference.split("[", 1)[0]

    if pairing and definition.loop(_base_loop(pairing.loop)) is None:
        raise DefinitionError(
            source, [f"output_pairing.loop {pairing.loop!r} is not a declared loop"]
        )
    def _check_loop_refs(operand: "Operand", rule_id: str) -> None:
        for reference in (operand.count, operand.sum_loop):
            if reference and definition.loop(_base_loop(reference)) is None:
                raise DefinitionError(
                    source,
                    [
                        f"reconciliation rule {rule_id!r} references "
                        f"undeclared loop {reference!r}"
                    ],
                )
        for child in (*operand.add, *operand.subtract):
            _check_loop_refs(child, rule_id)

    for rule in recon:
        for operand in (rule.left, rule.right):
            _check_loop_refs(operand, rule.id)
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
