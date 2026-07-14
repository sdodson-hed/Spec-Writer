from specgen import secfile
from specgen.htmlpage import write_html
from specgen.manifest import build_manifest

SRC = "<SEC><TXT>Provide [scroll][screw] compressors.</TXT></SEC>"


def _page(tmp_path):
    p = tmp_path / "t.SEC"
    p.write_bytes(SRC.encode(secfile.ENCODING))
    out = tmp_path / "t.html"
    write_html(build_manifest(secfile.parse(p)), out)
    return out.read_text(encoding="utf-8")


def test_redline_hooks_present(tmp_path):
    html = _page(tmp_path)
    assert 'id="btnView"' in html          # toggle button
    assert "state.view" in html            # persisted view mode
    assert "renderRedline" in html         # redline mark renderer
    assert "#doc mark s" in html           # strikethrough CSS


def test_clear_preserves_view_mode(tmp_path):
    html = _page(tmp_path)
    # btnClear's reset must carry the view key forward, or the live state
    # loses it until the next reload (renders clean while the toggle says on)
    assert 'view: state.view || "redline"' in html


NOTED = (
    "<SEC><NTE><NPR>NOTE: Select scroll for small plants.</NPR></NTE>"
    '<TAI OPT="ARMY"><TXT>army text</TXT></TAI>'
    "<TXT>Provide [scroll][screw] rated<MET> 5 kW</MET><ENG> 2 tons</ENG>.</TXT></SEC>"
)


def test_manifest_spans_and_guidance(tmp_path):
    from specgen.manifest import build_manifest
    p = tmp_path / "n.SEC"
    p.write_bytes(NOTED.encode(secfile.ENCODING))
    m = build_manifest(secfile.parse(p))
    assert m["tailoring_spans"][0]["opt"] == "ARMY"
    a, b = m["tailoring_spans"][0]["span"]
    assert m["text"][a:b] == "army text"
    body = [d for d in m["decisions"] if not d["in_note"]]
    assert "Select scroll" in body[0]["note_guidance"]


def test_page_has_gate_units_and_notes(tmp_path):
    p = tmp_path / "n.SEC"
    p.write_bytes(NOTED.encode(secfile.ENCODING))
    out = tmp_path / "n.html"
    write_html(build_manifest(secfile.parse(p)), out)
    html = out.read_text(encoding="utf-8")
    assert "UNITS_KEY" in html and "unit_spans" in html
    assert "note_guidance" in html
    assert "unanswered: open" in html   # export gate payload
    assert "tailoring_spans" in html


def test_esc_helper_escapes_double_quotes(tmp_path):
    # esc() output is interpolated into attribute values (value="...",
    # data-opt="..."); unescaped quotes in a typed answer like 30" dia
    # would truncate the attribute and corrupt the stored value on re-edit.
    html = _page(tmp_path)
    assert '&quot;' in html
    assert 'replace(/"/g, "&quot;")' in html


def test_dirty_flag_and_beforeunload_nag(tmp_path):
    html = _page(tmp_path)
    assert "let dirty = false;" in html
    assert "beforeunload" in html
    assert "dirty = false;" in html.split("beforeunload")[0]  # export resets it


def test_profOpen_is_clamped(tmp_path):
    html = _page(tmp_path)
    assert "Math.max(0, profAll - Object.keys(state.profile).length)" in html


NUMBERED = (
    "<SEC><PRT>PART 1  <TTL>GENERAL</TTL><SPT =1.1>1.1  <TTL>REFERENCES</TTL>"
    "body text</SPT></PRT></SEC>"
)


def test_manifest_nav_numbering_and_depth(tmp_path):
    p = tmp_path / "nav.SEC"
    p.write_bytes(NUMBERED.encode(secfile.ENCODING))
    m = build_manifest(secfile.parse(p))
    nav = m["nav"]
    assert len(nav) == 2
    assert nav[0]["num"] == "PART 1"
    assert nav[0]["title"] == "GENERAL"
    assert nav[0]["depth"] == 0
    assert nav[1]["num"] == "1.1"
    assert nav[1]["title"] == "REFERENCES"
    assert nav[1]["depth"] == 1
    assert isinstance(nav[0]["char"], int) and isinstance(nav[1]["char"], int)
    assert nav[0]["char"] <= nav[1]["char"]


def test_page_has_nav_panel_and_anchors(tmp_path):
    html = _page(tmp_path)
    assert 'id="navPanel"' in html
    assert "btnNavToggle" in html
    assert "navanchor" in html
    assert "DATA.nav" in html


def test_clear_preserves_nav_open(tmp_path):
    html = _page(tmp_path)
    # btnClear's reset must also carry navOpen forward, same lesson as
    # state.view (see test_clear_preserves_view_mode).
    assert "navOpen: state.navOpen" in html
