// One-off backfill: inserts v3.12.0 Wave 5/6/7 keys into every non-EN locale.
// Source of truth: src/app/locales/en.ts. This script ONLY adds missing keys.
// It never modifies en.ts and never removes/overwrites existing keys.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const LOCALES_DIR = path.join(__dirname, '..', 'src', 'app', 'locales');

function parseEntries(p) {
  const text = fs.readFileSync(p, 'utf-8');
  const entries = {};
  // Normalize line endings for parsing
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const m = /^    "([^"]+)":\s*(.*)$/.exec(line);
    if (m) {
      const key = m[1];
      let rest = m[2];
      if (rest === '' || rest === undefined) { i++; rest = lines[i].trim(); }
      let buffer = rest;
      while (!/[",]\s*$/.test(buffer.trim()) && !/^\}/.test(lines[i + 1] || '')) {
        i++; buffer += '\n' + lines[i];
      }
      entries[key] = buffer;
    }
    i++;
  }
  return entries;
}

const enEntries = parseEntries(path.join(LOCALES_DIR, 'en.ts'));

// Translation tables loaded from per-locale .json files in v312_tx/
const TX_DIR = path.join(__dirname, 'v312_tx');
const T = {};
for (const f of fs.readdirSync(TX_DIR)) {
  if (f.endsWith('.json')) {
    const loc = f.replace(/\.json$/, '');
    T[loc] = JSON.parse(fs.readFileSync(path.join(TX_DIR, f), 'utf-8'));
  }
}

const LOCALES = ['ar','bg','cs','da','de','es','fi','fr','hi','hr','id','it','ja','ko','mn','nl','no','pl','pt','ro','ru','sv','th','tr','vi','zh'];

function _formatValue(val) {
  // val is the raw English buffer like: "Add Child Partida",  or  'No steps match "{{query}}"',
  // We want to preserve the same quoting style. Strip trailing comma.
  let v = val.replace(/,\s*$/, '');
  return v;
}

function tsStringFromText(text) {
  // Wrap a plain JS string in TS source. If it contains a literal double-quote, use single quotes.
  if (text.includes('"') && !text.includes("'")) {
    return "'" + text + "'";
  }
  // escape backslashes & double quotes
  return '"' + text.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
}

function extractPlainTextFromEnValue(rawBuffer) {
  // Strip trailing comma + parse the TS literal back to a JS string.
  let v = rawBuffer.replace(/,\s*$/, '').trim();
  // Use Function constructor — safe here because input is from our own en.ts.
  // eslint-disable-next-line no-new-func
  return new Function('return ' + v)();
}

for (const loc of LOCALES) {
  const fp = path.join(LOCALES_DIR, loc + '.ts');
  const original = fs.readFileSync(fp, 'utf-8');
  const existing = parseEntries(fp);
  const missingKeys = Object.keys(enEntries).filter(k => !(k in existing));
  const trDict = T[loc] || {};

  if (missingKeys.length === 0) {
    console.log(loc + ': nothing to do');
    continue;
  }

  const lines = [];
  let missingTranslation = [];
  for (const k of missingKeys) {
    const enText = extractPlainTextFromEnValue(enEntries[k]);
    const tx = trDict[k];
    if (tx === undefined) {
      missingTranslation.push(k);
      lines.push('    ' + JSON.stringify(k) + ': ' + tsStringFromText(enText) + ',');
    } else {
      lines.push('    ' + JSON.stringify(k) + ': ' + tsStringFromText(tx) + ',');
    }
  }

  // Insert before the closing "  }\r?\n} as { translation:" block.
  const closingMatch = /  \}\r?\n\} as/.exec(original);
  if (!closingMatch) {
    console.error(loc + ': could not find closing brace');
    continue;
  }
  const insertAt = closingMatch.index;
  // Detect line ending used by the file
  const eol = original.includes('\r\n') ? '\r\n' : '\n';
  const updated = original.slice(0, insertAt) + lines.join(eol) + eol + original.slice(insertAt);
  fs.writeFileSync(fp, updated, 'utf-8');
  console.log(loc + ': inserted ' + missingKeys.length + ' keys (untranslated fallbacks: ' + missingTranslation.length + ')');
  if (missingTranslation.length > 0 && missingTranslation.length < 30) {
    console.log('  -> ' + missingTranslation.slice(0, 10).join(', '));
  }
}
