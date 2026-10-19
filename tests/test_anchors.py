"""Stable anchors (spec 2026-10-13, section 2): <path>#<kind>:<hash8>[~n]."""

import os
from pathlib import Path

import pytest

from specgen import secfile
from specgen.anchors import norm_title, option_hash, section_anchors
from specgen.scan import scan_groups

SRC = (
    "<SEC><HDR><TXT>Header [_____]</TXT></HDR>"
    "<PRT><TTL>PART 1 GENERAL</TTL><SPT><TTL>SUMMARY</TTL><TXT>x</TXT></SPT></PRT>"
    "<PRT><TTL>PART 2 PRODUCTS</TTL>"
    "<SPT><TTL>SCROLL[, RECIPROCATING] TYPE CHILLERS</TTL>"
    "<TXT>Provide [scroll][screw] compressors.</TXT>"
    "<TXT>Refrigerant [_____].</TXT>"
    "<TXT>Again [scroll][screw].</TXT></SPT>"
    "<SPT><TTL>CHILLED/HOT WATER</TTL><TXT>Unit[s] here.</TXT></SPT>"
    "</PRT></SEC>"
)


def _anchors(src):
    return section_anchors(secfile.parse_source(src))


def test_hash_values_are_pinned():
    # changing normalization silently orphans every saved answer: pin it
    assert option_hash(["scroll", "screw"]) == "e37dc8c8"
    assert option_hash(["  scroll\r\n", "screw "]) == "e37dc8c8"
    assert option_hash(["_____"]) == "2477bc03"


def test_anchor_shapes():
    a = _anchors(SRC)
    p = "PART 2/SCROLL, RECIPROCATING TYPE CHILLERS"
    assert a["BRK-0001"] == "(HEADER)#blank:2477bc03"
    assert a["BRK-0002"] == f"{p}#optional:" + option_hash([", RECIPROCATING"])
    assert a["BRK-0003"] == f"{p}#choice:e37dc8c8"
    assert a["BRK-0004"] == f"{p}#blank:2477bc03"
    assert a["BRK-0005"] == f"{p}#choice:e37dc8c8~2"
    assert a["BRK-0006"] == "PART 2/CHILLED%2FHOT WATER#plural:" + option_hash(["s"])


def test_crlf_and_lf_give_identical_anchors():
    crlf = SRC.replace("</TXT>", "</TXT>\r\n")
    assert _anchors(crlf) == _anchors(crlf.replace("\r\n", "\n"))


def test_stable_when_unrelated_group_inserted_earlier():
    before = _anchors(SRC)
    after = _anchors(SRC.replace("<TXT>x</TXT>", "<TXT>x [new][option]</TXT>"))
    assert set(before.values()) <= set(after.values())
    assert before["BRK-0003"] == after["BRK-0004"]  # id moved, anchor did not


def test_submittal_review_kind():
    src = ("<SEC><PRT><TTL>PART 1</TTL><SPT><TTL>SUBMITTALS</TTL>"
           "<TXT><SUB>Chiller</SUB>[; <SUB>G, [_____]</SUB>]</TXT></SPT></PRT></SEC>")
    [a] = _anchors(src).values()
    assert a.startswith("PART 1/SUBMITTALS#submittal-review:")


def test_norm_title():
    assert norm_title(" chilled/hot  [water] ") == "CHILLED%2FHOT WATER"


_ROOT = Path(__file__).resolve().parent.parent
_CORPUS = Path(os.environ.get("SPECGEN_CORPUS") or _ROOT / "masters")
_FILES = (
    sorted(p for p in _CORPUS.rglob("*") if p.suffix.lower() == ".sec")
    if _CORPUS.is_dir() else []
)


@pytest.mark.skipif(not _FILES, reason="corpus not present")
@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.stem)
def test_corpus_anchors_unique_and_eol_stable(path):
    sec = secfile.parse(path, tolerant=True)
    anchors = section_anchors(sec)
    assert len(anchors) == len(scan_groups(sec.source)[0])
    assert len(set(anchors.values())) == len(anchors)
    lf = sec.source.replace("\r\n", "\n")
    assert section_anchors(secfile.parse_source(lf, tolerant=True)) == anchors
