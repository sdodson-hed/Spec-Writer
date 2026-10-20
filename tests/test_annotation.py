"""Section annotations: schema and target resolution (plan 2026-10-20, Task 3).

MINI is a small chiller section built like 23 64 10 (choices in a subsection
title, a driver choice, blanks, removable subsections, an optional bracket,
agency tailoring, a unit pair). ANNOTATION is the annotation prefill tests
reuse."""

import pytest
import yaml

from specgen import secfile
from specgen.annotation import AnnotationError, check_targets, from_dict, resolve_targets
from specgen.cli import main
from specgen.manifest import build_manifest

MINI = (
    "<SEC><SCN>SECTION 23 64 99</SCN><STL>MINI CHILLERS</STL>"
    "<PRT><TTL>PART 1 GENERAL</TTL>"
    "<SPT><TTL>SUMMARY</TTL><TXT>Rated at <MET>352 kW</MET><ENG>100 tons</ENG>.</TXT>"
    '<TAI OPT="ARMY"><TXT>Army reviewer.</TXT></TAI>'
    '<TAI OPT="AIR FORCE"><TXT>Air Force reviewer.</TXT></TAI></SPT></PRT>'
    "<PRT><TTL>PART 2 PRODUCTS</TTL>"
    "<SPT><TTL>WATER CHILLERS</TTL>"
    "<SPT><TTL>[Scroll][Screw][Centrifugal] Type Chiller</TTL>"
    "<TXT>Compressor driver: [electric motor][gas-engine].</TXT>"
    "<TXT>Refrigerant [_____].</TXT></SPT>"
    "<SPT><TTL>Centrifugal Type Chiller</TTL><TXT>Centrifugal text.</TXT></SPT>"
    "</SPT>"
    "<SPT><TTL>COMPONENTS</TTL>"
    "<SPT><TTL>Compressor Driver, Gas-Engine</TTL><TXT>Engine [_____] text.</TXT></SPT>"
    "<SPT><TTL>Heat Recovery Condenser Coil</TTL><TXT>Heat recovery text.</TXT></SPT>"
    "<TXT>[Provide a factory sound test.]</TXT>"
    "<TXT>Capacity [_____] kW at [_____] degrees F.</TXT>"
    "</SPT></PRT></SEC>"
)

ANNOTATION = """
section: "23 64 99"
applies_to:
  schedule: air_cooled_chiller
derive:
  condenser:
    from: type
    map: {"AIR-COOLED SCROLL": air-cooled, "WATER-COOLED CENTRIFUGAL": water-cooled}
  driver: {value: electric motor}
rules:
  - id: compressor-type
    target: {path: "PART 2/WATER CHILLERS/*TYPE CHILLER", kind: choice,
             options: [Scroll, Screw, Centrifugal]}
    choose: {match: "{compressor_type}"}
  - id: driver
    target: {path: "PART 2/WATER CHILLERS/*TYPE CHILLER", kind: choice,
             options: [electric motor, gas-engine]}
    choose: {match: "{driver}"}
  - id: no-centrifugal
    target: {path: "PART 2/WATER CHILLERS/CENTRIFUGAL TYPE CHILLER", kind: spt}
    remove_unless: {any_equipment: {compressor_type: CENTRIFUGAL}}
  - id: no-gas-engine
    target: {path: "PART 2/COMPONENTS/COMPRESSOR DRIVER, GAS-ENGINE", kind: spt}
    remove_unless: {any_equipment: {driver: gas-engine}}
  - id: refrigerant
    target: {path: "PART 2/WATER CHILLERS/*TYPE CHILLER", kind: blank}
    fill: "{refrigerant}"
  - id: heat-recovery
    target: {path: "PART 2/COMPONENTS/HEAT RECOVERY CONDENSER COIL", kind: spt}
    remove_unless: {bod: {heat_recovery: true}}
    requires: [bod.heat_recovery]
  - id: sound-test
    target: {path: "PART 2/COMPONENTS", kind: optional}
    remove_unless: {bod: {sound_test: true}}
  - id: capacity
    target: {path: "PART 2/COMPONENTS", kind: blank, nth: 1}
    fill: "{capacity_mbh}"
  - id: engine-hp
    target: {path: "PART 2/COMPONENTS/COMPRESSOR DRIVER, GAS-ENGINE", kind: blank}
    fill: "{engine_hp}"
"""


def _m():
    return build_manifest(secfile.parse_source(MINI))


def _ann(text=ANNOTATION):
    return from_dict(yaml.safe_load(text))


def test_fixture_annotation_resolves_every_rule_once():
    m = _m()
    hits = resolve_targets(_ann(), m)
    ids = {rid: [h["id"] for h in hs] for rid, hs in hits.items()}
    assert all(len(v) == 1 for v in ids.values()), ids
    opts = {d["id"]: d["options"] for d in m["decisions"]}
    assert opts[ids["compressor-type"][0]] == ["Scroll", "Screw", "Centrifugal"]
    assert opts[ids["driver"][0]] == ["electric motor", "gas-engine"]
    subs = {s["id"]: s["title"] for s in m["subsections"]}
    assert subs[ids["no-gas-engine"][0]] == "Compressor Driver, Gas-Engine"
    assert check_targets(_ann(), m) == []


def test_ambiguous_target_without_options_or_nth():
    ann = _ann(ANNOTATION.replace(
        "options: [electric motor, gas-engine]}", "}"))
    problems = check_targets(ann, _m())
    assert len(problems) == 1
    assert problems[0].startswith("driver: 2 matches")


def test_nth_picks_in_document_order():
    m = _m()
    first = resolve_targets(_ann(), m)["capacity"]
    second = resolve_targets(_ann(ANNOTATION.replace("nth: 1", "nth: 2")), m)["capacity"]
    assert first[0]["offset"] < second[0]["offset"]
    assert check_targets(_ann(ANNOTATION.replace("nth: 1", "nth: 3")), m) == [
        "capacity: nth 3 but only 2 matches"]


def test_zero_matches_reported():
    ann = _ann(ANNOTATION.replace("HEAT RECOVERY CONDENSER COIL", "HEAT RECOVERY COIL"))
    assert check_targets(ann, _m()) == [
        "heat-recovery: 0 matches for spt at 'PART 2/COMPONENTS/HEAT RECOVERY COIL'"]


def test_section_mismatch():
    ann = _ann(ANNOTATION.replace('"23 64 99"', '"23 64 10"'))
    assert check_targets(ann, _m()) == [
        "annotation is for section 23 64 10, master is 23 64 99"]


@pytest.mark.parametrize("edit, message", [
    (lambda d: d.update(bogus=1), "unknown key 'bogus'"),
    (lambda d: d["rules"][0].update(fill="x"), "compressor-type: exactly one of choose, fill, remove_unless"),
    (lambda d: d["rules"][0].pop("target"), "compressor-type: target is required"),
    (lambda d: d["rules"][0]["target"].update(kind="maybe"), "compressor-type: target.kind must be one of"),
    (lambda d: d["rules"][4].update(fill=None, choose={"match": "x"}) or d["rules"][4].pop("fill"),
     "refrigerant: choose needs kind choice"),
    (lambda d: d["rules"][2].update(remove_unless="compressor_type == 'CENTRIFUGAL'"),
     "no-centrifugal.remove_unless"),
    (lambda d: d["rules"].append(dict(d["rules"][0])), "duplicate rule id 'compressor-type'"),
    (lambda d: d["rules"][5].update(requires=["heat_recovery_flag"]),
     "heat-recovery: requires entries are bod.<field>, project.<field> or equipment.<field>"),
    (lambda d: d.update(profile={"ARMY": "maybe"}), "profile.ARMY must be keep, remove, si or ip"),
])
def test_schema_errors(edit, message):
    d = yaml.safe_load(ANNOTATION)
    edit(d)
    with pytest.raises(AnnotationError) as e:
        from_dict(d)
    assert message in str(e.value)


def test_annotate_check_cli(tmp_path, capsys):
    master = tmp_path / "m.SEC"
    master.write_bytes(MINI.encode(secfile.ENCODING))
    good = tmp_path / "good.yaml"
    good.write_text(ANNOTATION, encoding="utf-8")
    assert main(["annotate-check", str(master), "--annotation", str(good)]) == 0
    out = capsys.readouterr().out
    assert "OK   compressor-type -> BRK-" in out and "9 rules, 0 problems" in out
    bad = tmp_path / "bad.yaml"
    bad.write_text(ANNOTATION.replace("HEAT RECOVERY CONDENSER COIL", "NOPE"), encoding="utf-8")
    assert main(["annotate-check", str(master), "--annotation", str(bad)]) == 1
    assert "FAIL heat-recovery: 0 matches" in capsys.readouterr().out
