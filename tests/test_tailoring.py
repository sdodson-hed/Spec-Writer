"""Joint-OPT tailoring: profile is keyed by INDIVIDUAL option names.

A <TAI OPT="AIR FORCE,NAVY"> block applies to either service; it is removed
only when ALL of its names are set to remove (generate.removable and the HTML
page's inRemovedTai/activeSpans already comma-split). tailoring_options must
therefore aggregate per individual name, or the profile rows/workbook expose
a dead joint key that nothing consumes (GitHub issue #20).
"""

from specgen import secfile
from specgen.generate import generate
from specgen.manifest import build_manifest

JOINT = (
    '<SEC><TAI OPT="AIR FORCE,NAVY"><TXT>af or navy text</TXT></TAI>'
    '<TAI OPT="ARMY"><TXT>army text</TXT></TAI>'
    "<TXT>Body.</TXT></SEC>"
)


def test_manifest_keys_tailoring_options_by_individual_name():
    m = build_manifest(secfile.parse_source(JOINT))
    assert set(m["tailoring_options"]) == {"AIR FORCE", "NAVY", "ARMY"}
    # the joint block's blocks/chars are credited to BOTH of its names
    af, navy = m["tailoring_options"]["AIR FORCE"], m["tailoring_options"]["NAVY"]
    assert af["blocks"] == navy["blocks"] == 1
    assert af["chars"] == navy["chars"] == len("af or navy text")
    # true block count is NOT double-counted by the per-name split
    assert m["counts"]["tailoring_blocks"] == 2
    # spans keep the raw joint opt string (the HTML splits it)
    assert sorted(s["opt"] for s in m["tailoring_spans"]) == [
        "AIR FORCE,NAVY",
        "ARMY",
    ]


def test_generate_joint_block_needs_all_names_removed(tmp_path):
    master = tmp_path / "t.SEC"
    master.write_bytes(JOINT.encode(secfile.ENCODING))

    out1 = tmp_path / "one.sec"
    generate(master, {"AIR FORCE": "remove"}, {}, out1)
    r1 = out1.read_bytes().decode(secfile.ENCODING)
    assert "af or navy text" in r1  # NAVY not removed -> block stays

    out2 = tmp_path / "both.sec"
    generate(master, {"AIR FORCE": "remove", "NAVY": "remove"}, {}, out2)
    r2 = out2.read_bytes().decode(secfile.ENCODING)
    assert "af or navy text" not in r2
    assert "army text" in r2  # ARMY untouched
