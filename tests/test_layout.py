"""Renderer layout fidelity (issues #42, #43).

#42 — <BRK/> is an explicit hard line break and reference articles carry no
literal whitespace between fields, so the flat text stream must emit "\\n"
for <BRK/> and a "\\t" between an </RID> and an immediately-following <RTL>.
#43 — body prose is hard-wrapped with CRLFs; the HTML page reflows a single
CRLF to a space in view mode (kept literal in edit mode).
"""

from specgen import secfile
from specgen.htmlpage import write_html
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


def test_page_reflows_in_view_keeps_literal_in_edit(tmp_path):
    p = tmp_path / "r.SEC"
    p.write_bytes(REF.encode(secfile.ENCODING))
    out = tmp_path / "r.html"
    write_html(build_manifest(secfile.parse(p)), out)
    html = out.read_text(encoding="utf-8")
    assert "function reflow(s)" in html
    assert "if (editMode) return s;" in html      # edit mode = verbatim
    assert "escFlow" in html                        # emission routed through it
    assert "tab-size: 4" in html                    # RID/RTL columns
