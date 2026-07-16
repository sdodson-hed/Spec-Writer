"""Unsafe bracket groups (safe == False: options cross SI structural markup)
are editable inline: a contiguous manual edit landing inside an unsafe group's
span is applied, while safe-group overlap and markup-crossing edits stay
rejected. XML safety rests on the contiguity check (a contiguous stream range
maps to a tag-free source range), not on the decision-overlap rejection."""

from specgen import secfile
from specgen.generate import generate, resolve_revisions, revert_revisions
from specgen.manifest import build_manifest
from specgen.scan import scan_groups

# One bracket whose options cross a </TXT><TXT> boundary: scan flags it unsafe.
UNSAFE_SRC = (
    "<SEC><TXT>Provide [alpha units for zone one</TXT>"
    "<TXT>beta units for zone two] in the plant room.</TXT></SEC>"
)

SAFE_SRC = "<SEC><TXT>Provide [scroll][screw] compressors.</TXT></SEC>"


def _write(tmp_path, name, src):
    p = tmp_path / name
    p.write_bytes(src.encode(secfile.ENCODING))
    return p


def test_edit_overlapping_unsafe_group_is_applied(tmp_path):
    master = _write(tmp_path, "u.SEC", UNSAFE_SRC)
    m = build_manifest(secfile.parse(master))
    (dec,) = [d for d in m["decisions"] if d["id"] == "BRK-0001"]
    assert dec["safe"] is False  # fixture really is an unsafe group

    _groups, text, _offs = scan_groups(UNSAFE_SRC)
    start = text.index("alpha")
    end = start + len("alpha")
    assert dec["char_start"] < end and start < dec["char_end"]  # inside group
    answers = {
        f"ME@{start}": {
            "start": start,
            "end": end,
            "before": "alpha",
            "after": "gamma",
            "notes": "",
        }
    }
    out = tmp_path / "out.sec"
    generate(master, {}, answers, out, revisions=True)
    clean = out.read_bytes().decode(secfile.ENCODING)
    assert "gamma units for zone one" in clean  # edit applied
    assert "alpha" not in clean
    unresolved_md = out.with_suffix(".unresolved.md").read_text(encoding="utf-8")
    assert "manual-edit" not in unresolved_md  # edit was NOT rejected
    rev = out.with_suffix(".revisions.sec").read_bytes().decode(secfile.ENCODING)
    assert "<DEL>alpha</DEL><ADD>gamma</ADD>" in rev
    assert resolve_revisions(rev) == clean
    assert revert_revisions(rev) == UNSAFE_SRC


def test_edit_overlapping_safe_group_still_rejected(tmp_path):
    master = _write(tmp_path, "s.SEC", SAFE_SRC)
    m = build_manifest(secfile.parse(master))
    assert m["decisions"][0]["safe"] is True

    _groups, text, _offs = scan_groups(SAFE_SRC)
    gstart = text.index("[scroll]")
    start, end = gstart + 1, gstart + 3  # inside the safe group's span
    answers = {
        f"ME@{start}": {
            "start": start,
            "end": end,
            "before": text[start:end],
            "after": "zz",
            "notes": "",
        }
    }
    out = tmp_path / "out.sec"
    generate(master, {}, answers, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "zz" not in result
    unresolved_md = out.with_suffix(".unresolved.md").read_text(encoding="utf-8")
    assert "manual-edit" in unresolved_md
    assert "overlaps decision BRK-0001" in unresolved_md


def test_markup_crossing_edit_in_unsafe_group_still_rejected(tmp_path):
    master = _write(tmp_path, "u.SEC", UNSAFE_SRC)
    _groups, text, _offs = scan_groups(UNSAFE_SRC)
    # "onebeta" spans the stripped </TXT><TXT> boundary: non-contiguous source
    start = text.index("onebeta")
    end = start + len("onebeta")
    answers = {
        f"ME@{start}": {
            "start": start,
            "end": end,
            "before": "onebeta",
            "after": "x",
            "notes": "",
        }
    }
    out = tmp_path / "out.sec"
    generate(master, {}, answers, out)
    result = out.read_bytes().decode(secfile.ENCODING)
    assert "alpha units for zone one" in result  # untouched
    assert ">x<" not in result and "x units" not in result
    unresolved_md = out.with_suffix(".unresolved.md").read_text(encoding="utf-8")
    assert "manual-edit" in unresolved_md
    assert "markup" in unresolved_md
