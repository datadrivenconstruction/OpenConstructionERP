// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { hasBlockingIssue, insertField, opensPicker, sameBlocks, unknownFields } from './docTemplateText';

const KNOWN = new Set(['package.name', 'doc.total']);

describe('unknownFields', () => {
  it('accepts declared fields with or without spaces', () => {
    expect(unknownFields('Auftrag {{package.name}} {{ doc.total }}', KNOWN)).toEqual([]);
  });
  it('lists unknown and malformed tokens once', () => {
    expect(unknownFields('{{pkg}} {{pkg}} {{ package.__class__ }} {{ 7*7 }}', KNOWN)).toEqual([
      'pkg',
      '{{ package.__class__ }}',
      '{{ 7*7 }}',
    ]);
  });
});

describe('insertField', () => {
  it('replaces a typed {{ with the full token', () => {
    expect(insertField('für {{', 6, 'package.name')).toEqual({ text: 'für {{package.name}}', caret: 20 });
  });
  it('inserts at the caret', () => {
    expect(insertField('ab', 1, 'doc.total')).toEqual({ text: 'a{{doc.total}}b', caret: 14 });
  });
});

describe('helpers', () => {
  it('detects the picker trigger', () => {
    expect(opensPicker('x {{', 4)).toBe(true);
    expect(opensPicker('x {', 3)).toBe(false);
  });
  it('compares block maps', () => {
    expect(sameBlocks({ a: 'x', b: '' }, { a: 'x' })).toBe(true);
    expect(sameBlocks({ a: 'x' }, { a: 'y' })).toBe(false);
  });
  it('blocks only on errors', () => {
    expect(hasBlockingIssue([{ rule_id: 'doctpl.locale_fallback', severity: 'warning', block: '', params: {} }])).toBe(false);
    expect(hasBlockingIssue([{ rule_id: 'doctpl.unsafe_link', severity: 'error', block: 'body', params: {} }])).toBe(true);
  });
});
