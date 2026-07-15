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


NAVSRC = (
    "<SEC><SCN>SECTION 99 00 00</SCN>"
    "<PRT><TTL>PART 1   GENERAL</TTL>"
    "<SPT><TTL>REFERENCES</TTL>ref text</SPT>"
    "<SPT><TTL>SUBMITTALS</TTL><SPT><TTL>Nested Item</TTL>x</SPT></SPT></PRT>"
    "<PRT><TTL>PART 2   PRODUCTS</TTL><SPT><TTL>STANDARD PRODUCTS</TTL>y</SPT></PRT></SEC>"
)


def test_manifest_nav_positional_numbering_and_depth(tmp_path):
    p = tmp_path / "nav.SEC"
    p.write_bytes(NAVSRC.encode(secfile.ENCODING))
    m = build_manifest(secfile.parse(p))
    nav = m["nav"]
    got = [(n["num"], n["title"], n["depth"]) for n in nav]
    assert got == [
        ("PART 1", "GENERAL", 0),
        ("1.1", "REFERENCES", 1),
        ("1.2", "SUBMITTALS", 1),
        ("1.2.1", "Nested Item", 2),
        ("PART 2", "PRODUCTS", 0),
        ("2.1", "STANDARD PRODUCTS", 1),
    ]
    chars = [n["char"] for n in nav]
    assert chars == sorted(chars)


def test_page_has_nav_panel_and_anchors(tmp_path):
    html = _page(tmp_path)
    assert 'id="navPanel"' in html
    assert "btnNavToggle" in html
    assert "navanchor" in html
    assert "DATA.nav" in html


def test_page_nav_is_collapsible_tree(tmp_path):
    p = tmp_path / "nav.SEC"
    p.write_bytes(NAVSRC.encode(secfile.ENCODING))
    out = tmp_path / "nav.html"
    write_html(build_manifest(secfile.parse(p)), out)
    html = out.read_text(encoding="utf-8")
    assert "navroot" in html
    assert "navtwist" in html
    assert "navttl" in html
    assert "text-overflow" in html


def test_clear_preserves_nav_open(tmp_path):
    html = _page(tmp_path)
    # btnClear's reset must also carry navOpen forward, same lesson as
    # state.view (see test_clear_preserves_view_mode).
    assert "navOpen: state.navOpen" in html


def test_nav_has_collapse_all_and_expand_all_controls(tmp_path):
    html = _page(tmp_path)
    assert 'data-navall="collapse"' in html
    assert 'data-navall="expand"' in html
    assert "collapse all" in html
    assert "expand all" in html


def test_paranum_span_emitted_for_depth_gt_zero_anchors(tmp_path):
    p_ = tmp_path / "nav.SEC"
    p_.write_bytes(NAVSRC.encode(secfile.ENCODING))
    out = tmp_path / "nav.html"
    write_html(build_manifest(secfile.parse(p_)), out)
    html = out.read_text(encoding="utf-8")
    assert 'class="paranum"' in html
    assert ".paranum {" in html  # CSS rule present


def test_numeric_answer_in_range_guard_present(tmp_path):
    # The "?" bug: an out-of-range digit answer must not be treated as an
    # option reference. Every place that parses the option-number regex
    # must also check the parsed indices are in range for the group.
    html = _page(tmp_path)
    assert "idx.every(i => i >= 0 && i < d.options.length)" in html
    # resolvedText no longer falls back to "?" for an unmatched index
    assert 'd.options[+n - 1] ?? "?"' not in html


def test_manual_text_edit_hooks_present(tmp_path):
    # Inline edit mode: edits render inside gaps; review card replaces the
    # old select-and-replace card.
    html = _page(tmp_path)
    assert 'class="gap" data-s=' in html    # offset-mapped gaps
    assert "data-e=" in html                # gap end bound for the editor
    assert "TEXT EDIT" in html              # review-card chip
    assert "data-me" in html                # edit-run attribute/lookup
    assert "state.edits" in html            # edit records persisted in state
    assert "renderMeCard" in html           # review & revert card
    assert "Revert this change" in html


def test_select_and_replace_flow_removed(tmp_path):
    html = _page(tmp_path)
    assert "onDocMouseUp" not in html
    assert "rejectSelection" not in html
    assert "renderEditCard" not in html
    assert "updateMeMark" not in html
    assert 'addEventListener("mouseup"' not in html


def test_edits_render_inline_not_as_islands(tmp_path):
    html = _page(tmp_path)
    assert "gapInner" in html
    assert 's class="me"' in html or 'class=\\"me\\"' in html or "s.me" in html
    assert "#doc s.me" in html              # CSS for inline deleted run
    assert "#doc ins.me" in html            # CSS for inline inserted run
    assert "mark.me" not in html            # old island styling/wiring gone


def test_locked_inline_spans_present(tmp_path):
    html = _page(tmp_path)
    assert "lockedtxt" in html
    assert "lockedOrigIn" in html
    # plural and in-note bracket spans are page-locked for generate parity
    assert "d.in_note || d.plural" in html


def test_prune_also_rejects_locked_overlaps(tmp_path):
    html = _page(tmp_path)
    body = html.split("function meConflict(")[1].split("\nfunction ")[0]
    assert "in_note" in body and "plural" in body


def test_prune_stale_edits_also_drops_conflicting_imports(tmp_path):
    # A hand-edited/imported answers JSON can carry ME@ records that overlap
    # a decision span, removed-tailoring span, unit span, or another edit.
    # pruneStaleEdits must reuse the save-time conflict predicate so a bad
    # import can't hide a decision's mark or re-export a conflicting edit.
    html = _page(tmp_path)
    body = html.split("function pruneStaleEdits()")[1].split("\nfunction ")[0]
    assert "meConflict(" in body
