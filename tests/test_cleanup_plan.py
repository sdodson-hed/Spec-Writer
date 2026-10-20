"""Cleanup planner (plan 2026-10-20, Task 2; decisions D1-D3)."""

from specgen import secfile
from specgen.cleanup import plan_cleanup
from specgen.manifest import build_manifest
from tests.test_cleanup_manifest import SRC


def _plan(src, *titles):
    sec = secfile.parse_source(src)
    m = build_manifest(sec)
    removed = {s["id"]: tuple(s["src"]) for s in m["subsections"] if s["title"] in titles}
    assert len(removed) == len(titles)
    return plan_cleanup(sec, m, removed), removed


def _by(actions, kind):
    return {a["name"]: a for a in actions if a["kind"] == kind}


def test_remove_engine_subsection():
    p, removed = _plan(SRC, "ENGINE")
    [engine] = removed
    items = _by(p["remove"], "submittal-item")
    refs = _by(p["remove"], "reference")
    orgs = _by(p["remove"], "reference-org")
    # used inside AND outside the removed subsection: kept
    assert "Scroll Chiller" not in items
    # only use was inside: removed, with its reviewer code logged
    gas = items["Gas Engine"]
    assert gas["reviewer"] == "G, [_____]" and gas["caused_by"] == [engine]
    assert SRC[slice(*gas["src"])] == (
        "<ITM><SUB>Gas Engine</SUB>; <SUB>G, [_____]</SUB></ITM><BRK/>\r\n<BRK/>\r\n")
    # never used in the master: never touched
    assert "Never Used" not in items
    # orphan inside a bracket: blocked, not removed (D1)
    [blocked] = p["blocked"]
    assert blocked["name"] == "Field Test Plan" and blocked["in_bracket"]
    assert blocked["caused_by"] == [engine]
    # reference entry removed; its org still has a used entry
    assert SRC[slice(*refs["AHRI 450"]["src"])] == (
        "<RID>AHRI 450</RID><RTL>Remote condensers</RTL><BRK/>\r\n<BRK/>\r\n")
    assert "AHRI 550/590" not in refs and "AHRI" not in orgs
    # every entry of NFPA orphaned: the whole org block goes instead (D2)
    assert "NFPA 37" not in refs
    nfpa = orgs["NFPA"]
    assert nfpa["rids"] == ["NFPA 37"]
    text = SRC[slice(*nfpa["src"])]
    assert text.startswith("<REF><ORG>NFPA") and text.endswith("</REF>")
    # SD headings keep their remaining items
    assert _by(p["remove"], "sd-heading") == {}
    assert p["section_refs_dropped"] == ["22 00 00"]


def test_items_inside_a_removed_subsection_are_not_actions():
    p, _ = _plan(SRC, "SUBMITTALS")
    assert _by(p["remove"], "submittal-item") == {}
    assert p["blocked"] == []
    # the submittals article cited 01 33 00; nothing else does
    assert p["section_refs_dropped"] == ["01 33 00"]


def test_both_product_subsections_removed():
    p, removed = _plan(SRC, "SCROLL", "ENGINE")
    items = _by(p["remove"], "submittal-item")
    assert set(items) == {"Scroll Chiller", "Gas Engine"}
    assert items["Scroll Chiller"]["caused_by"] == sorted(removed)
    # SD-03 still holds the blocked bracketed item, so its heading stays
    assert _by(p["remove"], "sd-heading") == {}
    # AHRI 550/590 now orphaned too: both AHRI entries gone, so the org goes
    assert set(_by(p["remove"], "reference-org")) == {"AHRI", "NFPA"}
    assert _by(p["remove"], "reference") == {}


HEAD = (
    "<SEC><PRT><TTL>PART 1</TTL><SPT><TTL>SUBMITTALS</TTL>"
    "<LST><SUB>SD-03 Product Data</SUB></LST><BRK/>\r\n<BRK/>\r\n"
    "<ITM><SUB>Keep Me</SUB></ITM><BRK/>\r\n<BRK/>\r\n"
    "<LST><SUB>SD-06 Test Reports</SUB></LST><BRK/>\r\n<BRK/>\r\n"
    "<ITM><SUB>Engine Test</SUB></ITM><BRK/>\r\n<BRK/>\r\n"
    "<ITM><SUB>Engine Log</SUB></ITM><BRK/>\r\n<BRK/>\r\n"
    "</SPT></PRT><PRT><TTL>PART 2</TTL>"
    "<SPT><TTL>A</TTL><TXT><SUB>Keep Me</SUB></TXT></SPT>"
    "<SPT><TTL>ENGINE</TTL><TXT><SUB>Engine Test</SUB>, <SUB>Engine Log</SUB></TXT></SPT>"
    "</PRT></SEC>"
)


def test_heading_emptied_by_cleanup_is_removed():
    p, removed = _plan(HEAD, "ENGINE")
    heads = _by(p["remove"], "sd-heading")
    assert set(heads) == {"SD-06 Test Reports"}
    assert HEAD[slice(*heads["SD-06 Test Reports"]["src"])] == (
        "<LST><SUB>SD-06 Test Reports</SUB></LST><BRK/>\r\n<BRK/>\r\n")
    assert heads["SD-06 Test Reports"]["caused_by"] == sorted(removed)
    assert set(_by(p["remove"], "submittal-item")) == {"Engine Test", "Engine Log"}


def test_nothing_removed_means_no_actions():
    sec = secfile.parse_source(SRC)
    p = plan_cleanup(sec, build_manifest(sec), {})
    assert p == {"remove": [], "blocked": [], "section_refs_dropped": []}
