"""Structured conditions for section annotations (spec 2026-10-13, section 5).

No expression strings and no eval: a condition is a YAML mapping.

    top level   {any_equipment: S} | {all_equipment: S} | {bod: S}
                | {project: S} | {all: [C, ...]} | {any: [C, ...]} | {not: C}
    scope S     {field: M, ...}      every entry must hold
                (may also use all / any / not over scope mappings)
    matcher M   scalar               equal (strings: case-insensitive)
                {in: [v, ...]} | {equals: v}

Evaluation is three-valued: True, False, or None (unknown). A field that is
absent is unknown, never false, and the result names it ("bod.x",
"ACC-1.compressor_type"), so prefill can leave the decision unresolved and
say why. all/any/not follow Kleene logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_COMBINATORS = ("all", "any", "not")
_SCOPES = ("any_equipment", "all_equipment", "bod", "project")
_UNKNOWN = "__unknown__"  # derived facts that could not be computed, with why


class ConditionError(Exception):
    pass


@dataclass
class Context:
    rows: list[dict]  # equipment rows this annotation applies to (derived facts added)
    bod: dict
    project: dict
    schedule: str = ""


@dataclass
class Result:
    value: bool | None
    missing: list[str] = field(default_factory=list)


# --- validation --------------------------------------------------------------

def _scalar(v) -> bool:
    return isinstance(v, (str, int, float, bool))


def _validate_matcher(path: str, m) -> None:
    if _scalar(m):
        return
    if isinstance(m, dict) and len(m) == 1:
        (op, v), = m.items()
        if op == "in" and isinstance(v, list) and v and all(_scalar(x) for x in v):
            return
        if op == "equals" and _scalar(v):
            return
    raise ConditionError(f"{path}: matcher must be a value, {{in: [...]}} or {{equals: v}} (got {m!r})")


def _validate_scope(path: str, s) -> None:
    if not isinstance(s, dict) or not s:
        raise ConditionError(f"{path}: expected a mapping of field: value (got {s!r})")
    for k, v in s.items():
        if k in ("all", "any"):
            if not isinstance(v, list) or not v:
                raise ConditionError(f"{path}.{k}: expects a non-empty list")
            for i, x in enumerate(v):
                _validate_scope(f"{path}.{k}[{i}]", x)
        elif k == "not":
            _validate_scope(f"{path}.not", v)
        else:
            _validate_matcher(f"{path}.{k}", v)


def validate(cond, path: str = "condition") -> None:
    if not isinstance(cond, dict) or len(cond) != 1:
        raise ConditionError(
            f"{path}: a condition is a mapping with exactly one of "
            f"{', '.join(_SCOPES + _COMBINATORS)} (got {cond!r})"
        )
    (op, arg), = cond.items()
    if op in ("all", "any"):
        if not isinstance(arg, list) or not arg:
            raise ConditionError(f"{path}.{op}: expects a non-empty list of conditions")
        for i, c in enumerate(arg):
            validate(c, f"{path}.{op}[{i}]")
    elif op == "not":
        validate(arg, f"{path}.not")
    elif op in _SCOPES:
        _validate_scope(f"{path}.{op}", arg)
    else:
        raise ConditionError(
            f"{path}: unknown operator {op!r}; a field needs a scope "
            f"({', '.join(_SCOPES)})"
        )


# --- evaluation --------------------------------------------------------------

def _eq(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return False


def _match(value, m) -> bool:
    if isinstance(m, dict):
        (op, v), = m.items()
        return any(_eq(value, x) for x in v) if op == "in" else _eq(value, v)
    return _eq(value, m)


def _and(results: list[Result]) -> Result:
    if any(r.value is False for r in results):
        return Result(False)
    unknown = [r for r in results if r.value is None]
    if unknown:
        return Result(None, sorted({m for r in unknown for m in r.missing}))
    return Result(True)


def _or(results: list[Result]) -> Result:
    if any(r.value is True for r in results):
        return Result(True)
    unknown = [r for r in results if r.value is None]
    if unknown:
        return Result(None, sorted({m for r in unknown for m in r.missing}))
    return Result(False)


def _not(r: Result) -> Result:
    return Result(None if r.value is None else not r.value, r.missing)


def _scope(s: dict, obj: dict, label: str) -> Result:
    parts = []
    for k, v in s.items():
        if k == "all":
            parts.append(_and([_scope(x, obj, label) for x in v]))
        elif k == "any":
            parts.append(_or([_scope(x, obj, label) for x in v]))
        elif k == "not":
            parts.append(_not(_scope(v, obj, label)))
        elif k in obj:
            parts.append(Result(_match(obj[k], v)))
        else:
            why = obj.get(_UNKNOWN, {}).get(k, f"{label}.{k}")
            parts.append(Result(None, [why]))
    return _and(parts)


def evaluate(cond: dict, ctx: Context) -> Result:
    (op, arg), = cond.items()
    if op == "all":
        return _and([evaluate(c, ctx) for c in arg])
    if op == "any":
        return _or([evaluate(c, ctx) for c in arg])
    if op == "not":
        return _not(evaluate(arg, ctx))
    if op == "bod":
        return _scope(arg, ctx.bod, "bod")
    if op == "project":
        return _scope(arg, ctx.project, "project")
    if not ctx.rows:
        return Result(None, [f"{ctx.schedule} rows"])
    per_row = [_scope(arg, r, r.get("mark", f"row{i}")) for i, r in enumerate(ctx.rows)]
    return _or(per_row) if op == "any_equipment" else _and(per_row)


# --- derived facts -----------------------------------------------------------

def derive_rows(rows: list[dict], derive: dict | None) -> list[dict]:
    """Copies of `rows` with each derived fact added. derive entries are
    {from: field, map: {value: fact}} or {value: fact}. A source value that
    is absent or not in the map leaves the fact unknown (recorded with the
    reason), never defaulted."""
    out = []
    for r in rows:
        row = dict(r)
        unknown: dict[str, str] = {}
        label = row.get("mark", "row")
        for name, spec in (derive or {}).items():
            if "value" in spec:
                row[name] = spec["value"]
                continue
            src = spec["from"]
            if src not in row:
                unknown[name] = f"{label}.{src}"
                continue
            hit = next((v for k, v in spec["map"].items() if _eq(row[src], k)), None)
            if hit is None:
                unknown[name] = f"{label}.{src}={row[src]!r} (not in derive.{name} map)"
            else:
                row[name] = hit
        if unknown:
            row[_UNKNOWN] = unknown
        out.append(row)
    return out


def validate_derive(derive, path: str = "derive") -> None:
    if derive is None:
        return
    if not isinstance(derive, dict):
        raise ConditionError(f"{path}: expected a mapping of fact name to rule")
    for name, spec in derive.items():
        ok = isinstance(spec, dict) and (
            (set(spec) == {"value"} and _scalar(spec["value"]))
            or (set(spec) == {"from", "map"} and isinstance(spec["from"], str)
                and isinstance(spec["map"], dict) and spec["map"])
        )
        if not ok:
            raise ConditionError(f"{path}.{name}: expected {{from: field, map: {{...}}}} or {{value: v}}")
