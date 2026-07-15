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
6. **Per-decision custom text.** Custom text answers already exist end to
   end: the decision card's freeform input ("…or type replacement text")
   stores literal text in the answer, `resolvedText` renders it as
   `<s>original</s><ins>custom</ins>`, and `generate` applies it (action
   "custom text", `<DEL>/<ADD>` in revisions). What's added:
   - An **Edit text…** button on every decision card that prefills the
     freeform input with the decision's original bracket text and focuses
     it, so the user can tweak the locked span's text directly.
   - `submittal-review` cards gain the freeform input (generate already
     handles custom text for that kind).
   - No storage-format or generate changes.
7. **Edit mode forces redline view.** Entering edit mode switches the view
   to redline (the tracking must be visible to be editable); the view
   toggle is disabled while editing.
8. **Unsafe-group copy fix.** The unsafe-decision card currently says
   "select the text in the document and edit it directly instead" — advice
   that both the old and new conflict rules reject. New copy: "It is
   flagged in the unresolved report for manual editing in SI Editor after
   generation."

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

The DOM is a pure view; the `ME@` records in `state.edits` stay the single
source of truth at every keystroke. Each input event is computed against a
**run model** built from the records, the records are updated, and the one
affected gap is re-rendered with the caret restored. (This hybrid was
chosen over mutating `<ins>`/`<s>` nodes in place: since `beforeinput` is
`preventDefault()`-ed either way, re-rendering one gap costs nothing and
the state can never drift from the DOM.)

- **Run model (pure functions, no DOM).** A gap `[s, e)` plus its records
  expand to runs `{t: "o"|"d"|"i", text}` — original kept, deleted
  original, inserted. Invariant: concatenating o+d texts equals
  `text.slice(s, e)`. Operations are expressed in *display offsets*
  (positions in the concatenation of all run texts, which is exactly the
  visible redline text):
  - `opInsert(runs, at, text)` — an `at` inside a `d` run first moves to
    the run's end (replacement text follows its strikethrough); splices in
    an `i` run; caret lands after the inserted text.
  - `opDelete(runs, from, to)` — `o` portions in range become `d`; `i`
    portions are removed; `d` portions stay. Returns both the range start
    and end so callers place the caret: before the strikethrough for
    Backspace, after it for Delete/selection operations.
  - `deleteTarget(runs, caret, dir)` — the single character a collapsed
    Backspace/Delete targets, skipping over already-struck (`d`) runs;
    null at a gap boundary.
  - `runsToRecords(runs, gapStart)` — coalesces consecutive `d`/`i` runs
    into records `{start, end, before, after}` keyed `ME@<start>`;
    `before === after` records are dropped (typed-then-erased no-ops).
    Audit notes carry over from prior records matching on `start` +
    `before`.
- Edit mode sets `contenteditable` on each `.gap` span (not on `#doc`);
  islands stay non-editable. Editing is confined to one gap per operation.
- A `beforeinput` listener on `#doc` `preventDefault()`s everything and
  maps: `insertText`/`insertParagraph`/`insertLineBreak` (as `\n`)/
  `insertFromPaste` (plain text only) → insert; `deleteContentBackward`/
  `deleteContentForward`/`deleteByCut`/`deleteByDrag` → delete. All other
  input types are swallowed. A selection spanning two gaps, crossing a
  locked island, or an op intersecting an in-gap locked range: blocked +
  transient hint. Known limitation: IME composition is not supported
  (composition events are not cancelable); acceptable for English spec
  text.
- **In-gap locked ranges.** Plural `[s]` markers and designer-note
  brackets are decisions excluded from `ds`, so their spans are plain gap
  text — but `generate` rejects manual edits overlapping *any* scanned
  group. For parity they are rendered as non-editable tinted spans and ops
  intersecting them are blocked (closes a page/generate inconsistency that
  exists today).
- **Caret mapping.** Display offset ↔ DOM position by walking the gap's
  text nodes, skipping nav-anchor content (`contenteditable="false"`,
  zero-width in the model).
- **Undo.** Session-only stack of `{gap, records-before/after,
  caret-before/after}` per applied op (capped at 100); Ctrl+Z / Ctrl+Y or
  Ctrl+Shift+Z via keydown while in edit mode.

### Custom decision answers (existing mechanism, reused)

Custom text is already a first-class answer: literal (non-option) text in
`state.answers[id].answer` renders via `resolvedText`, exports in the
answers JSON, and `generate` applies it (`after = ans`, action
`"custom text"`, `_rev_wrap`'s `<DEL>before</DEL><ADD>after</ADD>` in
revisions). Unknown answer ids already fail loudly in `generate`. No
storage, export, or generate.py changes. The UI additions are only the
**Edit text…** prefill button and the freeform input on
`submittal-review` cards.

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

- **Pure-core unit tests via Node (pytest wrapper, skipped when `node`
  is not on PATH):** the run-model functions are emitted as a standalone
  DOM-free script block; a pytest harness writes them plus JS assertions
  to a temp file and runs `node` on it. Covers opInsert/opDelete/
  deleteTarget/runsToRecords round-trips, note carry-over, no-op dropping,
  and the o+d invariant.
- **Python (pytest, as the suite does today):**
  - `generate` custom-answer path on a `submittal-review` group: applied,
    revisions resolve/revert round-trip.
  - Export-shaped answers JSON containing inline-edit `ME@` records + a
    custom answer → `generate --revisions` round-trip fixture.
  - Static-source assertions on emitted HTML/JS: Edit toggle present,
    `beforeinput` handler wired, `onDocMouseUp`/select-and-replace absent,
    inline `<s class="me">`/`<ins class="me">` rendering present, updated
    unsafe-group copy.
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
