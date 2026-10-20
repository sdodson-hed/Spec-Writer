"""Removal cleanup applied by generate (plan 2026-10-20, Task 3)."""

import json

from specgen import secfile
from specgen.generate import generate
from specgen.manifest import build_manifest
from tests.test_cleanup_manifest import SRC
from tests.test_cleanup_plan import HEAD


def _remove(src, *titles):
    m = build_manifest(secfile.parse_source(src))
    return m, {
        s["anchor"]: {"answer": "remove", "id": s["id"]}
        for s in m["subsections"] if s["title"] in titles
    }


def _gen(tmp_path, src, answers, profile=None, revisions=True):
    p = tmp_path / "m.SEC"
    p.write_bytes(src.encode(secfile.ENCODING))
    s = generate(p, profile or {}, answers, tmp_path / "o.sec", revisions=revisions)
    f = {
        "sec": (tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING),
        "md": (tmp_path / "o.redline.md").read_text(encoding="utf-8"),
        "json": (tmp_path / "o.redline.json").read_text(encoding="utf-8"),
        "unresolved": (tmp_path / "o.unresolved.md").read_text(encoding="utf-8"),
    }
    if revisions:
        f["rev"] = (tmp_path / "o.revisions.sec").read_bytes().decode(secfile.ENCODING)
    for name, text in f.items():
        assert "sg-cln" not in text and "sg-spt" not in text, name
    changes = json.loads(f["json"])["changes"]
    return s, f, {(c["kind"], c["name"]): c for c in changes if "name" in c}


def test_engine_removal_cleans_up(tmp_path):
    m, answers = _remove(SRC, "ENGINE")
    engine = next(s["id"] for s in m["subsections"] if s["title"] == "ENGINE")
    s, f, ch = _gen(tmp_path, SRC, answers)
    out = f["sec"]
    assert "<SUB>Gas Engine</SUB>" not in out
    assert "<RID>AHRI 450</RID>" not in out and "<RID>AHRI 550/590</RID>" in out
    assert "<ORG>NFPA</ORG>" not in out
    assert "<ITM><SUB>Scroll Chiller</SUB></ITM>" in out        # used elsewhere
    assert "[<ITM><SUB>Field Test Plan</SUB></ITM>" in out       # blocked (D1)
    assert "<ITM><SUB>Never Used</SUB></ITM>" in out             # never used
    # spacing after a removed item goes with it: no doubled blank lines
    assert "<ITM><SUB>Scroll Chiller</SUB></ITM><BRK/>\r\n<BRK/>\r\n[<ITM>" in out

    gas = ch[("submittal-item", "Gas Engine")]
    assert gas["action"] == f"removed: its only uses were in {engine}"
    assert gas["reviewer"] == "G, [_____]" and gas["source"] == {"kind": "cleanup"}
    assert ch[("reference-org", "NFPA")]["rids"] == ["NFPA 37"]
    assert ch[("reference", "AHRI 450")]["caused_by"] == [engine]
    blocked = ch[("submittal-item", "Field Test Plan")]
    assert blocked["action"].startswith("kept: inside BRK-")

    assert (s["submittal_items_removed"], s["references_removed"],
            s["reference_orgs_removed"], s["sd_headings_removed"]) == (1, 2, 1, 0)
    assert s["section_refs_dropped"] == ["22 00 00"]
    assert "Field Test Plan" in f["unresolved"]
    assert f"its only references were removed with {engine}; consider delete" in f["unresolved"]
    num = next(x["num"] for x in m["subsections"] if x["id"] == engine)
    assert "## Cleanup" in f["md"]
    assert f"- Submittal item Gas Engine (reviewer G, [_____]): removed, only used in {num}" in f["md"]
    # listed in document order (in this fixture REFERENCES precedes SUBMITTALS)
    md = f["md"].split("## Cleanup", 1)[1]
    assert md.index("AHRI 450") < md.index("NFPA") < md.index("Gas Engine")


def test_revisions_carry_cleanup_as_del(tmp_path):
    _, answers = _remove(SRC, "ENGINE")
    _, f, _ = _gen(tmp_path, SRC, answers)
    assert "<DEL><ITM><SUB>Gas Engine</SUB>" in f["rev"]
    assert "<DEL><REF><ORG>NFPA</ORG>" in f["rev"]
    assert "<DEL><RID>AHRI 450</RID>" in f["rev"]
    # generate itself verifies resolve(rev) == sec and revert(rev) == master


def _field_test_brk(m):
    e = next(x for x in m["submittal_entries"] if x["name"] == "Field Test Plan")
    return next(d for d in m["decisions"] if d["id"] == e["in_bracket"])


def test_blocked_item_answered_keep_is_logged_not_reported(tmp_path):
    m, answers = _remove(SRC, "ENGINE")
    d = _field_test_brk(m)
    answers[d["anchor"]] = {"answer": "keep", "id": d["id"]}
    _, f, ch = _gen(tmp_path, SRC, answers)
    assert ch[("submittal-item", "Field Test Plan")]["action"] == (
        f"kept by answer on {d['id']} although its only references were removed")
    assert "Field Test Plan" not in f["unresolved"]


def test_blocked_item_answered_delete_needs_nothing(tmp_path):
    m, answers = _remove(SRC, "ENGINE")
    d = _field_test_brk(m)
    answers[d["anchor"]] = {"answer": "delete", "id": d["id"]}
    _, f, ch = _gen(tmp_path, SRC, answers)
    assert "Field Test Plan" not in f["sec"] and "Field Test Plan" not in f["unresolved"]
    assert ("submittal-item", "Field Test Plan") not in ch


def test_item_already_removed_by_tailoring(tmp_path):
    src = SRC.replace("<ITM><SUB>Gas Engine</SUB>", '<TAI OPT="ARMY"><ITM><SUB>Gas Engine</SUB>').replace(
        "<SUB>G, [_____]</SUB></ITM>", "<SUB>G, [_____]</SUB></ITM></TAI>")
    _, answers = _remove(src, "ENGINE")
    s, _, ch = _gen(tmp_path, src, answers, profile={"ARMY": "remove"})
    assert ch[("submittal-item", "Gas Engine")]["action"] == "already removed (bracket or tailoring)"
    assert s["submittal_items_removed"] == 0


def test_emptied_heading_removed(tmp_path):
    _, answers = _remove(HEAD, "ENGINE")
    s, f, ch = _gen(tmp_path, HEAD, answers)
    assert "SD-06 Test Reports" not in f["sec"] and "SD-03 Product Data" in f["sec"]
    assert ("sd-heading", "SD-06 Test Reports") in ch
    assert (s["submittal_items_removed"], s["sd_headings_removed"]) == (2, 1)


def test_no_removals_means_no_cleanup(tmp_path):
    s, f, _ = _gen(tmp_path, SRC, {}, revisions=False)
    assert f["sec"] == SRC
    assert (s["submittal_items_removed"], s["references_removed"]) == (0, 0)
    assert "## Cleanup" not in f["md"]
