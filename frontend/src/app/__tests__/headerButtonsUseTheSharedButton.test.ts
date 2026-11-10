// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every control in a page header row is the shared `Button` (or a shared
// header control built on it), so all of them share one height and one radius.
// A hand-rolled `<button>` with its own `rounded-*` in `<PageHeader actions>`
// is what made "Insights" square-ish and "How it works" a pill side by side.
//
// Segments of a segmented toggle (`data-oe-segment`) may round inside their
// group. Anything else needs an entry below with its reason.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const FEATURES = resolve(__dirname, '../../features');

const ALLOWED: Record<string, string> = {};

function tsxFiles(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(dir)) {
    const abs = join(dir, e);
    if (statSync(abs).isDirectory()) tsxFiles(abs, out);
    else if (e.endsWith('.tsx') && !e.includes('.test.')) out.push(abs);
  }
  return out;
}

function actionBlocks(src: string): string[] {
  const blocks: string[] = [];
  let i = 0;
  while ((i = src.indexOf('<PageHeader', i)) >= 0) {
    i += 1;
    const a = src.indexOf('actions=', i);
    const close = src.indexOf('/>', i);
    if (a < 0 || (close >= 0 && close < a && !src.slice(i, close).includes('actions='))) continue;
    if (a - i > 3000) continue;
    const j = src.indexOf('{', a);
    let depth = 0;
    let k = j;
    for (; k < src.length; k++) {
      if (src[k] === '{') depth++;
      else if (src[k] === '}' && --depth === 0) break;
    }
    blocks.push(src.slice(j, k));
  }
  return blocks;
}

/** Opening `<button ...>` tags, read up to the first `>` outside braces. */
function buttonTags(block: string): string[] {
  const tags: string[] = [];
  let i = 0;
  while ((i = block.indexOf('<button', i)) >= 0) {
    let depth = 0;
    let k = i;
    for (; k < block.length; k++) {
      const c = block[k];
      if (c === '{') depth++;
      else if (c === '}') depth--;
      else if (c === '>' && depth === 0) break;
    }
    tags.push(block.slice(i, k + 1));
    i = k;
  }
  return tags;
}

describe('page header buttons use the shared Button', () => {
  it('no hand-rolled <button> with its own radius in PageHeader actions', () => {
    const offenders: string[] = [];
    for (const abs of tsxFiles(FEATURES)) {
      const rel = abs.slice(FEATURES.length + 1).split('\\').join('/');
      if (ALLOWED[rel]) continue;
      const src = readFileSync(abs, 'utf8');
      if (!src.includes('<PageHeader')) continue;
      for (const block of actionBlocks(src)) {
        for (const tag of buttonTags(block)) {
          if (tag.includes('data-oe-segment')) continue;
          if (/(^|[\s'"`{])rounded(-[a-z0-9]+)?(?=[\s'"`}])/.test(tag)) offenders.push(rel);
        }
      }
    }
    expect([...new Set(offenders)]).toEqual([]);
  });
});
