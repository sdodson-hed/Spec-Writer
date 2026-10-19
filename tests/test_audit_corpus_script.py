import os
import subprocess
import sys
from pathlib import Path

from tests.test_tolerant_parse import NORSOK

ROOT = Path(__file__).resolve().parent.parent
GOOD = "<SEC><PRT><TTL>PART 1</TTL><TXT>Provide [a][b].</TXT></PRT></SEC>"


def _run(*args, env=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "audit_corpus.py"), *args],
        capture_output=True, text=True, env=env,
    )


def test_corpus_dir_argument_and_lowercase_ext(tmp_path):
    # WBDG ships lowercase .sec in per-division folders
    (tmp_path / "DIV01").mkdir()
    (tmp_path / "DIV01" / "01 42 00.sec").write_bytes(NORSOK.encode("windows-1252"))
    (tmp_path / "23 64 10.SEC").write_bytes(GOOD.encode("windows-1252"))
    r = _run(str(tmp_path))
    assert r.returncode == 0, r.stdout
    assert "DEFECT 01 42 00.sec" in r.stdout
    assert ("2 sections: 2 round-trip, 1 audit clean, 1 source defect, "
            "0 failing") in r.stdout


def test_env_var_and_failures(tmp_path):
    (tmp_path / "x.SEC").write_bytes(b"<SEC><TXT>[unbalanced</TXT></SEC>")
    (tmp_path / "y.SEC").write_bytes(b"<SEC><TXT><B>x</TXT></B></SEC>")
    r = _run(env={**os.environ, "SPECGEN_CORPUS": str(tmp_path)})
    assert r.returncode == 1
    assert "FAIL x.SEC" in r.stdout and "FAIL y.SEC" in r.stdout
    # x round-trips but has an unknown; y does not parse at all
    assert "2 sections: 1 round-trip, 0 audit clean, 0 source defects, 2 failing" in r.stdout


def test_missing_corpus_is_an_error(tmp_path):
    r = _run(str(tmp_path / "nope"))
    assert r.returncode == 1 and "no .SEC files" in r.stdout
