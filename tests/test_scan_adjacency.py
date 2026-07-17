from specgen.scan import scan_groups


def test_invisible_markup_merges():
    src = "<SEC>[alpha]</SPT>[beta]</SEC>"
    groups, _, _ = scan_groups(src)
    assert len(groups) == 1
    assert [o.text for o in groups[0].options] == ["alpha", "beta"]
    # The merged span encloses a lone </SPT>: unbalanced, so the generator
    # must not splice it.
    assert groups[0].safe is False


def test_tai_gap_merges():
    src = '<SEC>[alpha]<TAI OPT="NAVY">[beta]</TAI></SEC>'
    groups, _, _ = scan_groups(src)
    assert len(groups) == 1
    assert groups[0].safe is False


def test_eng_gap_merges():
    src = "<SEC>[alpha]</ENG>[beta]</SEC>"
    groups, _, _ = scan_groups(src)
    assert len(groups) == 1
    assert groups[0].safe is False


def test_structural_tag_still_splits():
    src = "<SEC>[alpha]<OLI>[beta]</OLI></SEC>"
    groups, _, _ = scan_groups(src)
    assert len(groups) == 2


def test_whole_subsection_runs_split_into_optionals():
    # issue #36: butted whole-subsection brackets (26 20 00 2.7.5-2.7.13)
    # are independent include/exclude blocks, never one N-way choice
    src = (
        "<SEC>[<SPT><TTL>Service Entrance Cables</TTL><TXT>SE and USE, UL 854."
        "</TXT></SPT>][<SPT><TTL>Nonmetallic Sheathed Cable</TTL><TXT>UL 719."
        "</TXT></SPT>][<SPT><TTL>400 Hz Circuits</TTL><TXT>Copper.</TXT></SPT>]"
        "</SEC>"
    )
    groups, text, _ = scan_groups(src)
    assert [g.kind for g in groups] == ["optional", "optional", "optional"]
    assert all(g.safe and len(g.options) == 1 for g in groups)
    assert text[groups[1].char_start : groups[1].char_start + 12] == "[Nonmetallic"


def test_mixed_run_with_subsection_span_splits_fully():
    # a small span butted against a subsection span is not its alternative
    src = "<SEC>[small text][<SPT><TTL>Big Block</TTL><TXT>Body.</TXT></SPT>]</SEC>"
    groups, _, _ = scan_groups(src)
    assert [(g.kind, len(g.options)) for g in groups] == [
        ("optional", 1),
        ("optional", 1),
    ]


def test_plain_text_choices_still_merge():
    src = "<SEC><TXT>Provide [scroll][screw] compressors.</TXT></SEC>"
    groups, _, _ = scan_groups(src)
    assert len(groups) == 1 and groups[0].kind == "choice"
