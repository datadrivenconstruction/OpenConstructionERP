"""Apply v3.12 translation dictionary to a locale .ts file.

For each (key, value) in the JSON dict, find the corresponding line
    "<key>": "<old_value>",
in the .ts file and replace its quoted value with the new translation.
The old value MUST equal the English source from en.ts — that's how we
identify placeholder rows. Anything already translated stays untouched.
File structure (quotes, indentation, key order, trailing commas, comments)
is preserved exactly.
"""
import json
import re
import sys


def js_string_literal(s: str) -> str:
    """Encode a string for embedding in a TS source double-quoted literal.

    We preserve the exact JSON encoding rules used by the existing locale
    files: only escape backslash, double-quote, newline and tab. Everything
    else (including non-ASCII) is left literal. Unicode escapes are not
    introduced.
    """
    out = []
    for ch in s:
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        else:
            out.append(ch)
    return ''.join(out)


def patch(ts_path: str, en_path: str, tx_path: str) -> int:
    """Returns the number of values replaced."""
    with open(en_path, 'r', encoding='utf-8') as f:
        en_src = f.read()
    with open(ts_path, 'r', encoding='utf-8') as f:
        ts_src = f.read()
    with open(tx_path, 'r', encoding='utf-8') as f:
        tx = json.load(f)

    # Build map key -> english literal source (escape-encoded, as it appears in EN .ts)
    # We need exact string match against the placeholder in the .ts file
    line_re = re.compile(r'^(\s{4})"([^"]+)":\s*"((?:\\.|[^"\\])*)"(,?)\s*$', re.MULTILINE)
    en_literal = {}
    for m in line_re.finditer(en_src):
        en_literal[m.group(2)] = m.group(3)  # raw literal as seen in file (escapes intact)

    replaced = 0
    skipped_not_placeholder = 0
    skipped_no_key = 0

    def replace_line(m):
        nonlocal replaced, skipped_not_placeholder, skipped_no_key
        indent, key, raw_val, trail = m.group(1), m.group(2), m.group(3), m.group(4)
        if key not in tx:
            return m.group(0)
        en_lit = en_literal.get(key)
        if en_lit is None:
            skipped_no_key += 1
            return m.group(0)
        if raw_val != en_lit:
            # already translated — don't touch
            skipped_not_placeholder += 1
            return m.group(0)
        new_lit = js_string_literal(tx[key])
        replaced += 1
        return f'{indent}"{key}": "{new_lit}"{trail}'

    new_src = line_re.sub(replace_line, ts_src)
    if new_src != ts_src:
        with open(ts_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(new_src)
    return replaced, skipped_not_placeholder, skipped_no_key


if __name__ == '__main__':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    LOC = r'C:/Users/dev/Desktop/CodeProjects/ERP_26030500/frontend/src/app/locales'
    DICTS = r'C:/Users/dev/Desktop/CodeProjects/ERP_26030500/frontend/scripts/v312_tx'
    langs = sys.argv[1:] if len(sys.argv) > 1 else ['ja']
    for lang in langs:
        r, ns, nk = patch(f'{LOC}/{lang}.ts', f'{LOC}/en.ts', f'{DICTS}/{lang}.json')
        print(f'{lang}: replaced={r}, skipped_already_translated={ns}, skipped_no_en_key={nk}')
