"""``scripts/i18n.py remove`` deletes a key from every bundle and leaves every other line byte for byte."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"

BUNDLE = (
    "const x = {\r\n"
    "  translation: {\r\n"
    '    "a.keep": "Keep",\r\n'
    '    "a.drop": "Drop",\r\n'
    '    "b.keep": "Also {{n}}",\r\n'
    '    "b.drop": "Last"\r\n'
    "  },\r\n"
    "};\r\n"
    "export default x;\r\n"
)


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    sys.modules.pop("i18n", None)
    import i18n

    for lang in ("en", "de"):
        (tmp_path / f"{lang}.ts").write_bytes(BUNDLE.encode())
    monkeypatch.setattr(i18n, "LOCALES", tmp_path)
    yield i18n, tmp_path
    sys.modules.pop("i18n", None)


def test_remove_deletes_the_keys_in_every_bundle(cli):
    i18n, root = cli
    assert i18n.main(["remove", "a.drop", "b.drop"]) == 0
    for lang in ("en", "de"):
        text = (root / f"{lang}.ts").read_bytes().decode()
        assert '"a.drop"' not in text and '"b.drop"' not in text
        assert text == BUNDLE.replace('    "a.drop": "Drop",\r\n', "").replace('    "b.drop": "Last"\r\n', "")
        b = i18n.Bundle(lang)
        assert b.get("a.keep") == "Keep" and b.get("b.keep") == "Also {{n}}"


def test_remove_of_an_absent_key_changes_nothing_and_says_so(cli):
    i18n, root = cli
    assert i18n.main(["remove", "nope"]) == 1
    assert (root / "en.ts").read_bytes().decode() == BUNDLE


def test_import_takes_a_plural_form_english_does_not_have(cli, tmp_path):
    import json

    i18n, root = cli
    (root / "en.ts").write_bytes(BUNDLE.replace('"b.drop": "Last"', '"n_other": "{{count}} days"').encode())
    (root / "ru.ts").write_bytes(BUNDLE.encode())
    patch = tmp_path / "ru.json"
    patch.write_text(json.dumps({"n_few": "{{count}} дня", "n_many": "{{count}} дней", "zz_few": "x"}), "utf-8")
    assert i18n.main(["import", "--lang", "ru", str(patch)]) == 0
    b = i18n.Bundle("ru")
    assert b.get("n_few") == "{{count}} дня" and b.get("n_many") == "{{count}} дней" and b.get("zz_few") is None
