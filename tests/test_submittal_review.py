from pathlib import Path

from specgen import secfile
from specgen.answers import read_answers_json
from specgen.generate import generate
from specgen.manifest import build_manifest
from specgen.scan import scan_groups

SUBREV = (
    "<SEC><SPT><TTL>SUBMITTALS</TTL>"
    "<SUB>SD-03 Product Data</SUB><BRK/>"
    "<SUB>Controls</SUB>"
    '[; <SUB>G<TAI OPT="ARMY">, [_____]</TAI></SUB>]<BRK/>'
    "</SPT></SEC>"
)


def test_recognizer():
    groups, _, _ = scan_groups(SUBREV)
    subrev = [g for g in groups if g.kind == "submittal-review"]
    assert len(subrev) == 1
    assert subrev[0].safe


def test_generate_keep_with_office(tmp_path):
    master = tmp_path / "t.SEC"
    master.write_bytes(SUBREV.encode(secfile.ENCODING))
    groups, _, _ = scan_groups(SUBREV)
    gid = next(g.gid for g in groups if g.kind == "submittal-review")
    out = tmp_path / "out.sec"
    generate(master, {}, {gid: {"answer": "keep", "office": "AE", "notes": ""}}, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "; <SUB>G" in result and ", AE" in result
    assert "[_____]" not in result


def test_manifest_seeds_legacy_kind_counts_and_label():
    # Fixture contains ONLY a submittal-review group: the legacy kind_*
    # counts consumed by cli.cmd_report must still be present (zeroed).
    sec = secfile.parse_source(SUBREV)
    m = build_manifest(sec)
    c = m["counts"]
    assert c["kind_choice"] == 0
    assert c["kind_blank"] == 0
    assert c["kind_optional"] == 0
    assert c["kind_submittal-review"] == 1
    d = next(d for d in m["decisions"] if d["kind"] == "submittal-review")
    assert d["label"] == "Controls"


def test_json_office_passthrough(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        '{"answers": {"BRK-0001": {"answer": "keep", "office": "AE"}}}',
        encoding="utf-8",
    )
    _, answers = read_answers_json(p)
    assert answers["BRK-0001"]["office"] == "AE"
