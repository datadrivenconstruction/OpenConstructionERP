"""Tests for scripts/i18n.py on small fixture bundles in a tmp dir."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import i18n  # noqa: E402

EN = """// header
const resource = {
  "translation": {
    "boq.title": "Bill of quantities",
    "boq.add": "Add {{name}}",
    // --- section ---
    "cost.total": "Total",
    "cost.net": "Net"
  }
} as { translation: Record<string, string> };

export default resource;
"""

DE = """const resource = {
  "translation": {
    "boq.title": "Leistungsverzeichnis",
    "cost.total": "Summe",
  }
} as { translation: Record<string, string> };

export default resource;
"""


@pytest.fixture
def locales(tmp_path, monkeypatch):
    # CRLF on the English fixture proves line endings are preserved.
    (tmp_path / "en.ts").write_bytes(EN.replace("\n", "\r\n").encode())
    (tmp_path / "de.ts").write_bytes(DE.encode())
    monkeypatch.setattr(i18n, "LOCALES", tmp_path)
    return tmp_path


def run(*argv: str) -> int:
    return i18n.main(list(argv))


def test_get(locales, capsys):
    assert run("get", "boq.title", "--lang", "de", "en") == 0
    out = capsys.readouterr().out
    assert "de\tLeistungsverzeichnis" in out and "en\tBill of quantities" in out
    assert run("get", "nope", "--lang", "de") == 1


def test_add_set_rename_keep_rest_byte_identical(locales):
    en_before = (locales / "en.ts").read_bytes()
    de_before = (locales / "de.ts").read_bytes()

    assert run("add", "boq.remove", "--en", "Remove", "--de", "Entfernen") == 0
    en_lines = (locales / "en.ts").read_bytes().split(b"\n")
    # Placed after the last "boq." sibling, CRLF kept, nothing else touched.
    assert en_lines[5] == b'    "boq.remove": "Remove",\r'
    assert [ln for ln in en_lines if b"boq.remove" not in ln] == en_before.split(b"\n")
    de = (locales / "de.ts").read_text(encoding="utf-8")
    assert '    "boq.remove": "Entfernen",\n' in de

    assert run("set", "cost.net", "--lang", "en", 'Net "amount"') == 0
    en = (locales / "en.ts").read_bytes()
    assert b'"cost.net": "Net \\"amount\\""\r\n' in en  # no trailing comma kept as it was

    assert run("rename", "cost.total", "cost.gross") == 0
    assert i18n.Bundle("en").get("cost.gross") == "Total"
    assert i18n.Bundle("de").get("cost.gross") == "Summe"
    assert i18n.Bundle("de").get("cost.total") is None

    # Undo everything by hand and compare with the originals.
    assert run("rename", "cost.gross", "cost.total") == 0
    assert (locales / "de.ts").read_bytes().replace(b'    "boq.remove": "Entfernen",\n', b"") == de_before
    assert en_before.count(b"\n") + 1 == (locales / "en.ts").read_bytes().count(b"\n")


def test_add_after_last_entry_without_comma_and_unknown_namespace(locales):
    assert run("add", "zzz.new", "--en", "New") == 0
    en = (locales / "en.ts").read_bytes()
    assert b'"cost.net": "Net",\r\n    "zzz.new": "New",\r\n  }' in en


def test_add_existing_key_refused(locales):
    with pytest.raises(SystemExit):
        run("add", "boq.title", "--en", "x")


def test_missing(locales, capsys):
    assert run("missing", "--lang", "de") == 0
    out = capsys.readouterr()
    assert out.out.split() == ["boq.add", "cost.net"]
    assert run("missing", "--lang", "de", "--prefix", "cost.") == 0
    assert capsys.readouterr().out.split() == ["cost.net"]


def test_export_import_round_trip(locales, tmp_path, capsys):
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps(["boq.add", "cost.net", "boq.title"]), encoding="utf-8")
    out = tmp_path / "out.json"
    assert run("export", "--lang", "de", "--keys-from", str(keys), "--out", str(out), "--only-missing") == 0
    exported = json.loads(out.read_text(encoding="utf-8"))
    assert exported == {"boq.add": "Add {{name}}", "cost.net": "Net"}

    patch = tmp_path / "patch.json"
    patch.write_text(
        json.dumps({"boq.add": "{{name}} hinzufügen", "cost.net": "Netto", "boq.title": "LV {{x}}"}),
        encoding="utf-8",
    )
    assert run("import", "--lang", "de", str(patch)) == 0
    de = i18n.Bundle("de")
    assert de.get("boq.add") == "{{name}} hinzufügen"
    assert de.get("cost.net") == "Netto"
    assert de.get("boq.title") == "Leistungsverzeichnis"  # placeholder mismatch skipped
    capsys.readouterr()
    assert run("missing", "--lang", "de") == 0
    assert capsys.readouterr().out.strip() == ""
