"""Structured conditions, three-valued (plan 2026-10-20, Task 2).

Unknown (None) is never false: a rule whose condition is unknown leaves its
decision unresolved, naming the missing fields."""

import pytest

from specgen.conditions import (
    ConditionError,
    Context,
    derive_rows,
    evaluate,
    validate,
    validate_derive,
)

ACC1 = {"mark": "ACC-1", "type": "AIR-COOLED SCROLL", "compressor_type": "SCROLL", "volts": 208}
ACC2 = {"mark": "ACC-2", "type": "WATER-COOLED CENTRIFUGAL", "compressor_type": "CENTRIFUGAL"}


def ctx(*rows, bod=None, project=None):
    return Context(rows=list(rows), bod=bod or {}, project=project or {"agency": "AIR FORCE"},
                   schedule="air_cooled_chiller")


def ev(cond, c):
    validate(cond)
    return evaluate(cond, c)


# --- leaves and scopes -------------------------------------------------------

def test_equality_is_case_insensitive_for_strings():
    assert ev({"any_equipment": {"compressor_type": "scroll"}}, ctx(ACC1)).value is True
    assert ev({"any_equipment": {"compressor_type": "SCREW"}}, ctx(ACC1)).value is False
    assert ev({"any_equipment": {"volts": 208}}, ctx(ACC1)).value is True
    assert ev({"any_equipment": {"volts": "208"}}, ctx(ACC1)).value is False  # no type coercion


def test_in_and_equals():
    assert ev({"any_equipment": {"compressor_type": {"in": ["SCREW", "Scroll"]}}}, ctx(ACC1)).value is True
    assert ev({"project": {"agency": {"equals": "air force"}}}, ctx(ACC1)).value is True


def test_bod_and_project_scopes():
    c = ctx(ACC1, bod={"heat_recovery": True})
    assert ev({"bod": {"heat_recovery": True}}, c).value is True
    assert ev({"project": {"agency": "NAVY"}}, c).value is False


def test_missing_field_is_unknown_and_named():
    r = ev({"bod": {"heat_recovery": True}}, ctx(ACC1))
    assert r.value is None and r.missing == ["bod.heat_recovery"]
    r = ev({"any_equipment": {"refrigerant": "R-454B"}}, ctx(ACC1))
    assert r.value is None and r.missing == ["ACC-1.refrigerant"]


def test_multiple_fields_in_one_scope_all_must_hold():
    c = ctx(ACC1)
    assert ev({"any_equipment": {"compressor_type": "SCROLL", "volts": 208}}, c).value is True
    assert ev({"any_equipment": {"compressor_type": "SCROLL", "volts": 480}}, c).value is False


# --- equipment rows ----------------------------------------------------------

def test_any_equipment_over_rows():
    c = ctx(ACC1, ACC2)
    assert ev({"any_equipment": {"compressor_type": "CENTRIFUGAL"}}, c).value is True
    assert ev({"all_equipment": {"compressor_type": "SCROLL"}}, c).value is False
    # remove_unless semantics: content is removed only when NO row needs it
    assert ev({"any_equipment": {"compressor_type": "SCREW"}}, c).value is False


def test_any_equipment_with_an_unknown_row():
    no_type = {"mark": "ACC-3"}
    # one row is true: true regardless of the unknown one
    assert ev({"any_equipment": {"compressor_type": "SCROLL"}}, ctx(ACC1, no_type)).value is True
    # no row true, one unknown: unknown, naming it
    r = ev({"any_equipment": {"compressor_type": "SCREW"}}, ctx(ACC1, no_type))
    assert r.value is None and r.missing == ["ACC-3.compressor_type"]


def test_no_rows_is_unknown_not_false():
    r = ev({"any_equipment": {"compressor_type": "SCROLL"}}, ctx())
    assert r.value is None and r.missing == ["air_cooled_chiller rows"]


# --- combinators (Kleene) ----------------------------------------------------

T = {"project": {"agency": "AIR FORCE"}}
F = {"project": {"agency": "NAVY"}}
U = {"bod": {"x": 1}}


@pytest.mark.parametrize("cond, want", [
    ({"all": [T, T]}, True), ({"all": [T, F]}, False), ({"all": [T, U]}, None), ({"all": [F, U]}, False),
    ({"any": [F, F]}, False), ({"any": [F, T]}, True), ({"any": [F, U]}, None), ({"any": [T, U]}, True),
    ({"not": T}, False), ({"not": F}, True), ({"not": U}, None),
])
def test_kleene(cond, want):
    r = ev(cond, ctx(ACC1))
    assert r.value is want
    assert (r.missing == ["bod.x"]) == (want is None)


def test_combinators_inside_a_scope():
    cond = {"any_equipment": {"any": [{"compressor_type": "SCREW"}, {"compressor_type": "SCROLL"}]}}
    assert ev(cond, ctx(ACC1)).value is True


# --- derived facts -----------------------------------------------------------

DERIVE = {
    "condenser": {"from": "type", "map": {"AIR-COOLED SCROLL": "air-cooled",
                                          "WATER-COOLED CENTRIFUGAL": "water-cooled"}},
    "driver": {"value": "electric"},
}


def test_derived_facts():
    rows = derive_rows([ACC1, ACC2], DERIVE)
    assert [r["condenser"] for r in rows] == ["air-cooled", "water-cooled"]
    assert all(r["driver"] == "electric" for r in rows)
    assert ACC1.get("condenser") is None  # inputs untouched
    c = Context(rows=rows, bod={}, project={}, schedule="s")
    assert evaluate({"any_equipment": {"driver": "gas-engine"}}, c).value is False


def test_derived_value_not_in_map_is_unknown_never_default():
    odd = {"mark": "ACC-9", "type": "ABSORPTION"}
    rows = derive_rows([odd], DERIVE)
    assert "condenser" not in rows[0]
    r = evaluate({"any_equipment": {"condenser": "air-cooled"}},
                 Context(rows=rows, bod={}, project={}, schedule="s"))
    assert r.value is None
    assert r.missing == ["ACC-9.type='ABSORPTION' (not in derive.condenser map)"]


def test_derived_from_missing_field():
    rows = derive_rows([{"mark": "ACC-4"}], DERIVE)
    r = evaluate({"any_equipment": {"condenser": "air-cooled"}},
                 Context(rows=rows, bod={}, project={}, schedule="s"))
    assert r.missing == ["ACC-4.type"]


# --- validation: no expression strings, no unknown operators -----------------

@pytest.mark.parametrize("bad", [
    "compressor_type == 'SCROLL'",                        # expression strings are not conditions
    {"compressor_type": "SCROLL"},                        # a field needs a scope
    {"any_equipment": {"compressor_type": {"like": "S%"}}},  # unknown matcher
    {"all": T},                                           # all/any take a list
    {"bod": {"x": 1}, "project": {"y": 2}},               # one operator per mapping at top level
    {"not": [T]},
])
def test_invalid_conditions_rejected(bad):
    with pytest.raises(ConditionError):
        validate(bad)


def test_derive_validation():
    validate_derive(DERIVE)
    for bad in ({"x": {"from": "type"}}, {"x": {"value": "a", "from": "b"}},
                {"x": {"from": "type", "map": {}}}, ["not", "a", "mapping"]):
        with pytest.raises(ConditionError):
            validate_derive(bad)
