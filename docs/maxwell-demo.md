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

Our checks prove each output parses, round-trips byte for byte and is well formed. They do not prove that SpecsIntact accepts it. SpecsIntact is not installed on the build machine, so this step is manual. Use the files in `1-prefill/`:

- [ ] `23_64_10.sec` opens in SpecsIntact without errors or repair prompts.
- [ ] The tailored text reads correctly in 2.4.1 (Scroll), the compressor driver line (electric motor) and the condenser line (air-cooled condenser coil).
- [ ] The 7 removed subsections are gone, and the section's numbering and outline look right.
- [ ] Submittal verification passes, with no items pointing at removed subsections.
- [ ] Reference verification passes. The 12 removed references were only cited inside removed subsections.
- [ ] Only Air Force tailoring remains, and units are IP only.
- [ ] `23_64_10.revisions.sec` opens with the changes as tracked changes, red for deletions and green for insertions, and accepting all of them gives the same text as `23_64_10.sec`.
- [ ] Open bracket decisions (for example the condenser accessories list after the condenser line) still show as brackets for the engineer.

Note anything SpecsIntact flags with its message and the paragraph number. Each one becomes a fix or a known limit.
