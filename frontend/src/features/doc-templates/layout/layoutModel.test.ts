import { describe, expect, it } from 'vitest';
import type { LayoutBlock, LayoutLocks, LayoutTemplate } from './layoutApi';
import {
  allBlockIds,
  blockLock,
  columnLock,
  duplicateBlock,
  historyOf,
  historyPush,
  historyRedo,
  historyUndo,
  moveItem,
  variantKey,
  removeBlock,
  setText,
  textIn,
  unknownFields,
  updateBlock,
} from './layoutModel';

const LOCKS: LayoutLocks = {
  sections: { line_items: 'Standard purchase order' },
  columns: { items: { amount: 'Standard purchase order' } },
  fields: {},
};

function template(body: LayoutBlock[]): LayoutTemplate {
  return {
    schema: 1,
    primary_locale: 'en',
    title: {},
    subject: {},
    show_subject: true,
    page: {} as LayoutTemplate['page'],
    branding: {},
    watermark: {},
    header: [],
    footer: [],
    body,
  };
}

const BODY: LayoutBlock[] = [
  { id: 'line_items', type: 'section' } as LayoutBlock,
  {
    id: 'cols',
    type: 'columns',
    columns: [[{ id: 'left', type: 'text', text: { en: 'L' } }], [{ id: 'right', type: 'text', text: { en: 'R' } }]],
  } as LayoutBlock,
];

describe('layout model', () => {
  it('names the lock of a required section and column', () => {
    expect(blockLock(BODY[0] as LayoutBlock, LOCKS)).toBe('Standard purchase order');
    expect(blockLock(BODY[1] as LayoutBlock, LOCKS)).toBeNull();
    expect(columnLock('items', 'amount', LOCKS)).toBe('Standard purchase order');
    expect(columnLock('items', 'unit', LOCKS)).toBeNull();
  });

  it('falls back from the region to the language to the primary text', () => {
    expect(textIn({ en: 'Order', de: 'Bestellung' }, 'de-AT')).toBe('Bestellung');
    expect(textIn({ en: 'Order' }, 'fr')).toBe('Order');
    expect(setText({ en: 'A', de: 'B' }, 'de', '')).toEqual({ en: 'A' });
  });

  it('edits blocks inside a two-column container', () => {
    const t = template(BODY);
    expect([...allBlockIds(t.body)]).toEqual(['line_items', 'cols', 'left', 'right']);
    const updated = updateBlock(t, 'right', { hidden: true } as Partial<LayoutBlock>);
    expect((updated.body[1]?.columns as LayoutBlock[][])[1]?.[0]?.hidden).toBe(true);
    const removed = removeBlock(t, 'left');
    expect((removed.body[1]?.columns as LayoutBlock[][])[0]).toEqual([]);
  });

  it('duplicates a block below itself with fresh ids, a section keeps its source', () => {
    const t = duplicateBlock(template(BODY), 'line_items');
    expect(t.body).toHaveLength(3);
    expect(t.body[1]?.id).not.toBe('line_items');
    expect(t.body[1]?.section).toBe('line_items');
    const c = duplicateBlock(template(BODY), 'cols');
    expect(new Set(allBlockIds(c.body)).size).toBe(7);
  });

  it('reorders and flags unknown merge fields', () => {
    expect(moveItem(['a', 'b', 'c'], 0, 2)).toEqual(['b', 'c', 'a']);
    expect(moveItem(['a'], 0, 3)).toEqual(['a']);
    expect(unknownFields('{{doc.number}} {{doc.nope}} {{ doc.nope }}', new Set(['doc.number']))).toEqual(['doc.nope']);
  });

  it('undoes and redoes, a new edit clears the redo stack', () => {
    let h = historyOf(1);
    h = historyPush(h, 2);
    h = historyPush(h, 3);
    h = historyUndo(h);
    expect(h.present).toBe(2);
    h = historyRedo(h);
    expect(h.present).toBe(3);
    h = historyPush(historyUndo(h), 4);
    expect(h.future).toEqual([]);
    expect(historyUndo(historyOf(1)).present).toBe(1);
  });

  it('turns a typed variant name into a key, empty when nothing usable is left', () => {
    expect(variantKey('  Short form (EN) ')).toBe('short_form_en');
    expect(variantKey('***')).toBe('');
    expect(variantKey('x'.repeat(60))).toHaveLength(40);
  });
});
