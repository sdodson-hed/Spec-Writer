"""Subsection removal in generate (plan 2026-10-19, Tasks 3 and 4)."""

import json

from specgen import secfile
from specgen.generate import generate
from specgen.manifest import build_manifest
from tests.test_subsections import SRC

M = build_manifest(secfile.parse_source(SRC))
SUBS = {s["id"]: s for s in M["subsections"]}


def _spt(sid, answer):
    s = SUBS[sid]
    return {s["anchor"]: {"answer": answer, "id": sid, "num": s["num"], "title": s["title"]}}


def _brk(gid, answer):
    d = next(d for d in M["decisions"] if d["id"] == gid)
    return {d["anchor"]: {"answer": answer, "id": gid}}


def _gen(tmp_path, answers, profile=None, revisions=False):
    p = tmp_path / "m.SEC"
    p.write_bytes(SRC.encode(secfile.ENCODING))
    s = generate(p, profile or {}, answers, tmp_path / "o.sec", revisions=revisions)
    files = {
        "sec": (tmp_path / "o.sec").read_bytes().decode(secfile.ENCODING),
        "md": (tmp_path / "o.redline.md").read_text(encoding="utf-8"),
        "json": (tmp_path / "o.redline.json").read_text(encoding="utf-8"),
        "unresolved": (tmp_path / "o.unresolved.md").read_text(encoding="utf-8"),
    }
    if revisions:
        files["rev"] = (tmp_path / "o.revisions.sec").read_bytes().decode(secfile.ENCODING)
    changes = {c["id"]: c for c in json.loads(files["json"])["changes"]}
    for name, text in files.items():
        assert "sg-spt" not in text, f"marker leaked into {name}"
    return s, files, changes


SCREW_BRK = SUBS["SPT-0005"]["in_bracket"]       # "[Text before <SPT>Screw...]"
CENTRIFUGAL_BRK = SUBS["SPT-0004"]["governed_by"]  # "[<SPT>Centrifugal...]"


def test_remove_leaf(tmp_path):
    s, f, ch = _gen(tmp_path, _spt("SPT-0003", "remove"))
    assert "<TTL>Scroll</TTL>" not in f["sec"]
    assert "<TTL>CHILLERS</TTL>" in f["sec"] and "<TTL>Centrifugal</TTL>" in f["sec"]
    c = ch["SPT-0003"]
    assert (c["kind"], c["action"], c["source"]) == ("subsection", "removed subsection", "answer")
    assert c["num"] == "2.1.1" and c["title"] == "Scroll"
    assert s["subsections_removed"] == 1
    assert "## SPT-0003 — removed subsection 2.1.1 Scroll" in f["md"]


def test_remove_parent_ignores_child_answer_and_drops_its_brackets(tmp_path):
    s, f, ch = _gen(tmp_path, {**_spt("SPT-0002", "remove"), **_spt("SPT-0003", "keep")})
    assert "CHILLERS" not in f["sec"] and "Centrifugal" not in f["sec"]
    assert ch["SPT-0003"]["action"] == "ignored: inside removed SPT-0002"
    assert ch["SPT-0002"]["brackets_removed"] == [CENTRIFUGAL_BRK, SCREW_BRK]
    # the two brackets were unanswered but went with the subsection
    assert CENTRIFUGAL_BRK not in f["unresolved"] and SCREW_BRK not in f["unresolved"]
    assert s["unresolved"] == 0 and s["subsections_removed"] == 1


def test_answered_bracket_inside_removed_subsection_is_marked(tmp_path):
    _, f, ch = _gen(tmp_path, {**_spt("SPT-0002", "remove"), **_brk(SCREW_BRK, "keep")})
    assert ch[SCREW_BRK]["action"].endswith("(then removed with SPT-0002)")


def test_remove_inside_kept_tailoring(tmp_path):
    s, f, _ = _gen(tmp_path, _spt("SPT-0006", "remove"), profile={"ARMY": "keep"})
    assert "Army only" not in f["sec"] and '<TAI OPT="ARMY">' in f["sec"]
    assert s["subsections_removed"] == 1


def test_remove_inside_removed_tailoring_is_logged(tmp_path):
    s, _, ch = _gen(tmp_path, _spt("SPT-0006", "remove"), profile={"ARMY": "remove"})
    assert ch["SPT-0006"]["action"] == "already removed with tailoring ARMY"
    assert s["subsections_removed"] == 0


def test_keep_overridden_by_tailoring_is_logged(tmp_path):
    _, _, ch = _gen(tmp_path, _spt("SPT-0006", "keep"), profile={"ARMY": "remove"})
    assert ch["SPT-0006"]["action"] == "keep had no effect: removed with tailoring ARMY"


def test_remove_inside_deleted_bracket_is_logged(tmp_path):
    s, f, ch = _gen(tmp_path, {**_spt("SPT-0005", "remove"), **_brk(SCREW_BRK, "delete")})
    assert ch["SPT-0005"]["action"] == f"already removed with {SCREW_BRK}"
    assert "Screw" not in f["sec"] and s["subsections_removed"] == 0


def test_unanswered_subsections_are_kept_by_default_and_logged(tmp_path):
    s, f, ch = _gen(tmp_path, {})
    defaults = [c for c in ch.values() if c["kind"] == "subsection"]
    assert len(defaults) == 8
    assert {(c["action"], c["source"]) for c in defaults} == {("kept by default", "default")}
    assert s["subsections_kept_default"] == 8
    assert "8 subsections kept by default (no answer)" in f["md"]
    assert f["sec"] == SRC  # nothing answered, nothing changed


def test_explicit_keep_is_logged_as_answer(tmp_path):
    _, _, ch = _gen(tmp_path, _spt("SPT-0007", "keep"))
    assert (ch["SPT-0007"]["action"], ch["SPT-0007"]["source"]) == ("kept", "answer")


def test_repeated_titles_remove_only_the_answered_one(tmp_path):
    _, f, _ = _gen(tmp_path, _spt("SPT-0008", "remove"))
    assert "<TXT>n1</TXT>" in f["sec"] and "<TXT>n2</TXT>" not in f["sec"]


# --- revisions (Task 4) ------------------------------------------------------

def test_revisions_wrap_removed_subsection_in_del(tmp_path):
    _, f, _ = _gen(tmp_path, _spt("SPT-0003", "remove"), revisions=True)
    assert "<DEL><SPT><TTL>Scroll</TTL><TXT>s</TXT></SPT></DEL>" in f["rev"]
    # generate itself verifies resolve(rev) == sec and revert(rev) == master


def test_revisions_parent_only_wrapped_once(tmp_path):
    _, f, _ = _gen(tmp_path, {**_spt("SPT-0002", "remove"), **_spt("SPT-0003", "remove")},
                   revisions=True)
    assert f["rev"].count("<DEL><SPT><TTL>CHILLERS") == 1
    assert "<DEL><SPT><TTL>Scroll" not in f["rev"]


def test_revisions_no_double_wrap_inside_deleted_bracket(tmp_path):
    _, f, _ = _gen(tmp_path, {**_spt("SPT-0005", "remove"), **_brk(SCREW_BRK, "delete")},
                   revisions=True)
    assert f["rev"].count("<TTL>Screw</TTL>") == 1
    assert "<DEL><SPT><TTL>Screw" not in f["rev"]


def test_revisions_inside_kept_tailoring(tmp_path):
    _, f, _ = _gen(tmp_path, _spt("SPT-0006", "remove"), profile={"ARMY": "keep"},
                   revisions=True)
    assert '<TAI OPT="ARMY"><DEL><SPT><TTL>Army only' in f["rev"]
