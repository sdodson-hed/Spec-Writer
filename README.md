# specgen — UFGS Spec Section Generator (Phase 0)

Tooling for the SpecsIntact automation project: parse UFGS master sections
(`.SEC`, SpecsIntact XML), round-trip them losslessly, and extract the
**decision manifest** — every bracket choice, fill-in blank, optional phrase,
tailoring option, submittal, and reference a section demands of a specifier.

## Status

- Lossless parser: **all 431 masters in the current WBDG release
  round-trip byte-identically** (Divisions 01 03 05 07 08 09 21 22 23 26 28
  31 33, UMRL July 2026); 430 audit clean. 01 42 00 ships a stray `</URL>`
  in its NORSOK entry: tolerant mode keeps it as raw text and `audit`
  reports it as a source defect (exit 2), not a pass.
  The earlier 56-master corpus (55 Division 23 + 26 20 00, UMRL April 2026)
  is in `masters/Specifications` on the shared drive.
- Stable anchors: answers are keyed by `<path>#<kind>:<hash8>[~n]`, not by
  positional `BRK-NNNN` ids, so they survive quarterly UFGS releases and
  CRLF/LF differences. Answers made on 03 30 00 (April 2026) carry 236 of
  244 decisions to the July 2026 copy; the other 8 are reported, not applied.
- Additive bracket lists: choice groups that are select-any lists
  ("[ single pole][, double pole][, and four-way]") render as checkboxes;
  connector-only spans ("[ or ]") are joiners, never options; kept items
  are rejoined with correct commas/and/or by `generate`. Mid-sentence
  choice groups demote "remove entirely" behind a confirmation.
- Decision manifests generated for the Maxwell pilot sections:
  - `23 64 10` Water Chillers, Vapor Compression Type (147 bracket groups)
  - `23 64 26` Chilled/Chilled-Hot/Condenser Water Piping Systems
- Completeness audit enforced corpus-wide: unknown bracket tokens and nested
  structure violations caught in CI (all 56 masters audit-clean).
- Markup signals surfaced: units (SI/IP), submittal-review groups, and
  markup-split conflicts all detectable and traceable in manifests and reports.
- XSD validation wired up but the official schema
  (`si.ksc.nasa.gov/sidownloads/xml/specsintactSEC.xsd`) was unreachable —
  drop it into `schema/` when obtainable (it ships with the SpecsIntact
  install, e.g. `C:\Program Files (x86)\SpecsIntact\...`).

## Usage

```
python -m specgen roundtrip "masters/23 64 10.SEC"   # byte-identical check
python -m specgen manifest  "masters/23 64 10.SEC" -o out/manifest.json
python -m specgen report    "masters/23 64 10.SEC" -o out/report.md
python -m specgen validate  "masters/23 64 10.SEC"  [--schema path.xsd]
python -m specgen answers   "masters/23 64 10.SEC" -o out/answers.xlsx
python -m specgen html      "masters/23 64 10.SEC" -o out/decisions.html
python -m specgen generate  "masters/23 64 10.SEC" \
    --answers out/answers.xlsx -o out/generated/23_64_10.sec   # or .json
python -m specgen audit     "masters/23 64 10.SEC"               # completeness gate
python -m specgen generate  ... --revisions   # also emit .revisions.sec (SI tracked changes)
python -m specgen generate  ... --strict      # refuse if any answer no longer resolves
python scripts/audit_corpus.py [corpus_dir]   # audit + round-trip every .SEC under a dir
                                              # (default $SPECGEN_CORPUS, else masters/Specifications)
python scripts/build_project.py <dir> <masters...>   # per-project batch + index
```

## The answer-file workflow (no platform integration required)

1. Emit the decision surface: `html` builds a single-file interactive page
   (open in any browser, no server; answers autosave locally; Export
   downloads an answers JSON). `answers` builds the same thing as an Excel
   workbook for engineers who prefer a spreadsheet. Both cover: choices,
   blanks, optionals, duplicate propagation, and a Project Profile block
   (tailoring keep/remove, plural [s] markers).
   The page also has an Edit mode: click Edit and type directly in the
   document like a tracked-changes Word doc — insertions show green,
   deletions show red strikethrough, and every change exports as an ME@
   record that `generate` applies and `--revisions` renders as native
   SpecsIntact ADD/DEL markup.
2. An engineer — or, later, the Hedral platform — fills in the answers.
3. `generate` accepts either the .xlsx or the exported .json (they are
   provably equivalent) and applies them: resolves brackets, strips removed
   tailoring blocks, and emits the tailored `.sec` plus `.redline.md`
   (human-readable change log), `.redline.json` (machine audit trail), and
   `.unresolved.md` (decisions needing engineer input). Output is verified
   (parse, round-trip, well-formed) before it is written; unanswered
   decisions are never defaulted. Structurally unsafe groups (bracket spans
   crossing markup unevenly) are flagged for manual editing, never touched.

Answer keys. Exports (`schema: specgen.answers/2`) and workbooks key each
bracket answer by its anchor: the PRT/SPT title path, the decision kind, and
a hash of its option text, e.g. `PART 2/REFRIGERANT#blank:2477bc03`. The
`BRK-NNNN` id and option texts ride along for display. When the master
changes (a new UFGS release), every anchor that still matches applies; an
anchor that no longer matches goes to `.unresolved.md` as "master changed:
decision not found" with the option text it was answered against, and is
applied to nothing. Older answer files keyed on `BRK-NNNN` still load when
their fingerprint matches this master. `--strict` turns any non-resolving
answer or fingerprint mismatch into a hard stop.

Shared-drive workflow: `build_project.py` sets up a per-project layout
(`decisions/`, `answers/`, `generated/`, `index.html`) that organizes manifests,
filled-in answers, and generated outputs. Export from the HTML or Excel
interface produces an answers file that explicitly marks any unanswered
decisions, so the engineer can verify completeness before generation. When
`generate` is invoked with `--revisions`, both `.sec` and `.revisions.sec` are
written; the `.revisions.sec` file opens directly in SpecsIntact with native
red/green tracked-change markup, bridging the workflow back to the existing QA
tools.

Demo: `python scripts/maxwell_demo.py` fills the 23 64 10 workbook with the
Maxwell AFB values (air-cooled, electric drive, scroll, Air Force tailoring)
and the `generate` run above produces the draft section.

## Layout

- `specgen/secfile.py` — raw-token parser/serializer (byte-identical output
  is guaranteed by keeping every token's source text; no XML library rewrites)
- `specgen/manifest.py` — flattens text with a char→location map, scans for
  literal bracket groups, extracts TAI/SUB/RID/NTE structure
- `masters/` — local copies of pilot sections (source of truth is
  `G:\Shared drives\Hedral-Shared\...\Mech\Specifications`; never edited)
- `out/` — generated manifests and reports

## Known heuristic limits (fine for Phase 0, resolved at annotation time)

- Adjacent bracket spans are grouped as one choice set; UFGS sometimes butts
  unrelated brackets together (e.g. an optional submittal item directly
  followed by a choice set), so some groups need manual splitting.
- Plural markers like `Chiller[s]` classify as `optional` — trivial to
  resolve (quantity > 1) but they inflate the optional count.

## Next (Phase 1/2)

1. Get the XSD from a SpecsIntact install; make `validate` part of CI.
2. Annotation layer: map each manifest decision ID for 23 64 10 to a
   design-data field or rule (chiller schedule, system alternative, project
   attributes). Deterministic at generation time.
3. Generator: apply an annotation + design data to the master, emit the job
   copy, unresolved-decision list, and redline log.
4. Open a generated file in SpecsIntact on the AFCEC-mandated version and run
   its QA reports — the external acceptance gate.
