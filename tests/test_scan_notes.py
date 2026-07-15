from specgen.scan import scan_groups, text_stream

# balanced brackets in a note, plus a body choice
BAL = (
    "<SEC><NTE><NPR>NOTE: choose [copper][steel] per project.</NPR></NTE>"
    "<TXT>Provide [scroll][screw] compressors.</TXT></SEC>"
)

# 23 09 23.01 idiom: a note QUOTING an unmatched bracket character
UNBAL = (
    '<SEC><NTE><NPR>NOTE: "a Gateway [or " appears only when selected.</NPR></NTE>'
    "<TXT>Provide [one][two] units.</TXT></SEC>"
)

# note bracket directly adjacent to a body bracket must not merge
ADJ = "<SEC><NTE>keep [x]</NTE>[y] text</SEC>"


def test_note_groups_marked_and_ids_stable():
    groups, _, _ = scan_groups(BAL)
    assert [g.gid for g in groups] == ["BRK-0001", "BRK-0002"]
    assert [g.in_note for g in groups] == [True, False]
    body = groups[1]
    assert [o.text for o in body.options] == ["scroll", "screw"]


def test_unbalanced_note_bracket_does_not_leak():
    groups, _, _ = scan_groups(UNBAL)
    body = [g for g in groups if not g.in_note]
    assert len(body) == 1
    assert [o.text for o in body[0].options] == ["one", "two"]


def test_note_body_adjacency_never_merges():
    groups, _, _ = scan_groups(ADJ)
    assert len(groups) == 2
    assert groups[0].in_note and not groups[1].in_note


def test_text_stream_mask():
    text, offs, mask = text_stream("<SEC>a<NTE>b</NTE>c</SEC>")
    assert text == "abc"
    assert mask == [False, True, False]
    assert len(offs) == 3
