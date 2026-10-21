"""A decision page built with answers (`html --answers`) opens with them
loaded, so a reviewer sees prefill's answers without clicking Import."""

import json

import pytest

from specgen import secfile
from specgen.cli import main
from specgen.htmlpage import write_html
from specgen.manifest import build_manifest
from tests.test_annotation import MINI


def _data(html):
    start = html.index("const DATA = ") + len("const DATA = ")
    return json.loads(html[start:html.index(";\nconst PLURAL_KEY")])


def test_preload_is_embedded_with_its_own_storage_key(tmp_path):
    m = build_manifest(secfile.parse_source(MINI))
    payload = {"schema": "specgen.answers/2", "fingerprint": m["fingerprint"],
               "answers": {}, "profile": {"ARMY": "remove"}}
    write_html(m, tmp_path / "p.html", preload=payload)
    html = (tmp_path / "p.html").read_text(encoding="utf-8")
    data = _data(html)
    assert data["preload"] == payload
    assert len(data["preload_id"]) == 8          # a fresh build starts fresh
    assert "if (DATA.preload && !hadSaved) { importPayload(DATA.preload)" in html   # first open
    assert "Reset this page to the answers it was built with?" in html          # Clear all
    write_html(m, tmp_path / "plain.html")
    assert "preload" not in _data((tmp_path / "plain.html").read_text(encoding="utf-8"))


def _master(tmp_path):
    p = tmp_path / "m.SEC"
    p.write_bytes(MINI.encode(secfile.ENCODING))
    return p


def test_cli_html_answers(tmp_path):
    master = _master(tmp_path)
    fp = build_manifest(secfile.parse(master, tolerant=True))["fingerprint"]
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"fingerprint": fp, "answers": {}}), encoding="utf-8")
    assert main(["html", str(master), "-o", str(tmp_path / "p.html"), "--answers", str(a)]) == 0
    assert _data((tmp_path / "p.html").read_text(encoding="utf-8"))["preload"]["fingerprint"] == fp


@pytest.mark.parametrize("content", ['{"fingerprint": "other", "answers": {}}', "not json"])
def test_cli_html_refuses_answers_for_another_scan(tmp_path, content, capsys):
    master = _master(tmp_path)
    a = tmp_path / "a.json"
    a.write_text(content, encoding="utf-8")
    assert main(["html", str(master), "-o", str(tmp_path / "p.html"), "--answers", str(a)]) == 1
    assert "ERROR" in capsys.readouterr().out
    assert not (tmp_path / "p.html").exists()
