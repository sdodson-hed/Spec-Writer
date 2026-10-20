"""Manifest data for removal cleanup (plan 2026-10-20, Task 1)."""

import os
from pathlib import Path

import pytest

from specgen import secfile
from specgen.manifest import build_manifest

SRC = (
    "<SEC><PRT><TTL>PART 1 GENERAL</TTL>"
    "<SPT><TTL>REFERENCES</TTL>"
    "<REF><ORG>AHRI</ORG><BRK/>\r\n<BRK/>\r\n"
    "<RID>AHRI 450</RID><RTL>Remote condensers</RTL><BRK/>\r\n<BRK/>\r\n"
    "<RID>AHRI 550/590</RID><RTL>Chillers</RTL><BRK/>\r\n<BRK/>\r\n</REF>"
    "<REF><ORG>NFPA</ORG><BRK/>\r\n<BRK/>\r\n"
    "<RID>NFPA 37</RID><RTL>Engines</RTL><BRK/>\r\n<BRK/>\r\n</REF></SPT>"
    "<SPT><TTL>SUBMITTALS</TTL>"
    "<TXT>Submit per Section <SRF>01 33 00</SRF>:</TXT><BRK/>\r\n<BRK/>\r\n"
    "<LST><SUB>SD-03 Product Data</SUB></LST><BRK/>\r\n<BRK/>\r\n"
    "<ITM><SUB>Scroll Chiller</SUB></ITM><BRK/>\r\n<BRK/>\r\n"
    "<ITM><SUB>Gas Engine</SUB>; <SUB>G, [_____]</SUB></ITM><BRK/>\r\n<BRK/>\r\n"
    "[<ITM><SUB>Field Test Plan</SUB></ITM><BRK/>\r\n<BRK/>\r\n]"
    "<LST><SUB>SD-06 Test Reports</SUB></LST><BRK/>\r\n<BRK/>\r\n"
    "<ITM><SUB>Never Used</SUB></ITM><BRK/>\r\n<BRK/>\r\n"
    "</SPT></PRT>"
    "<PRT><TTL>PART 2 PRODUCTS</TTL>"
    "<SPT><TTL>SCROLL</TTL><TXT>Provide <SUB>Scroll Chiller</SUB> per <RID>AHRI 550/590</RID>."
    " See Section <SRF>23 64 26</SRF>.</TXT></SPT>"
    "<SPT><TTL>ENGINE</TTL><TXT>Provide <SUB>gas  engine</SUB> per <RID>NFPA 37</RID>"
    " and <RID>AHRI 450</RID>; <SUB>Field Test Plan</SUB>; also <SUB>Scroll Chiller</SUB>."
    " See Section <SRF>22 00 00</SRF>.</TXT></SPT>"
    "</PRT></SEC>"
)


def _m(src=SRC):
    return build_manifest(secfile.parse_source(src))


def test_one_entry_per_item_with_spans_and_groups():
    m = _m()
    e = m["submittal_entries"]
    assert [x["name"] for x in e] == [
        "Scroll Chiller", "Gas Engine", "Field Test Plan", "Never Used"]
    assert [x["id"] for x in e] == ["ITM-0001", "ITM-0002", "ITM-0003", "ITM-0004"]
    for x in e:
        a, b = x["src"]
        assert SRC[a:].startswith("<ITM>") and SRC[:b].endswith("</ITM>")
    assert [x["sd_group"] for x in e] == ["SD-03 Product Data"] * 3 + ["SD-06 Test Reports"]
    groups = m["submittal_groups"]
    assert [(g["name"], g["items"]) for g in groups] == [
        ("SD-03 Product Data", ["ITM-0001", "ITM-0002", "ITM-0003"]),
        ("SD-06 Test Reports", ["ITM-0004"]),
    ]
    a, b = groups[0]["src"]
    assert SRC[a:b] == "<LST><SUB>SD-03 Product Data</SUB></LST>"


def test_item_uses_reviewer_and_bracket():
    m = _m()
    e = {x["name"]: x for x in m["submittal_entries"]}
    assert len(e["Scroll Chiller"]["uses"]) == 2
    assert len(e["Gas Engine"]["uses"]) == 1        # matched case/space-insensitive
    assert e["Never Used"]["uses"] == []
    for a, b in e["Scroll Chiller"]["uses"]:
        assert SRC[a:b] == "<SUB>Scroll Chiller</SUB>"
    assert e["Gas Engine"]["reviewer"] == "G, [_____]"
    assert e["Scroll Chiller"]["reviewer"] is None
    brk = e["Field Test Plan"]["in_bracket"]
    assert brk and next(d for d in m["decisions"] if d["id"] == brk)["kind"] == "optional"
    assert e["Scroll Chiller"]["in_bracket"] is None


def test_reference_entries_gain_spans_and_uses():
    m = _m()
    r = {x["rid"]: x for x in m["references"]}
    assert set(r) == {"AHRI 450", "AHRI 550/590", "NFPA 37"}
    a, b = r["NFPA 37"]["src"]
    assert SRC[a:b] == "<RID>NFPA 37</RID>"
    assert [SRC[a:b] for a, b in r["NFPA 37"]["uses"]] == ["<RID>NFPA 37</RID>"]
    assert len(r["AHRI 550/590"]["uses"]) == 1
    assert r["AHRI 450"]["org"] == "AHRI"
    orgs = m["reference_orgs"]
    assert [(o["org"], o["rids"]) for o in orgs] == [
        ("AHRI", ["AHRI 450", "AHRI 550/590"]), ("NFPA", ["NFPA 37"])]
    a, b = orgs[1]["src"]
    assert SRC[a:].startswith("<REF><ORG>NFPA") and SRC[:b].endswith("</REF>")


def test_section_refs():
    m = _m()
    refs = m["section_refs"]
    assert sorted(refs) == ["01 33 00", "22 00 00", "23 64 26"]
    a, b = refs["22 00 00"][0]
    assert SRC[a:b] == "<SRF>22 00 00</SRF>"


def test_sd_heading_without_sub_tag_is_recognized():
    # 26 32 15 (UMRL July 2026) writes "<LST>SD-11 Closeout Submittals</LST>"
    # with no <SUB>; its items must not be filed under the previous heading
    src = SRC.replace("<LST><SUB>SD-06 Test Reports</SUB></LST>",
                      "<LST>SD-06 Test Reports</LST>")
    groups = _m(src)["submittal_groups"]
    assert [(g["name"], g["items"]) for g in groups] == [
        ("SD-03 Product Data", ["ITM-0001", "ITM-0002", "ITM-0003"]),
        ("SD-06 Test Reports", ["ITM-0004"]),
    ]


def test_article_titled_submittals_wins_over_earlier_submittal_titles():
    # 01 33 00 has "Submittal Information" (1.1.1) before "SUBMITTALS" (1.3)
    src = SRC.replace(
        "<SPT><TTL>REFERENCES</TTL>",
        "<SPT><TTL>Submittal Information</TTL><ITM><SUB>Decoy</SUB></ITM></SPT>"
        "<SPT><TTL>REFERENCES</TTL>")
    names = [e["name"] for e in _m(src)["submittal_entries"]]
    assert names == ["Scroll Chiller", "Gas Engine", "Field Test Plan", "Never Used"]


def test_existing_submittals_list_unchanged():
    m = _m()
    # the deduped name list the report prints keeps its old shape
    assert {"name", "sd_group", "has_brackets"} == set(m["submittals"][0])


_ROOT = Path(__file__).resolve().parent.parent
_CORPUS = Path(os.environ.get("SPECGEN_CORPUS") or _ROOT / "masters")
_FILES = (
    sorted(p for p in _CORPUS.rglob("*") if p.suffix.lower() == ".sec")
    if _CORPUS.is_dir() else []
)


@pytest.mark.skipif(not _FILES, reason="corpus not present")
@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.stem)
def test_corpus_spans_point_at_their_elements(path):
    sec = secfile.parse(path, tolerant=True)
    m = build_manifest(sec)
    src = sec.source
    for x in m["submittal_entries"]:
        assert src.startswith("<ITM", x["src"][0])
        for a, b in x["uses"]:
            assert src.startswith("<SUB", a)
    for r in m["references"]:
        assert src.startswith("<RID", r["src"][0])
