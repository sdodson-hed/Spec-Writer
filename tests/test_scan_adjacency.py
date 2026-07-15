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
