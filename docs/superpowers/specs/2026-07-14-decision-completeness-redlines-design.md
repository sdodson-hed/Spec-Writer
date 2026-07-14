# Decision Completeness + Redlines — Design

**Date:** 2026-07-14
**Status:** Approved pending user review
**Scope:** specgen scanner, new audit command, HTML decision page, generator revisions output, pilot workflow.

## Problem

The HTML decision page must be trusted to surface **every** input a UFGS master
demands of a specifier, and to make unanswered inputs impossible to miss. A
survey of all 55 Division 23 masters (`masters/Specifications`) found input
signals beyond the bracket patterns the scanner currently handles, plus traps
that produce phantom decisions. Separately, engineers trust SpecsIntact's
red/green tracked-changes display; our output should meet them there.

## Goals

1. **Surfacing completeness** — every decision signal in a `.SEC` appears in
   the HTML, enforced by a machine-checked invariant, not a one-time survey.
2. **Resolution completeness** — the page and export make unanswered
   decisions obvious; nothing is ever silently defaulted.
3. **Redlines** — live red/green feedback in the HTML, and native SpecsIntact
   revision markup in the generated output.

## Non-goals (explicitly out of scope)

- Free-text editing in the HTML with tracked changes (separate future spec).
- Annotation layer / design-data pre-fill (Phase 2 in README; this design
  keeps the JSON format compatible so pre-fill slots in later).
- Contractor form blanks (118 bare `_____` in test-report forms) are
  excluded by rule, not surfaced.

## Corpus survey findings (evidence base)

| Signal | Count / spread | Current handling |
|---|---|---|
| `[text]` optional | ubiquitous | surfaced |
| `[a][b]` adjacent choice | 1,621 butted + 1,653 one-space | surfaced |
| `[_____]` blank | 5,160 | surfaced |
| `[s]` plural | 99 in 15 files | surfaced (Project Profile) |
| Nested brackets | 482 | surfaced (embedded) |
| Submittal classification `[; G[, [_____]]]` | 588 G + 27 S | generic group — **needs typed handling** |
| Tailoring `<TAI OPT="...">` | 1,508 in 53 files | surfaced (Project Profile) |
| `<MET>/<ENG>` unit pairs | ~6,900 in 53 files | **not surfaced** |
| Brackets split only by markup `]</SPT>[` etc. | ~18 | **wrongly split into separate groups** |
| Brackets inside `<NTE>` notes | 2,215 notes; 1 unbalanced `[` (23 09 23.01) | **wrongly scanned; can abort a group** |
| Bare `_____` outside brackets | 118 | ignored (correct; make it a named rule) |

Adjacent brackets are never newline-separated in this corpus. Bracket counts
balance in 54/55 files; the one imbalance is quoted text inside a note.

## Design

### 1. Scanner extensions (`specgen/scan.py`)

- **Note masking.** `text_stream()` marks characters inside `<NTE>...</NTE>`
  non-scannable while preserving offsets (char→source map unchanged; serializer
  untouched, so round-trip stays byte-identical). Note brackets can never form
  groups. Note text is captured and attached as guidance to the decision
  group(s) that follow it.
- **Markup-split adjacency.** The adjacency rule (spaces/tabs only) also
  accepts render-invisible markup between spans: `</SPT>`, `<TAI ...>`,
  `</TAI>`, `</MET>`, `</ENG>`. Structural tags (`<OLI>`, headers, table
  cells) still split; uneven groups keep `safe=False`.
- **Submittal-classification recognizer.** Groups matching
  `[; G[, [_____]]]` (G or S, optional `<TAI>` wrapping) classify as
  `kind="submittal-review"` with two sub-decisions: reviewer flag
  keep/remove, reviewer-office fill-in. Labeled with the parent `<SUB>` item.
- **Unit-system decision.** One synthetic project-level decision
  `UNITS: SI | Imperial` resolves every `<MET>/<ENG>` pair in the section.
  Pairs are not individual decisions.

### 2. Coverage audit (`specgen audit` + `scripts/audit_corpus.py`)

Invariant: every decision signal is attributed to exactly one bucket —
`surfaced`, `excluded:<named-rule>`, or `unknown`.

- Walks every `[`, `]`, `_+` run, `<TAI>`, `<MET>/<ENG>`, `<SUB>`
  classification in the file.
- Named exclusion rules: `note-text`, `contractor-form-blank`
  (bare `_+` of ≥3 outside brackets), `header-metadata` (`<DTA>` before SCOPE).
- Any `unknown` → non-zero exit with file/offset/context excerpt.
- Emits per-section coverage table (counts per bucket per signal type).
- `scripts/audit_corpus.py` runs all 55 masters; rerun on every UFGS revision.
- `html` and `generate` refuse sections with `unknown`s (`--force` downgrades
  to a loud warning).

### 3. HTML decision page (`specgen/htmlpage.py`)

- **Live redline.** Decision spans are wrapped at build time. Unanswered:
  bracketed, amber. Answered: rejected options red strikethrough, chosen/
  filled text green underline. Removed tailoring blocks collapse to an
  expandable red-struck summary ("▸ 14 lines removed — NIAGARA FRAMEWORK").
  Redline state restores from localStorage on reopen.
- **Project Profile** gains Units (SI/Imperial); answering swaps the document
  view (other side red-struck).
- **Submittal-review decisions** render as a labeled pair under their
  submittal item name.
- **Export gate (warn + export).** Persistent "N of M unanswered" counter;
  click scrolls to next unanswered. Export lists unanswered items, one
  confirm, and records them as explicit `unanswered` in the JSON so
  `generate` emits them in `.unresolved.md`. Never defaulted.
- **Import answers.** Page can import a previously exported answers JSON —
  localStorage is per-browser, the JSON is the durable artifact; the page
  nags to export.
- **Note guidance.** Each decision shows its governing designer note,
  collapsed by default.

### 4. Generator (`specgen/generate.py`)

- `--revisions` flag: emit `.revisions.sec` alongside the clean `.sec`, with
  every change wrapped in SpecsIntact revision markup
  `<DEL>rejected</DEL><ADD>chosen</ADD>` (pure deletions/additions
  degenerate naturally).
- Verification extends to the revisions file: it must parse and round-trip;
  resolving revisions (drop `<DEL>` content, keep `<ADD>` content) must
  reproduce the clean output byte-identically; reverting revisions (keep
  `<DEL>` content, drop `<ADD>` content) must reproduce the master.
- `.redline.md` / `.redline.json` and `.revisions.sec` are generated from the
  same diff records — they cannot drift apart.

### 5. Pilot workflow (no platform integration)

Per-project folder on the shared drive
(`G:\Shared drives\Hedral-Shared\...`):

```
<project>/
  decisions/   # generated HTML, one per section in the job (not all 55)
  answers/     # engineers drop exported .answers.json here
  generated/   # .sec, .revisions.sec, .redline.md, .unresolved.md
  index.html   # project page: sections + per-section answer progress
```

Engineer opens the HTML locally (no server), answers, exports into
`answers/`; a batch `generate` run rebuilds everything whose answers changed.
Phase 2 pre-fill later turns this from data entry into exception review —
same page, same JSON, pre-filled.

## Error handling

- Unbalanced brackets outside notes: group abandoned (current behavior) but
  now always reported by `audit` as `unknown` rather than silently dropped.
- Structurally unsafe groups (`safe=False`): flagged for manual editing,
  never spliced (unchanged).
- Unanswered decisions: carried as explicit `unanswered` through JSON →
  `.unresolved.md`; generation never defaults.

## Testing

- **Corpus regression:** `audit_corpus.py` green (zero `unknown`) on all 55
  masters; round-trip stays byte-identical for all 55.
- **Unit tests from real excerpts:** the 23 09 23.01 unbalanced note; a
  `]</SPT>[` split pair; the `[; G[, [_____]]]` idiom; a `<MET>/<ENG>` pair;
  revisions resolve/revert identities.
- **Phase C (external gate, later):** open `.revisions.sec` in SpecsIntact on
  the AFCEC-mandated version; Bracket Verification report shows zero
  remaining brackets; revisions display red/green natively.

## Decisions log

- Guarantee: both surfacing and resolution completeness.
- Surface: units, submittal classifications, markup-split merges. Exclude
  contractor form blanks by rule.
- Notes: excluded from scan, shown as guidance.
- Export: warn + export (no hard block).
- Redlines: live HTML redline + `--revisions` output. Free-text editing
  deferred to its own spec.
- Completeness strategy: coverage-audit invariant now; SpecsIntact QA
  reports as external acceptance gate later (A + C).
