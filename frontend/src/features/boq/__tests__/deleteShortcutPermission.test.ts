// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The BOQ editor's Delete key must ask the same permission as every other
// delete control. `resolveBoqShortcut` skips the delete when told the user
// cannot delete (boqShortcuts.test.ts); this pins that the editor tells it,
// from the role gate the grid's delete controls use.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const PAGE = readFileSync(resolve(__dirname, '../BOQEditorPage.tsx'), 'utf8');

describe('the BOQ editor Delete shortcut', () => {
  it('passes the boq.delete permission into the shortcut resolver', () => {
    expect(PAGE).toMatch(/const canDeletePositions = useHasPermission\('boq\.delete'\);/);
    expect(PAGE).toMatch(/resolveBoqShortcut\(e, \{[\s\S]{0,400}canDelete: canDeletePositions,/);
  });

  it('re-subscribes the key handler when the permission changes', () => {
    const effectEnd = PAGE.indexOf("document.removeEventListener('keydown', handleKeyDown, true);");
    const deps = PAGE.slice(effectEnd, effectEnd + 300);
    expect(deps).toContain('canDeletePositions');
  });
});
