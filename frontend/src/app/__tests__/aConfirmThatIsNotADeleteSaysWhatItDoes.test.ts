// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A confirmation that does something other than delete names that something.
//
// `ConfirmDialog` falls back to `confirm_dialog.delete` when no `confirmLabel`
// is passed, which is right for the removals that make up most of its callers.
// The award on a tender package took that fallback, so the button that awards
// a contract read "Delete". Integrations (disconnect), the demo marketplace
// (uninstall, reinstall), whole-life carbon (reject) and the schedule (reset)
// did the same.
//
// Deliberately a source scan: the defect is an argument that is absent, and no
// runtime seam sees it without rendering every page. A call without a label
// passes only when its title key names a removal. The population is asserted
// next to the verdict, so a scan that matched nothing cannot pass.
//
// Run:  npx vitest run src/app/__tests__/aConfirmThatIsNotADeleteSaysWhatItDoes.test.ts

import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = join(__dirname, '..', '..');

/** Title keys that name a removal, for which "Delete" is the right button. */
const REMOVAL = /delete|remove|clear|discard|revoke|purge|erase|wipe|unlink|detach/i;

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'dist' || entry === 'locales') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

/** The balanced `{...}` argument starting at `open`. */
function objectAt(src: string, open: number): string {
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') {
      depth -= 1;
      if (depth === 0) return src.slice(open, i + 1);
    }
  }
  return src.slice(open);
}

interface Call {
  where: string;
  titleKey: string | null;
  labelled: boolean;
}

function confirmCalls(): Call[] {
  const calls: Call[] = [];
  for (const file of walk(SRC)) {
    const src = readFileSync(file, 'utf8');
    if (!src.includes('useConfirm')) continue;
    // `confirm` itself and any name it is destructured to.
    const names = new Set(['confirm']);
    for (const m of src.matchAll(/\bconfirm:\s*(\w+)\s*[,}]/g)) names.add(m[1]!);
    for (const name of names) {
      for (const m of src.matchAll(new RegExp(`\\b${name}\\(\\{`, 'g'))) {
        const body = objectAt(src, m.index! + m[0].length - 1);
        const title = /title:\s*t\(\s*'([^']+)'/.exec(body);
        calls.push({
          where: `${relative(SRC, file)}:${src.slice(0, m.index).split('\n').length}`,
          titleKey: title ? title[1]! : null,
          labelled: /\bconfirmLabel\s*:/.test(body),
        });
      }
    }
  }
  return calls;
}

describe('confirm dialogs', () => {
  const calls = confirmCalls();

  it('finds the population it judges', () => {
    // Around forty callers use the promise-based hook today.
    expect(calls.length).toBeGreaterThan(20);
  });

  it('labels every confirmation that is not a removal', () => {
    const offenders = calls
      .filter((c) => !c.labelled && c.titleKey !== null && !REMOVAL.test(c.titleKey))
      .map((c) => `${c.where} ${c.titleKey}`);
    expect(offenders).toEqual([]);
  });
});
