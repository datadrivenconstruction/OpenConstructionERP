// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Many call sites write `oe-input-sm`/`oe-select-lg` without the base class.
// Each sized class must therefore carry the full field look on its own.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const CSS = readFileSync(resolve(__dirname, '../../index.css'), 'utf8');

function rulesFor(cls: string): string {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let body = '';
  for (let m = re.exec(CSS); m; m = re.exec(CSS)) {
    const selectors = m[1]!.split(',').map((s) => s.trim());
    if (selectors.includes(`.${cls}`)) body += m[2];
  }
  return body;
}

describe('sized field classes work without the base class', () => {
  it.each(['oe-input-sm', 'oe-input-lg', 'oe-select-sm', 'oe-select-lg'])('%s has border, radius and height', (cls) => {
    const body = rulesFor(cls);
    expect(body).toMatch(/border:\s*1px solid/);
    expect(body).toMatch(/border-radius:/);
    expect(body).toMatch(/height:\s*\d+px/);
  });

  it.each(['oe-select-sm', 'oe-select-lg'])('%s draws its own chevron', (cls) => {
    expect(rulesFor(cls)).toMatch(/appearance:\s*none/);
  });
});
