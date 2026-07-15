# Manual browser checklist — decision page

Build: `python -m specgen html "masters/23 64 10.SEC" -o out/decisions.html`
and open `out/decisions.html`. Run top to bottom; also covers the pending
Tasks 7/8 items (redline view, tailoring profile).

## Inline edit mode
- [ ] Click Edit → button reads "Edit: on", view forced to redline, view toggle disabled
- [ ] Click in plain text, type — characters appear green at the caret
- [ ] Backspace over original text — red strikethrough, caret hops left past it
- [ ] Backspace over green text you just typed — genuinely removed
- [ ] Forward Delete — strikethrough grows rightward
- [ ] Select a phrase, press a letter — phrase struck red, letter green after it
- [ ] Select a phrase, Ctrl+X — struck red (and on the clipboard)
- [ ] Paste rich text from Word/browser — inserts as plain green text
- [ ] Enter — inserts a literal newline (green)
- [ ] Ctrl+Z / Ctrl+Y — steps edits backward/forward, caret follows
- [ ] Try to type inside a yellow bracket mark — blocked, hint toast appears
- [ ] Try to select across a bracket mark and delete — blocked + hint
- [ ] Try to type inside a plural "[s]" or designer-note bracket — blocked + hint
- [ ] Progress footer shows "· N text edits"
- [ ] Toggle Edit off — document read-only again, edits still shown

## Review card
- [ ] Click any green/red run (view mode) — TEXT EDIT card with before/after
- [ ] Add an audit note — persists after reload (autosave)
- [ ] Revert this change — text restored, record gone
- [ ] In edit mode, clicking a run both places the caret and shows the card

## Decisions & custom text
- [ ] Click a bracket decision → answer via options — unchanged behavior
- [ ] "Edit text… (start from the original)" prefills the freeform input
- [ ] Saving freeform text shows <s>original</s><ins>custom</ins> redline
- [ ] Submittal-review card has the freeform input
- [ ] Unsafe (dashed red) decision card copy mentions SI Editor, not select-to-edit

## Round trip
- [ ] Export answers (JSON) → includes ME@ records
- [ ] Clear all → import the JSON → edits and answers all restored
- [ ] Hand-corrupt one ME@ "before" in the JSON, import → dropped with notice
- [ ] `python -m specgen generate "masters/23 64 10.SEC" --answers <export>.json -o out/generated/t.sec --revisions` → open the .revisions.sec in SpecsIntact: inline edits show as red/green tracked changes

## Pre-existing checks (Tasks 7/8 pass)
- [ ] Redline view toggle: clean view hides strikethroughs and shows chosen text
- [ ] Tailoring profile remove → blocks collapse to "▸ NAME removed" chips; keep restores
- [ ] Units SI/IP toggle strikes the unchosen halves in redline view
