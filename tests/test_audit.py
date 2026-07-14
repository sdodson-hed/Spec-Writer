from specgen import secfile
from specgen.audit import audit_source

CLEAN = (
    "<SEC><NTE>choose [x] wisely</NTE>"
    '<TAI OPT="ARMY"><TXT>army text</TXT></TAI>'
    "<TXT>Provide [scroll][screw] units rated<MET> 5 kW</MET><ENG> 2 tons</ENG> "
    "with [_____] starts per hour.</TXT></SEC>"
)

STRAY = "<SEC><TXT>orphan ] bracket</TXT></SEC>"


def test_clean_source_fully_attributed():
    sec = secfile.parse_source(CLEAN)
    report = audit_source(sec.source, sec.root)
    assert report["unknowns"] == []
    b = report["signals"]["bracket-group"]
    assert b["surfaced"] == 2 and b["excluded:note-text"] == 1
    assert report["signals"]["tailoring"]["surfaced"] == 1
    assert report["signals"]["units"]["surfaced"] == 2


def test_stray_bracket_is_unknown():
    sec = secfile.parse_source(STRAY)
    report = audit_source(sec.source, sec.root)
    assert len(report["unknowns"]) == 1
    assert report["unknowns"][0]["type"] == "stray-bracket"


# Corpus pattern (e.g. 23 01 30.41.SEC): the whole submittal <ITM> is
# optional, and the "; <SUB>G, [office]" reviewer idiom is nested inside
# it. Nested brackets stay embedded in their enclosing option (scan.py) —
# the outer optional group already surfaces this; it must not also be
# reported as an unrecognized submittal classification.
NESTED_SUBREV_IN_OPTIONAL_ITEM = (
    "<SEC><SPT><SUB>SD-03 Product Data</SUB><BRK/>"
    '[<ITM><SUB>Gravimetric Analysis</SUB>[; <SUB>G<TAI OPT="ARMY">, '
    "[_____]</TAI></SUB>]</ITM><BRK/>]</SPT></SEC>"
)

# Corpus pattern (e.g. 23 81 47.SEC): the SD-G/S reviewer flag is hardcoded
# with no brackets at all -- only the office blank is bracketed. There is
# no decision in the bare classification text, so it must be excluded, not
# unknown.
FIXED_SUBREV_NO_BRACKETS = (
    "<SEC><SPT><SUB>SD-03 Product Data</SUB><BRK/>"
    '<ITM><SUB>Pipe</SUB>; <SUB>G<TAI OPT="ARMY">, [_____]</TAI></SUB></ITM>'
    "</SPT></SEC>"
)


def test_nested_submittal_review_inside_optional_item_not_unknown():
    sec = secfile.parse_source(NESTED_SUBREV_IN_OPTIONAL_ITEM)
    report = audit_source(sec.source, sec.root)
    assert report["unknowns"] == []
    assert report["signals"]["bracket-group"]["surfaced"] == 1


def test_fixed_classification_without_brackets_is_excluded_not_unknown():
    sec = secfile.parse_source(FIXED_SUBREV_NO_BRACKETS)
    report = audit_source(sec.source, sec.root)
    assert report["unknowns"] == []
    sc = report["signals"]["submittal-classification"]
    assert sc["excluded:fixed-classification"] == 1
    # the office blank is still its own surfaced bracket-group decision
    assert report["signals"]["bracket-group"]["surfaced"] == 1
