# Maxwell demo walkthrough

UFGS 23 64 10 (Water Chillers, Vapor Compression Type) tailored for Maxwell AFB from the ACC-1 line of the 35% air-cooled chiller schedule.

```
python scripts/maxwell_demo.py
```

The script writes `out/maxwell-demo/` and prints a one-line summary per scenario. Open `out/maxwell-demo/index.html` in a browser. It links every file below. The pages run from disk, with no server.

## 1. The schedule as issued (`1-prefill/`)

`prefill` reads `projects/maxwell/design-data.json` through `annotations/23 64 10.yaml`. It answers 13 of the 14 rules. `generate --strict --revisions` then writes the tailored section.

| What | Result |
|---|---|
| Compressor | Scroll, in 2.4.1 and in the submittal list |
| Driver | Electric motor |
| Condenser | Air-cooled condenser coil |
| Subsections removed | 7: centrifugal chiller, split-system chiller, rotary screw and centrifugal compressors, gas-engine driver, water-cooled condenser coil, cooling tower |
| Tailoring | Air Force kept, Army and Navy removed (33 blocks) |
| Units | IP |
| Cleanup | 2 submittal items and 12 references only the removed subsections used |
| Left for the engineer | 80 decisions, listed in `23_64_10.unresolved.md` |

What to look at:

1. `23_64_10.decisions.html` opens with prefill's answers loaded. Each answer is colored by its source. Blue means the schedule and indigo means a project rule (agency, units). The legend is under the decision panel. Click a colored answer to see where it came from, for example `ACC-1.compressor_type = SCROLL`.
2. 2.6.12 Heat Recovery Condenser Coil has an amber "?" in the outline. Prefill could not decide it, because the design data has no `bod.heat_recovery`. It stays in the section until someone answers it, and the "?" says why.
3. `23_64_10.answers.prefill.md` lists each rule, what it answered and from which field.
4. `23_64_10.redline.md` lists every change, and `23_64_10.revisions.sec` holds the same changes as SpecsIntact tracked changes.

## 2. A schedule revision after engineer review (`2-schedule-revision/`)

This scenario shows what happens when the design changes after an engineer has worked on the section.

1. An engineer reviews scenario 1. The script writes two answers the way the decision page would export them, and nothing else is scripted:
   - the condenser line rewritten as "Air-cooled condenser coil with factory-applied coil coating", which is an override of prefill's answer
   - 2.6.12 Heat Recovery Condenser Coil kept, an answer prefill had left open

   The reviewed file is kept as `23_64_10.reviewed.answers.json`.
2. The schedule changes: ACC-1 becomes `WATER-COOLED SCROLL` (`design-data.json` in the folder).
3. `prefill` runs again on the reviewed file and merges. The table on the index page lists what moved:
   - 2.6.10 Air-Cooled Condenser Coil goes. 2.6.11 Water-Cooled Condenser Coil and 2.10.3 Cooling Tower come back.
   - The engineer's condenser line is now a conflict. The engineer wrote it for an air-cooled coil, and the schedule now says water-cooled. Prefill does not overwrite it, and generate doesn't use it either.
   - The engineer's heat recovery answer and note are untouched.
4. `generate` leaves the condenser line open. `23_64_10.unresolved.md` shows both values. Generating with `--strict` would refuse until the conflict is resolved.

What to look at:

1. Open `23_64_10.decisions.html`. The header shows "1 conflict" in red.
2. Click Next unanswered. It goes to the conflict first. The condenser line has a dashed red outline, and the panel shows the engineer's text, prefill's new value and where that value came from.
3. Click Keep mine or Take prefill. The conflict count clears. Export answers, then run `generate` on the exported file, and the choice applies.

The pages save your clicks in the browser. Clear all resets a page to the answers it was built with.

## 3. SpecsIntact acceptance (step 8, manual)

Our checks prove each output parses, round-trips byte for byte and is well formed. They do not prove that SpecsIntact accepts it, so this step is manual.

Test SpecsIntact against its own release. The copy of 23 64 10 in SpecsIntact's library (`Documents\SpecsIntactWD\Masters\UFGS`) is newer than `masters/`: it has the July 2026 reference update. All 14 annotation rules match it, and the demo's answers carry over to it with none lost. Build the demo from it, reading it only:

```
python scripts/maxwell_demo.py --master "%USERPROFILE%\Documents\SpecsIntactWD\Masters\UFGS\23 64 10.SEC" --out out/maxwell-demo-si
```

Then, in SpecsIntact 5.7:

1. New Job from the UFGS master with section 23 64 10. SpecsIntact adds 01 33 00 and 01 42 00 itself. When a section is pulled into a job, SpecsIntact adds table styles and re-wraps reference lines, but it applies no tailoring.
2. With the editor closed, back up the job's `pulldata\23 64 10.SEC` and replace it with `out/maxwell-demo-si/1-prefill/23_64_10.sec`, keeping SpecsIntact's file name.
3. Open the section. The Tailoring Options dialog lists AIR FORCE and NAVY, the options on the one shared block that is left. Click OK, and do not save on close.
4. Process > Reference Processing: Reconcile references, UMRL, run once with Remove unused references off and once with it on. Reports go to `prntdata\REFVER.RPT` and `TTLDIFFS.RPT` and do not open by themselves.
5. Process > Export Submittal Register, comma-delimited, to the job's `Exports` folder.
6. Repeat step 2 with `23_64_10.revisions.sec` and open it.

Check which reference list SpecsIntact has first (`%APPDATA%\SpecsIntact\umrl\locUMRLDate.txt`). Run the reference checks against the list the section cites ("References are in agreement with UMRL dated ..."), taking SpecsIntact's offer to download a newer one if needed. It keeps the old files as `umrlOld.ref` and `umslold.lst`.

### Results, 2026-10-22 (SpecsIntact 5.7.0.248, UFGS Aug 2026)

| Check | Result |
|---|---|
| `23_64_10.sec` opens without errors or repair prompts | Pass |
| 2.4.1 and the submittal list say Scroll; driver line electric motor; condenser line air-cooled condenser coil | Pass |
| Removed subsections gone, numbering closes up (old 2.5 Split-System gone, 2.5 is Chiller Components) | Pass |
| Only the shared Air Force/Navy block remains (Tailoring Options lists no ARMY) | Pass |
| Open decisions (heat recovery condenser, receiver, economizer; field acceptance test plan) stay bracketed | Pass |
| Reference Verification Report and Reference Title Report: "ALL REFERENCES HAVE BEEN VERIFIED" | Pass; reconciling left the file byte-identical |
| Remove unused references removes nothing | Pass; file byte-identical |
| Control: our file plus AHRI 450 (unused) | SpecsIntact removed exactly AHRI 450; the result is byte-identical to ours, so its cleanup and ours agree byte for byte |
| The same reference checks after updating SpecsIntact's lists from UMRL 2025.10.15 to 2026.07.15, the list the section cites | Pass; file byte-identical. All 14 listed references match the new list's titles and dates (12 of 14 matched the old one) |
| Submittal register: 22 items for 23 64 10, each mapped to a paragraph | Pass. Against the master's 25: Centrifugal and Split-System removed by cleanup, Posted Instructions and the ", [_____]" reviewer blanks were Army tailoring |
| `23_64_10.revisions.sec` opens; deletions show red strikethrough and the navigator labels removed subsections "(DELETED)" | Pass |
| Open, save without edits, close | Harmless. SpecsIntact re-wraps lines and restyles the title-block table (adds a style, narrows its two columns from 366 to 225); with those set aside the file is identical to ours. Our parser reads the saved file and round-trips it with no defects |

Notes from the run:

- Choices produce deletions only. Picking "Scroll" deletes the brackets and the other options, and the kept word stays plain. Green insertions appear only for filled blanks and hand edits, which this demo has none of.
- The editor has no accept-all command that we found. `generate` already accepts every change itself and checks that the result equals `23_64_10.sec` before writing either file.
- In revision view a deleted subsection keeps its number, so 2.4.2 appears twice (the deleted Centrifugal and the next one).
- The editor display hid SI values in designer notes ("500 tons" only). The file still has "1760 kW"; we never edit notes.
