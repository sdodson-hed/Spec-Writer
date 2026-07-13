# specgen — UFGS Spec Section Generator (Phase 0)

Tooling for the SpecsIntact automation project: parse UFGS master sections
(`.SEC`, SpecsIntact XML), round-trip them losslessly, and extract the
**decision manifest** — every bracket choice, fill-in blank, optional phrase,
tailoring option, submittal, and reference a section demands of a specifier.

## Status

- Lossless parser: **all 55 Division 23 masters round-trip byte-identically**
  (Nov 2025 UFGS revision, UMRL April 2026).
- Decision manifests generated for the Maxwell pilot sections:
  - `23 64 10` Water Chillers, Vapor Compression Type (147 bracket groups)
  - `23 64 26` Chilled/Chilled-Hot/Condenser Water Piping Systems
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
```

## The answer-file workflow (no platform integration required)

1. Emit the decision surface: `html` builds a single-file interactive page
   (open in any browser, no server; answers autosave locally; Export
   downloads an answers JSON). `answers` builds the same thing as an Excel
   workbook for engineers who prefer a spreadsheet. Both cover: choices,
   blanks, optionals, duplicate propagation, and a Project Profile block
   (tailoring keep/remove, plural [s] markers).
2. An engineer — or, later, the Hedral platform — fills in the answers.
3. `generate` accepts either the .xlsx or the exported .json (they are
   provably equivalent) and applies them: resolves brackets, strips removed
   tailoring blocks, and emits the tailored `.sec` plus `.redline.md`
   (human-readable change log), `.redline.json` (machine audit trail), and
   `.unresolved.md` (decisions needing engineer input). Output is verified
   (parse, round-trip, well-formed) before it is written; unanswered
   decisions are never defaulted. Structurally unsafe groups (bracket spans
   crossing markup unevenly) are flagged for manual editing, never touched.

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
