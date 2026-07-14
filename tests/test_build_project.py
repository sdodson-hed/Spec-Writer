import json
import subprocess
import sys
from pathlib import Path

from specgen import secfile

SRC = "<SEC><SCN>SECTION 99 00 00</SCN><STL>TEST</STL><TXT>[a][b] and [_____].</TXT></SEC>"


def test_build_project(tmp_path):
    master = tmp_path / "99 00 00.SEC"
    master.write_bytes(SRC.encode(secfile.ENCODING))
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "answers").mkdir()
    (proj / "answers" / "99 00 00.answers.json").write_text(
        json.dumps({"answers": {"BRK-0001": {"answer": "1"}}}), encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, "scripts/build_project.py", str(proj), str(master)],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert (proj / "decisions" / "99 00 00.decisions.html").exists()
    assert (proj / "generated" / "99 00 00.sec").exists()
    index = (proj / "index.html").read_text(encoding="utf-8")
    assert "99 00 00" in index and "1 unresolved" in index
