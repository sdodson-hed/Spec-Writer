# Inline edit mode with live tracked changes — design

Date: 2026-07-15
Status: approved by Victor (design conversation, 2026-07-15)

## Problem

The HTML decision page's manual text editing is select-and-replace: select
text in the document, retype the replacement in a right-panel card. It is
clumsy, and the selection→offset capture has a bug (the card can show the
wrong original text). Engineers want a human sanity-check pass over the whole
section: click **Edit**, type anywhere like a Word document with Track
Changes on — insertions green, deletions red strikethrough — with every
change still flowing through export, `generate`, and the `.revisions.sec`
SpecsIntact tracked-changes output.

## Constraints

- The page stays a single self-contained HTML file: no server, no external
  libraries, opens from a shared drive.
- Edits must remain in the existing `ME@<start>` answer format
  `{start, end, before, after, notes}` — character ranges against the
  original master text — so autosave, export/import, stale-edit pruning
  (`pruneStaleEdits`), `generate` validation, and revisions output are
  unchanged.
- Bracket decisions, removed tailoring blocks, and removed unit halves are
  resolved by the answer system, never by free typing. They are locked
  islands in the document.

## UX

1. **Edit toggle.** An `Edit` button in the header toolbar (next to
   "Redline view: on"). State is not persisted; the page loads in view mode.
2. **Live Word-style tracking while editing.** In edit mode:
   - Typing inserts green (`<ins>`) text at the caret as you type.
   - Backspace / Delete / selection-delete / cut / drag-out of *original*
     text never removes it: the affected characters become red strikethrough
     (`<s>`) and the caret moves past them.
   - Deleting text that is itself green (typed this session or from an
     existing edit's `after`) genuinely removes it.
   - Paste inserts plain text only, as green.
   - Enter inserts a literal `\n` as green text (masters are plain-text
     lines).
3. **Locked islands.** Decision marks, removed tailoring blocks
   (`taicut`), and removed unit halves (`unitcut`) get a subtle tint in
   edit mode. Any keystroke, paste, or selection operation that would modify
   or cross a locked island (including selections spanning two gaps) is
   blocked, and a brief inline hint appears: "Answer brackets from the
   panel." Caret placement next to an island is always allowed.
4. **Review & revert card.** Clicking any green/red manual-edit run — in
   either mode — shows a right-panel card: before/after text, an optional
   audit-log note input, and a **Revert this change** button. The card is
   read-only about the text itself; all retyping happens inline. In edit
   mode the same click also places the caret normally; the card updates
   passively and never captures focus or blocks typing.
5. **Select-and-replace is removed.** `onDocMouseUp` selection capture,
   `rejectSelection`, and the old TEXT EDIT card entry path are deleted.
   (This also removes the wrong-original-text selection bug.)
6. **Per-decision custom text.** Every decision card gains an **Edit text**
   button. It opens a textarea prefilled with the decision's original
   bracket text. Saving stores a *custom text* answer for that decision:
   - Renders as `<s>original</s><ins>custom</ins>` in redline view, custom
     text alone in clean view.
   - Counts as answered in the progress bar and decision states.
   - The card shows the custom text with **Remove custom text** to restore
     normal choice/fill-in answering. Setting a custom text clears any
     choice answer and vice versa.

## Architecture

### Document rendering (htmlpage.py JS)

`buildDoc` today emits alternating root nodes: `.gap` spans (plain text,
`data-s` char base) and locked `<mark>` islands. Changes:

- **Manual edits render inline inside gaps** as `<s class="me">` /
  `<ins class="me">` runs (with `data-me` ids), instead of as separate
  `mark.me` root islands. View mode and edit mode render identically;
  clean view hides `<s>` content and shows `<ins>` content only, as today.
- `gapHtml` interleaves three streams: plain text, nav anchors
  (`contenteditable="false"`), and edit runs.

### Edit engine

- Edit mode sets `contentEditable` on each `.gap` span (not on `#doc`);
  islands stay non-editable. Editing is confined to one gap per operation.
- A `beforeinput` listener on `#doc` handles all input types:
  - `insertText` / `insertParagraph` / `insertFromPaste` (plain text):
    `preventDefault()`, insert or extend an `<ins>` at the caret. If the
    selection is non-collapsed, first apply the delete rule below.
  - `deleteContentBackward` / `deleteContentForward` / `deleteByCut` /
    `deleteByDrag`: `preventDefault()`; characters from original text are
    wrapped in `<s>` (splitting text nodes as needed); characters inside
    `<ins>` are removed; caret moves past the struck run.
  - Anything crossing a locked island or a gap boundary: blocked + hint.
  - Other input types (`formatBold`, etc.): `preventDefault()`.
- **Derivation.** After every applied input, walk the affected gap's DOM in
  order, tracking the original-text offset from `data-s`:
  - text node → unchanged original (advances offset, contributes to both
    sides)
  - `<s>` → deleted original (advances offset, `before` only)
  - `<ins>` → insertion (`after` only)
  - nav anchors → skipped (zero-width)
  Consecutive `<s>`/`<ins>` runs with no plain text between them coalesce
  into one record `{start, end, before, after}`, keyed `ME@<start>`. An
  insertion at offset p is `{start: p, end: p, before: ""}`. All prior
  `ME@` records within the gap's range are replaced by the derived set;
  records whose `before === ""` and `after === ""` are dropped. Existing
  audit notes are carried over by matching record start where possible.
  `save()` autosaves as today.
- **Undo.** Programmatic DOM mutation breaks native undo, so keep a
  session-only snapshot stack per gap (innerHTML + caret position before
  each applied input, capped). Ctrl+Z pops it; Ctrl+Y/Ctrl+Shift+Z redoes.
- **Invariant.** After any operation, concatenating (text nodes + `<s>`
  content) over the gap equals `DATA.text.slice(gapStart, gapEnd)`. The
  derivation asserts this and, on mismatch, discards the gap's DOM state
  and rebuilds it from records (fail-safe, console warning).

### Custom decision answers

- Stored in `state.answers[id]` as `{ custom: "<text>" }` (distinct from
  option-index / literal answers). `eff()`/`resolvedText()` return the
  custom text; existing redline rendering applies.
- Export/import: flows through answers JSON as-is. JSON/HTML-only, like
  `ME@` edits; the Excel path is unchanged and ignores custom answers.
- `generate` (generate.py): a `{custom}` answer for a decision group is
  validated (decision exists, group is `safe`, not in a designer note) and
  applied through the same replacement machinery as manual edits, with the
  group's span as the replace range, `_escape_manual_edit_text` for output
  escaping, action `"custom text"` in the redline log, and normal ADD/DEL
  markup in `--revisions` output. Counts as resolved. Invalid custom
  answers land in the unresolved report with a reason, never defaulted.
- `pruneStaleEdits` equivalent: a custom answer whose decision id no longer
  exists is dropped on import (console warning + panel notice, same as
  stale edits).

### Conflict rules (unchanged in spirit)

Manual edits live only in gaps, so they cannot overlap decisions, removed
tailoring blocks, or removed unit halves by construction. Imported edits
are still validated by `pruneStaleEdits` / `_invalid_edit_reason` exactly
as today. A decision with a custom answer is still a decision — inline
edits still cannot touch its span.

## Error handling

- Cross-gap or island-crossing operations: blocked, transient hint, no
  state change.
- Paste of rich content: text extracted, else blocked.
- Derivation invariant failure: gap rebuilt from records; edit lost with a
  console warning (never silent corruption of offsets).
- Import: stale/conflicting `ME@` records and unknown-decision custom
  answers dropped with count shown in the panel (existing notice reused).
- `generate`: malformed/overlapping `ME@` records and invalid custom
  answers go to the unresolved report, as today.

## Testing

- **Python (pytest, as the suite does today):**
  - `generate` custom-answer path: applied, escaped, redline action,
    revisions ADD/DEL, unresolved on invalid id/unsafe group/note overlap.
  - Export→generate round-trip fixture containing inline edits + a custom
    answer.
  - Static-source assertions on emitted HTML/JS: Edit toggle present,
    `beforeinput` handler wired, `onDocMouseUp`/select-and-replace absent,
    inline `<s class="me">`/`<ins class="me">` rendering present.
- **Manual browser checklist** (extends the pending Tasks 7/8 pass): type,
  delete forward/backward, selection delete, paste, Enter, undo/redo,
  island blocking + hint, review card revert, audit note, custom text set/
  remove, clean-view toggle, export/import round-trip, autosave reload.

## Out of scope

- Excel workbook support for custom answers or manual edits.
- Accept/reject per change inside the HTML page (SpecsIntact remains the
  accept/reject surface via `.revisions.sec`).
- Persisting edit-mode state or undo history across reloads.
- Rich text of any kind.
