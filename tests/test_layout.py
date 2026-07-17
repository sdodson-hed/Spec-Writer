"""Renderer layout fidelity (issues #42, #43).

#42 — <BRK/> is an explicit hard line break and reference articles carry no
literal whitespace between fields, so the flat text stream must emit "\\n"
for <BRK/> and a "\\t" between an </RID> and an immediately-following <RTL>.
#43 — body prose is hard-wrapped with CRLFs; the HTML page reflows a single
CRLF to a space in view mode (kept literal in edit mode).
"""

import shutil
import subprocess

import pytest

from specgen import secfile
from specgen.htmlpage import EDIT_CORE_JS, write_html
from specgen.manifest import build_manifest
from specgen.scan import scan_groups, text_stream

REF = (
    "<SEC><REF><ORG>AMERICAN CONCRETE INSTITUTE (ACI)</ORG><BRK/><BRK/>"
    "<RID>ACI 117</RID><RTL>(2010) Tolerances</RTL><BRK/><BRK/>"
    "<RID>ACI 301</RID><RTL>(2020) Structural Concrete</RTL></REF></SEC>"
)


def test_brk_emits_newline():
    text, offs, mask = text_stream("<SEC>a<BRK/>b<BRK/><BRK/>c</SEC>")
    assert text == "a\nb\n\nc"
    assert len(offs) == len(text) == len(mask)  # maps stay aligned


def test_reference_article_is_readable():
    text, _, _ = text_stream(REF)
    assert text == (
        "AMERICAN CONCRETE INSTITUTE (ACI)\n\n"
        "ACI 117\t(2010) Tolerances\n\n"
        "ACI 301\t(2020) Structural Concrete"
    )


def test_itm_list_items_are_indented():
    # <ITM> list items get a leading tab so they sit under their heading
    text, _, _ = text_stream(
        "<SEC><LST><SUB>SD-01</SUB></LST><ITM><SUB>Curing Plan</SUB></ITM></SEC>"
    )
    assert text == "SD-01\tCuring Plan"


def test_optional_submittal_span_covers_trailing_spacing(tmp_path):
    # UFGS wraps a submittal item AND its trailing blank-line spacing in one
    # optional bracket; the scanner keeps that whole span (so keep/delete is
    # correct), and the HTML page trims the whitespace out of the highlight.
    src = (
        "<SEC>[<ITM><SUB>Concrete Curing Plan</SUB></ITM><BRK/>\r\n<BRK/>\r\n]"
        "<ITM><SUB>Quality Control Program</SUB></ITM></SEC>"
    )
    groups, text, _ = scan_groups(src)
    g = groups[0]
    slice_ = text[g.char_start : g.char_end]
    assert slice_.startswith("[\tConcrete Curing Plan")
    assert slice_.endswith("]")
    # the closing bracket floats past blank lines in the raw span — the page's
    # mark-trim regex is what pulls it back onto the item's line
    assert "\n" in slice_[:-1]


def test_page_carries_mark_trim(tmp_path):
    p = tmp_path / "s.SEC"
    p.write_bytes(
        b"<SEC>[<ITM><SUB>Curing Plan</SUB></ITM><BRK/>\r\n<BRK/>\r\n]"
        b"<ITM><SUB>QC Program</SUB></ITM></SEC>"
    )
    out = tmp_path / "s.html"
    write_html(build_manifest(secfile.parse(p)), out)
    html = out.read_text(encoding="utf-8")
    # the leaf-decision whitespace-trim path is present
    assert "/^(\\[)(\\s*)([\\s\\S]*?)(\\s*)(\\])$/" in html


FLOW_HARNESS = r"""
function eq(a, b, msg) {
  const ja = JSON.stringify(a), jb = JSON.stringify(b);
  if (ja !== jb) {
    console.error("FAIL " + msg + "\n  got      " + ja + "\n  expected " + jb);
    process.exit(1);
  }
}
const T = "A.\r\n\r\nB";                    // paragraph break, run = [2,6)
const R = flowRunsFor(T);
eq(flowSliceIn(T, R, 0, T.length), "A.\n\nB", "full paragraph break");
// a run split across two render pieces is applied exactly once, by the
// piece containing the run START — concatenation must equal the full render
eq(flowSliceIn(T, R, 0, 4) + flowSliceIn(T, R, 4, T.length), "A.\n\nB",
   "boundary-split run stays one paragraph break");
const T2 = "forms,\r\nsizes";
eq(flowSliceIn(T2, flowRunsFor(T2), 0, T2.length), "forms, sizes",
   "single CRLF reflows to space");
const T3 = "list\n\r\nnext";                // BRK newline + file CRLF
eq(flowSliceIn(T3, flowRunsFor(T3), 0, T3.length), "list\nnext",
   "BRK-bearing run collapses to one break");
eq(syntheticIn("a\tb\r\nc\nd", 0, 8), [[1,2],[6,7]],
   "tab and lone-newline are synthetic; CRLF newline is not");

// ---- flowed edit mode: widths, mapping, atomic deletion expansion ----
const GT = "ab\r\ncd";                       // gap text, run [2,4) -> " "
const FR = flowRunsFor(GT);
eq(gapWidthsIn(GT, {}, 0, 6, FR), [1,1,0,0,1,1], "run chars are zero-width");
eq(domToDispW([1,1,0,0,1,1], 2), 2, "dom 2 maps before the run cluster");
eq(dispToDomW([1,1,0,0,1,1], 4), 2, "display past the run projects to dom 2");
// typed insertion: i chars are width 1 (except \r of a typed CRLF pair)
const REC = { "ME@2": { start: 2, end: 2, before: "", after: "XY", notes: "" } };
eq(gapWidthsIn(GT, REC, 0, 6, FR), [1,1,1,1,0,0,1,1], "typed chars width 1");
// forward-delete whose 1-char target lands inside the run expands to the
// WHOLE run — a partial strike would leave a mangled \r or \n in the master
let ar = applyGapOp(GT, {}, 0, 6, { kind: "fwd", caret: 2 }, [],
                    FR.map(r => [r.s, r.e]));
eq(ar.records, { "ME@2": { start: 2, end: 4, before: "\r\n", after: "",
                           notes: "" } }, "run deletion is atomic");
// backspace before the run targets the real char, no expansion
ar = applyGapOp(GT, {}, 0, 6, { kind: "bs", caret: 2 }, [],
                FR.map(r => [r.s, r.e]));
eq(ar.records, { "ME@1": { start: 1, end: 2, before: "b", after: "",
                           notes: "" } }, "bs before run hits the real char");
// a run holding a locked synthetic char (<BRK/>): expansion covers the lock
// and the whole op is blocked
const BT = "x\ny";                            // BRK newline at [1,2)
const BFR = flowRunsFor(BT);
ar = applyGapOp(BT, {}, 0, 3, { kind: "fwd", caret: 1 },
                syntheticIn(BT, 0, 3), BFR.map(r => [r.s, r.e]));
eq(ar, { blocked: true }, "BRK line break is not deletable");
console.log("flow tests passed");
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_flow_core_boundary_coherence():
    r = subprocess.run(
        ["node", "-e", EDIT_CORE_JS + FLOW_HARNESS],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr or r.stdout


def test_note_inside_group_wins_guidance(tmp_path):
    # a bracketed subsection that carries its own note gets THAT note as
    # card guidance — not the preceding (unrelated) subsection's note
    src = (
        "<SEC><NTE><NPR>NOTE: prev guidance.</NPR></NTE>\r\n"
        "<TXT>[optional phrase]</TXT>\r\n"
        "[<SPT><TTL>Surface Finish</TTL><NTE><NPR>NOTE: inner guidance."
        "</NPR></NTE><TXT>Body text.</TXT></SPT>]</SEC>"
    )
    p = tmp_path / "g.SEC"
    p.write_bytes(src.encode(secfile.ENCODING))
    m = build_manifest(secfile.parse(p))
    by_id = {d["id"]: d for d in m["decisions"]}
    assert by_id["BRK-0001"]["note_guidance"] == "NOTE: prev guidance."
    assert by_id["BRK-0002"]["note_guidance"] == "NOTE: inner guidance."


def test_note_text_bolded_inside_marks(tmp_path):
    p = tmp_path / "g.SEC"
    p.write_bytes(
        ("<SEC>[<SPT><TTL>T</TTL><NTE><NPR>NOTE: inner.</NPR></NTE>"
         "<TXT>Body.</TXT></SPT>]</SEC>").encode(secfile.ENCODING)
    )
    out = tmp_path / "g.html"
    write_html(build_manifest(secfile.parse(p)), out)
    html = out.read_text(encoding="utf-8")
    assert "function noteBoldHtml(a, b)" in html
    # both render paths use it: build-time emit and update-time updateMark
    assert "${mp.coreHtml}</mark>" in html
    um = html.split("function updateMark")[1].split("\nfunction ")[0]
    assert "coreHtml" in um and "noteBoldHtml" in um


def test_manual_edit_on_synthetic_char_rejected(tmp_path):
    # deleting a <BRK/>-synthesized newline passes the contiguity check
    # (single char) but would splice into the tag's '<' — generate must
    # reject it as unresolved, not crash at output verification
    src = "<SEC><TXT>alpha</TXT><BRK/><TXT>beta</TXT></SEC>"
    from specgen.generate import generate
    from specgen.scan import text_stream

    text, _, _ = text_stream(src)
    k = text.index("\n")
    master = tmp_path / "m.SEC"
    master.write_bytes(src.encode(secfile.ENCODING))
    out = tmp_path / "out.sec"
    summary = generate(
        master,
        {},
        {f"ME@{k}": {"start": k, "end": k + 1, "before": "\n", "after": ""}},
        out,
    )
    assert summary["unresolved"] == 1
    unresolved = out.with_suffix(".unresolved.md").read_text(encoding="utf-8")
    assert "layout character" in unresolved
    # the master text is untouched
    got = out.read_bytes().decode(secfile.ENCODING)
    assert "<BRK/>" in got and "alpha" in got and "beta" in got


def test_inline_rid_gets_no_tab():
    # <RID> used inline in body (space follows in source) must not get a tab
    text, _, _ = text_stream("<SEC><TXT>per <RID>ACI 301</RID> Section 4.</TXT></SEC>")
    assert text == "per ACI 301 Section 4."


def test_rid_with_whitespace_before_rtl_gets_no_extra_tab():
    text, _, _ = text_stream("<SEC><RID>ACI 1</RID> <RTL>title</RTL></SEC>")
    assert text == "ACI 1 title"  # the source space separates them, no \t


def test_offsets_stay_monotonic_and_source_maps_back():
    text, offs, _ = text_stream(REF)
    assert offs == sorted(offs)
    # a real (non-synthetic) char still maps to its exact source char
    k = text.index("T")  # first 'T' in "INSTITUTE"
    assert REF[offs[k]] == "T"


def test_brk_does_not_break_roundtrip_or_manifest(tmp_path):
    p = tmp_path / "r.SEC"
    p.write_bytes(REF.encode(secfile.ENCODING))
    sec = secfile.parse(p)
    assert sec.roundtrips()  # serializer is independent of the text stream
    m = build_manifest(sec)
    assert "\t" in m["text"] and "\n\n" in m["text"]


def test_page_flows_both_modes_and_anchors_scroll(tmp_path):
    p = tmp_path / "r.SEC"
    p.write_bytes(REF.encode(secfile.ENCODING))
    out = tmp_path / "r.html"
    write_html(build_manifest(secfile.parse(p)), out)
    html = out.read_text(encoding="utf-8")
    assert "function flowRunsFor(text)" in html    # global run classification
    assert "function flowSlice(a, b)" in html
    assert "tab-size: 4" in html                    # RID/RTL columns
    # edit mode shows the SAME flowed layout: run replacements render as
    # non-editable spans and the caret math skips them via per-char widths
    assert 'class="flowbrk" contenteditable="false"' in html
    assert "function gapWidthsIn(text, records, s, e, frs)" in html
    assert "domToDispW(gapWidths(gapEl)" in html
    assert '".navanchor,.flowbrk"' in html
    # deletions expand to whole layout runs (never a partial CRLF strike)
    assert "atomicOrig" in html
    # toggling edit/view keeps the reader's place
    assert "function rebuildDocAnchored()" in html
    body = html.split('getElementById("btnEdit").onclick')[1].split("};")[0]
    assert "rebuildDocAnchored()" in body


def test_update_paths_share_build_rendering(tmp_path):
    # updateMark/renderRedline must reproduce emit()'s trimmed+reflowed mark
    # content — a raw DATA.text slice there resurrects the CRLF jank (and
    # duplicates the whitespace emit() moved outside the mark) on the first
    # click, because refresh() re-renders every mark
    p = tmp_path / "r.SEC"
    p.write_bytes(REF.encode(secfile.ENCODING))
    out = tmp_path / "r.html"
    write_html(build_manifest(secfile.parse(p)), out)
    html = out.read_text(encoding="utf-8")
    assert "function markParts(s, e)" in html
    body = html.split("function updateMark")[1].split("\nfunction ")[0]
    assert "markParts(d.char_start, d.char_end)" in body
    assert "DATA.text.slice(d.char_start, d.char_end)" not in body
    rr = html.split("function renderRedline")[1].split("\nfunction ")[0]
    assert "markParts(" in rr
    # edit ops are blocked over synthetic layout chars
    assert "syntheticRangesIn(ctx.s, ctx.e)" in html
