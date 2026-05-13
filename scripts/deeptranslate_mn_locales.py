#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from deep_translator import GoogleTranslator


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_EN = ROOT / "frontend" / "src" / "app" / "locales" / "en.ts"
FRONTEND_MN = ROOT / "frontend" / "src" / "app" / "locales" / "mn.ts"
BACKEND_EN = ROOT / "backend" / "locales" / "en.json"
BACKEND_MN = ROOT / "backend" / "locales" / "mn.json"
STATE_DIR = ROOT / "tmp" / "deeptranslate-mn"
FRONTEND_STATE = STATE_DIR / "frontend-mn.json"
BACKEND_STATE = STATE_DIR / "backend-mn.json"

PLACEHOLDER_RE = re.compile(r"(\{\{[^}]+\}\}|\{[^}]+\}|%\([^)]+\)s|%s|%d|%f|<[^>]+>)")
TS_CAST_SUFFIX_RE = re.compile(r"\s+as\s+\{\s*translation:\s*Record<string, string>\s*\};\s*$", re.DOTALL)
MASK_TOKEN_RE = re.compile(r"\[\[PH_\d+\]\]")
SEP = "\n[[DT_BATCH_SEP]]\n"


def load_ts_resource(path: Path) -> dict[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    start_marker = "const resource ="
    end_marker = "export default resource;"
    start = text.find(start_marker)
    end = text.rfind(end_marker)
    if start < 0 or end < 0:
        raise RuntimeError(f"Could not parse TS locale resource from {path}")
    payload = text[start + len(start_marker) : end].strip()
    payload = TS_CAST_SUFFIX_RE.sub("", payload).strip()
    payload = re.sub(r",(\s*[}\]])", r"\1", payload)
    return json.loads(payload)


def dump_ts_resource(path: Path, resource: dict[str, dict[str, str]]) -> None:
    body = json.dumps(resource, ensure_ascii=False, indent=2)
    path.write_text(
        "// Auto-generated from en.ts via deeptranslate_mn_locales.py\n"
        "// Review before shipping.\n\n"
        f"const resource = {body} as {{ translation: Record<string, string> }};\n\n"
        "export default resource;\n",
        encoding="utf-8",
    )


def load_output_translations(state_path: Path) -> dict[str, str]:
    try:
        if state_path == FRONTEND_STATE and FRONTEND_MN.exists():
            return load_ts_resource(FRONTEND_MN)["translation"]
        if state_path == BACKEND_STATE and BACKEND_MN.exists():
            nested = json.loads(BACKEND_MN.read_text(encoding="utf-8"))
            flat: dict[str, str] = {}
            flatten("", nested, flat)
            return flat
    except Exception:
        return {}
    return {}


def flatten(prefix: str, value: object, out: dict[str, str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            flatten(next_prefix, child, out)
        return
    out[prefix] = "" if value is None else str(value)


def unflatten(flat: dict[str, str]) -> dict[str, object]:
    root: dict[str, object] = {}
    for dotted_key, value in flat.items():
        current = root
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})  # type: ignore[assignment]
        current[parts[-1]] = value
    return root


def mask_placeholders(text: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        token = f"[[PH_{len(replacements)}]]"
        replacements[token] = match.group(0)
        return token

    return PLACEHOLDER_RE.sub(repl, text), replacements


def unmask_placeholders(text: str, replacements: dict[str, str]) -> str:
    result = text
    for token, original in replacements.items():
        result = result.replace(token, original)
    return result


def placeholder_signature(text: str) -> list[str]:
    return sorted(PLACEHOLDER_RE.findall(text))


def is_translation_valid(source: str, translated: str) -> bool:
    if MASK_TOKEN_RE.search(translated):
        return False
    return placeholder_signature(source) == placeholder_signature(translated)


def translate_batch(values: list[str], source_lang: str, target_lang: str) -> list[str]:
    if not values:
        return []

    translator = GoogleTranslator(source=source_lang, target=target_lang)
    joined = SEP.join(values)
    translated = translator.translate(joined)
    if not translated:
        return values
    parts = [part.strip() for part in translated.split(SEP)]
    if len(parts) != len(values):
        return [translator.translate(value) or value for value in values]
    return parts


def load_existing_translations(state_path: Path, source: dict[str, str]) -> dict[str, str]:
    translations = {key: "" for key in source}
    if state_path.exists():
        translations.update(json.loads(state_path.read_text(encoding="utf-8")))
    for key, value in load_output_translations(state_path).items():
        if key in source and value:
            translations[key] = value
    return {key: translations.get(key, "") for key in source}


def save_state(state_path: Path, translations: dict[str, str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(translations, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def translate_map(
    source: dict[str, str],
    state_path: Path,
    source_lang: str,
    target_lang: str,
    batch_size: int,
    pause_seconds: float,
) -> dict[str, str]:
    translations = load_existing_translations(state_path, source)
    masked_inputs: list[tuple[str, str, str, dict[str, str]]] = []

    for key, value in source.items():
        if translations.get(key):
            continue
        if not value.strip():
            translations[key] = value
            continue
        masked, replacements = mask_placeholders(value)
        masked_inputs.append((key, value, masked, replacements))

    total = len(masked_inputs)
    for start in range(0, total, batch_size):
        chunk = masked_inputs[start : start + batch_size]
        raw_values = [item[2] for item in chunk]
        try:
            translated_values = translate_batch(raw_values, source_lang, target_lang)
        except Exception:
            translated_values = []
            for value in raw_values:
                try:
                    translated_values.append(
                        GoogleTranslator(source=source_lang, target=target_lang).translate(value) or value
                    )
                except Exception:
                    translated_values.append(value)

        for (key, source_value, masked_value, replacements), translated in zip(chunk, translated_values):
            candidate = unmask_placeholders(translated, replacements)
            if not is_translation_valid(source_value, candidate):
                try:
                    single = GoogleTranslator(source=source_lang, target=target_lang).translate(masked_value) or masked_value
                    candidate = unmask_placeholders(single, replacements)
                except Exception:
                    candidate = source_value
            if not is_translation_valid(source_value, candidate):
                candidate = source_value
            translations[key] = candidate

        save_state(state_path, translations)
        done = min(start + len(chunk), total)
        print(f"[{state_path.stem}] {done}/{total}", flush=True)
        if pause_seconds:
            time.sleep(pause_seconds)

    return translations


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate OpenConstructionERP English locale packs to Mongolian.")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--pause", type=float, default=0.6)
    args = parser.parse_args()

    frontend_en = load_ts_resource(FRONTEND_EN)["translation"]
    backend_en_nested = json.loads(BACKEND_EN.read_text(encoding="utf-8"))
    backend_en: dict[str, str] = {}
    flatten("", backend_en_nested, backend_en)

    print(f"Frontend keys: {len(frontend_en)}", flush=True)
    frontend_mn = translate_map(
        frontend_en,
        FRONTEND_STATE,
        source_lang="en",
        target_lang="mn",
        batch_size=args.batch_size,
        pause_seconds=args.pause,
    )
    dump_ts_resource(FRONTEND_MN, {"translation": frontend_mn})
    print(f"Wrote {FRONTEND_MN}", flush=True)

    print(f"Backend keys: {len(backend_en)}", flush=True)
    backend_mn = translate_map(
        backend_en,
        BACKEND_STATE,
        source_lang="en",
        target_lang="mn",
        batch_size=args.batch_size,
        pause_seconds=args.pause,
    )
    BACKEND_MN.write_text(
        json.dumps(unflatten(backend_mn), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {BACKEND_MN}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())