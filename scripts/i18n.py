#!/usr/bin/env python3
"""Canonical CLI for the locale bundles in ``frontend/src/app/locales/<lang>.ts``.

The bundles are 4-9 MB each, so nobody (human or agent) should open or edit
them by hand. Use this tool instead:

    python scripts/i18n.py get KEY [--lang de ru]
    python scripts/i18n.py add KEY --en "Text" [--de "Text"] [--fr "Text"]
    python scripts/i18n.py set KEY --lang de "Text"
    python scripts/i18n.py missing --lang de [--prefix boq.]
    python scripts/i18n.py rename OLD NEW
    python scripts/i18n.py export --lang de --keys-from keys.json [--out out.json]
    python scripts/i18n.py import --lang de patch.json [--force]

Edits are line based: only the touched lines change, the rest of the file stays
byte-identical (line endings, comments, key order included). The span of the
``translation`` object comes from ``check_i18n_key_nesting.translation_span``,
the parser the nesting gate already trusts. A new key is placed right after the
last existing key of the same namespace (longest dotted prefix), so related keys
stay together; with no namespace match it goes at the end of the object.

``export`` writes ``{key: english_text}`` for the requested keys (the source a
translator works from); ``import`` takes ``{key: translated_text}``, updates the
key when it exists and adds it otherwise. ``import`` refuses a value whose
``{{placeholder}}`` set differs from English unless ``--force`` is given.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_i18n_key_nesting import LOCALES, NOT_LOCALES, translation_span  # noqa: E402

_KEY_LINE = re.compile(rb'^(\s*)"((?:[^"\\]|\\.)*)":\s*(.*?)(,?)\s*$')
_PLACEHOLDER = re.compile(r"\{\{\s*([^}\s]+?)\s*(?:,[^}]*)?\}\}")


class Bundle:
    """One locale file held as a list of byte lines (split on ``\\n`` only)."""

    def __init__(self, lang: str) -> None:
        self.lang = lang
        self.path = LOCALES / f"{lang}.ts"
        if not self.path.is_file():
            raise SystemExit(f"no bundle for language '{lang}': {self.path}")
        self.lines = self.path.read_bytes().split(b"\n")
        self.cr = b"\r" if self.lines and self.lines[0].endswith(b"\r") else b""
        span = translation_span(self.lines)
        if span is None:
            raise SystemExit(f"{self.path.name}: no translation object")
        self.start, self.end = span
        self.index: dict[str, int] = {}
        self.order: list[tuple[int, str]] = []
        self._scan()

    def _scan(self) -> None:
        self.index = {}
        self.order = []
        for i in range(self.start + 1, self.end):
            match = _KEY_LINE.match(self.lines[i])
            if match:
                key = match.group(2).decode("utf-8")
                self.index.setdefault(key, i)
                self.order.append((i, key))

    def get(self, key: str) -> str | None:
        i = self.index.get(key)
        if i is None:
            return None
        raw = _KEY_LINE.match(self.lines[i]).group(3).decode("utf-8")  # type: ignore[union-attr]
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    def _line(self, indent: bytes, key: str, value: str) -> bytes:
        body = f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)},"
        return indent + body.encode("utf-8") + self.cr

    def set(self, key: str, value: str) -> None:
        i = self.index[key]
        match = _KEY_LINE.match(self.lines[i])
        assert match is not None
        comma = match.group(4)
        new = self._line(match.group(1), key, value)
        if not comma:
            new = new[: len(new) - len(self.cr) - 1] + self.cr
        self.lines[i] = new

    def _anchor(self, key: str) -> int:
        parts = key.split(".")
        for n in range(len(parts) - 1, 0, -1):
            prefix = ".".join(parts[:n]) + "."
            for i, existing in reversed(self.order):
                if existing.startswith(prefix):
                    return i
        return self.order[-1][0] if self.order else self.start

    def add(self, key: str, value: str) -> None:
        anchor = self._anchor(key)
        indent = b"    "
        match = _KEY_LINE.match(self.lines[anchor])
        if match:
            indent = match.group(1).replace(b"\r", b"")
            if not match.group(4):
                text = self.lines[anchor].rstrip()
                self.lines[anchor] = text + b"," + self.cr
        self.lines.insert(anchor + 1, self._line(indent, key, value))
        self.end += 1
        self._scan()

    def rename(self, old: str, new: str) -> None:
        i = self.index[old]
        match = _KEY_LINE.match(self.lines[i])
        assert match is not None
        old_q = json.dumps(old, ensure_ascii=False).encode("utf-8")
        new_q = json.dumps(new, ensure_ascii=False).encode("utf-8")
        line = self.lines[i]
        pos = line.find(old_q)
        self.lines[i] = line[:pos] + new_q + line[pos + len(old_q) :]
        self.index[new] = self.index.pop(old)
        self.order = [(n, new if k == old else k) for n, k in self.order]

    def save(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_bytes(b"\n".join(self.lines))
        os.replace(tmp, self.path)


def all_langs() -> list[str]:
    return sorted(p.stem for p in LOCALES.glob("*.ts") if p.name not in NOT_LOCALES)


def _placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def cmd_get(args: argparse.Namespace) -> int:
    langs = args.lang or all_langs()
    rc = 0
    for lang in langs:
        value = Bundle(lang).get(args.key)
        if value is None:
            print(f"{lang}\t<missing>")
            rc = 1
        else:
            print(f"{lang}\t{value}")
    return rc


def cmd_add(args: argparse.Namespace) -> int:
    values = {lang: getattr(args, lang) for lang in all_langs() if getattr(args, lang, None)}
    if "en" not in values:
        raise SystemExit("add needs --en")
    for lang, text in values.items():
        bundle = Bundle(lang)
        if args.key in bundle.index:
            raise SystemExit(f"{lang}: key '{args.key}' already exists (use set)")
        bundle.add(args.key, text)
        bundle.save()
        print(f"{lang}: added {args.key} at line {bundle.index[args.key] + 1}")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    bundle = Bundle(args.lang)
    if args.key not in bundle.index:
        raise SystemExit(f"{args.lang}: key '{args.key}' not found (use add)")
    bundle.set(args.key, args.value)
    bundle.save()
    print(f"{args.lang}: set {args.key}")
    return 0


def cmd_missing(args: argparse.Namespace) -> int:
    en = Bundle("en")
    other = Bundle(args.lang)
    keys = [k for _, k in en.order if k not in other.index and k.startswith(args.prefix or "")]
    for key in keys:
        print(key)
    print(f"# {len(keys)} missing in {args.lang}", file=sys.stderr)
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    changed = 0
    bundles = []
    for lang in all_langs():
        bundle = Bundle(lang)
        if args.new in bundle.index:
            raise SystemExit(f"{lang}: target key '{args.new}' already exists")
        bundles.append(bundle)
    for bundle in bundles:
        if args.old in bundle.index:
            bundle.rename(args.old, args.new)
            bundle.save()
            changed += 1
    print(f"renamed in {changed} of {len(bundles)} bundles")
    return 0 if changed else 1


def _read_keys(path: str) -> list[str]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except ValueError:
        return [ln.strip() for ln in text.splitlines() if ln.strip()]
    return list(data) if isinstance(data, (dict, list)) else []


def cmd_export(args: argparse.Namespace) -> int:
    en = Bundle("en")
    target = Bundle(args.lang)
    out = {}
    for key in _read_keys(args.keys_from):
        value = en.get(key)
        if value is None:
            print(f"warning: '{key}' not in en.ts", file=sys.stderr)
            continue
        if args.only_missing and key in target.index:
            continue
        out[key] = value
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {len(out)} keys to {args.out}")
    else:
        print(text)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    patch = json.loads(Path(args.file).read_text(encoding="utf-8"))
    en = Bundle("en")
    bundle = Bundle(args.lang)
    added = updated = 0
    for key, value in patch.items():
        source = en.get(key)
        if source is None:
            print(f"skip '{key}': not in en.ts", file=sys.stderr)
            continue
        if not args.force and _placeholders(source) != _placeholders(value):
            print(f"skip '{key}': placeholders differ from English (use --force)", file=sys.stderr)
            continue
        if key in bundle.index:
            bundle.set(key, value)
            updated += 1
        else:
            bundle.add(key, value)
            added += 1
    bundle.save()
    print(f"{args.lang}: {added} added, {updated} updated")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("get", help="print the value of a key")
    p.add_argument("key")
    p.add_argument("--lang", nargs="+")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("add", help="insert a new key (needs --en)")
    p.add_argument("key")
    for lang in all_langs():
        p.add_argument(f"--{lang}", dest=lang, metavar="TEXT")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("set", help="change one value")
    p.add_argument("key")
    p.add_argument("--lang", required=True)
    p.add_argument("value")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("missing", help="keys in en.ts absent from a language")
    p.add_argument("--lang", required=True)
    p.add_argument("--prefix")
    p.set_defaults(func=cmd_missing)

    p = sub.add_parser("rename", help="rename a key in every bundle")
    p.add_argument("old")
    p.add_argument("new")
    p.set_defaults(func=cmd_rename)

    p = sub.add_parser("export", help="write {key: english} for a translator")
    p.add_argument("--lang", required=True)
    p.add_argument("--keys-from", required=True)
    p.add_argument("--out")
    p.add_argument("--only-missing", action="store_true")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help="apply {key: translation} JSON to a language")
    p.add_argument("--lang", required=True)
    p.add_argument("file")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_import)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
