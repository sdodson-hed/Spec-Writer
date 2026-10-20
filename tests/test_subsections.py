"""Subsection (spt) decisions in the manifest (spec 2026-10-13, section 3)."""

import os
from pathlib import Path

import pytest

from specgen import secfile
from specgen.anchors import option_hash, section_spt_anchors
from specgen.manifest import build_manifest, location_index

SRC = (
    "<SEC><PRT><TTL>PART 1 GENERAL</TTL>"
    "<SPT><TTL>SUMMARY</TTL><TXT>x</TXT></SPT></PRT>"
    "<PRT><TTL>PART 2 PRODUCTS</TTL>"
    "<SPT><TTL>CHILLERS</TTL><TXT>a</TXT>"
    "<SPT><TTL>Scroll</TTL><TXT>s</TXT></SPT>"
    # wrapped exactly by an optional bracket: governed by that bracket
    "[<SPT><TTL>Centrifugal</TTL><TXT>c</TXT></SPT>]"
    "<TXT>between</TXT>"
    # inside larger bracketed text: not governed
    "[Text before <SPT><TTL>Screw</TTL><TXT>w</TXT></SPT>]"
    "</SPT>"
    '<TAI OPT="ARMY"><SPT><TTL>Army only</TTL><TXT>y</TXT></SPT></TAI>'
    "<SPT><TTL>NOTES</TTL><TXT>n1</TXT></SPT>"
    "<SPT><TTL>NOTES</TTL><TXT>n2</TXT></SPT>"
    "</PRT></SEC>"
)


def _subs(src=SRC):
    m = build_manifest(secfile.parse_source(src))
    return m, {s["id"]: s for s in m["subsections"]}


def test_ids_numbers_titles_and_parents():
    m, s = _subs()
    assert list(s) == [f"SPT-{i:04d}" for i in range(1, 9)]
    assert [(v["num"], v["title"]) for v in s.values()] == [
        ("1.1", "SUMMARY"), ("2.1", "CHILLERS"), ("2.1.1", "Scroll"),
        ("2.1.2", "Centrifugal"), ("2.1.3", "Screw"), ("2.2", "Army only"),
        ("2.3", "NOTES"), ("2.4", "NOTES"),
    ]
    assert s["SPT-0003"]["parent"] == "SPT-0002"
    assert s["SPT-0002"]["parent"] is None
    assert s["SPT-0003"]["depth"] == 2 and s["SPT-0002"]["depth"] == 1
    assert m["counts"]["subsections"] == 8


def test_anchors_are_pinned_and_repeat_numbered():
    _, s = _subs()
    assert s["SPT-0002"]["anchor"] == "PART 2/CHILLERS#spt:3e6c8986"
    assert s["SPT-0003"]["anchor"] == "PART 2/CHILLERS/SCROLL#spt:da4313f4"
    assert s["SPT-0007"]["anchor"] == "PART 2/NOTES#spt:e69fc18a"
    assert s["SPT-0008"]["anchor"] == "PART 2/NOTES#spt:e69fc18a~2"
    assert option_hash(["CHILLERS"]) == "3e6c8986"


def test_governed_bracketed_and_tailored():
    m, s = _subs()
    brk = {d["id"]: d for d in m["decisions"]}
    centrifugal, screw, army = s["SPT-0004"], s["SPT-0005"], s["SPT-0006"]
    assert centrifugal["governed_by"] == centrifugal["in_bracket"]
    assert brk[centrifugal["governed_by"]]["kind"] == "optional"
    assert screw["governed_by"] is None
    assert screw["in_bracket"] is not None and screw["in_bracket"] != centrifugal["in_bracket"]
    assert army["tailoring"] == "ARMY"
    assert all(v["tailoring"] is None for k, v in s.items() if k != "SPT-0006")
    assert all(s[k]["governed_by"] is None and s[k]["in_bracket"] is None
               for k in ("SPT-0001", "SPT-0002", "SPT-0003", "SPT-0006"))


def test_spans_index_source_and_text():
    m, s = _subs()
    for v in s.values():
        a, b = v["src"]
        assert SRC[a:].startswith("<SPT>") and SRC[:b].endswith("</SPT>")
        ca, cb = v["span"]
        assert m["text"][ca:cb].startswith(v["title"])
    assert m["text"][slice(*s["SPT-0002"]["span"])].startswith("CHILLERSaScroll")


def test_crlf_and_lf_give_identical_anchors():
    crlf = SRC.replace("</TXT>", "</TXT>\r\n")
    a = section_spt_anchors(secfile.parse_source(crlf))
    assert a == section_spt_anchors(secfile.parse_source(crlf.replace("\r\n", "\n")))
    assert len(a) == 8


def test_bracket_decisions_unchanged():
    m, _ = _subs()
    assert m["counts"]["bracket_groups_total"] == len(m["decisions"]) == 2


_ROOT = Path(__file__).resolve().parent.parent
_CORPUS = Path(os.environ.get("SPECGEN_CORPUS") or _ROOT / "masters")
_FILES = (
    sorted(p for p in _CORPUS.rglob("*") if p.suffix.lower() == ".sec")
    if _CORPUS.is_dir() else []
)


@pytest.mark.skipif(not _FILES, reason="corpus not present")
@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.stem)
def test_corpus_subsection_anchors_unique(path):
    sec = secfile.parse(path, tolerant=True)
    anchors = section_spt_anchors(sec)
    n = sum(1 for s in location_index(sec.root) if s.depth > 0)
    assert len(anchors) == n
    assert len(set(anchors.values())) == n
