"""scripts/maxwell_demo.py runs end to end and tells the story the walkthrough
(docs/maxwell-demo.md) describes."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _demo():
    spec = importlib.util.spec_from_file_location("maxwell_demo", ROOT / "scripts" / "maxwell_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_demo_builds_both_scenarios(tmp_path, capsys):
    demo = _demo()
    assert demo.main(tmp_path) == 0
    stem = demo.STEM
    for folder in ("1-prefill", "2-schedule-revision"):
        for suffix in (".decisions.html", ".sec", ".revisions.sec", ".redline.md",
                       ".unresolved.md", ".answers.json", ".answers.prefill.md"):
            assert (tmp_path / folder / f"{stem}{suffix}").is_file(), (folder, suffix)
    out = capsys.readouterr().out
    assert "1-prefill: 7 subsections removed" in out and "80 decisions left" in out
    assert "2-schedule-revision: 6 subsections removed" in out

    p2 = json.loads((tmp_path / "2-schedule-revision" / f"{stem}.answers.json").read_text(encoding="utf-8"))
    outcomes = sorted(r["outcome"] for r in p2["prefill"]["merge"])
    assert outcomes == ["conflict", "updated", "updated", "updated"]
    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "2.6.10 Air-Cooled Condenser Coil" in index and demo.CONDENSER_TEXT in index

    # the page opens with the answers it was built with
    page = (tmp_path / "2-schedule-revision" / f"{stem}.decisions.html").read_text(encoding="utf-8")
    assert '"preload"' in page and demo.CONDENSER_TEXT in page
