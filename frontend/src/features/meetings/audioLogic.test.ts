// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, expect, it } from 'vitest';
import type { Proposal } from './audioApi';
import {
  actionProblems,
  canConfirm,
  draftFor,
  formatClock,
  groupProposals,
  maxRecordSeconds,
  resolveOwner,
  retentionOptions,
  reviewEntry,
  segmentsFromText,
  speakerLabels,
  speakerName,
} from './audioLogic';

const action = (over: Partial<Proposal> = {}): Proposal => ({
  id: 'a1',
  kind: 'action',
  status: 'pending',
  text: 'Send the revised rebar drawings',
  confidence: 0.8,
  owner_name: 'Anna Berg',
  owner_contact_id: 'c-1',
  due_date: '2026-11-02',
  linked_entity: { type: 'rfi', id: 'r-1', label: 'RFI 12' },
  ...over,
});

describe('segmentsFromText', () => {
  it('splits speaker turns and keeps unlabelled lines', () => {
    const segs = segmentsFromText('Anna: Pour on Friday.\n\nwe agreed\n10: not a speaker');
    expect(segs.map((s) => s.speaker)).toEqual(['Anna', '', '']);
    expect(segs[0]!.text).toBe('Pour on Friday.');
    expect(segs[2]!.text).toBe('10: not a speaker');
  });
});

describe('speakers', () => {
  it('lists labels once in order and resolves names', () => {
    const segs = segmentsFromText('S1: a\nS2: b\nS1: c');
    expect(speakerLabels(segs)).toEqual(['S1', 'S2']);
    expect(speakerName('S1', { S1: { name: 'Anna', contact_id: null } })).toBe('Anna');
    expect(speakerName('S2', {})).toBe('S2');
  });
});

describe('recording limits', () => {
  it('fits a long meeting into the upload cap at speech bitrate', () => {
    expect(maxRecordSeconds(25)).toBeGreaterThan(2 * 3600);
    expect(maxRecordSeconds(0)).toBe(60);
  });

  it('formats clock time', () => {
    expect(formatClock(65)).toBe('01:05');
    expect(formatClock(3725)).toBe('1:02:05');
  });

  it('offers retention windows up to the maximum plus the default', () => {
    expect(retentionOptions(30, 90)).toEqual([7, 30, 90]);
    expect(retentionOptions(14, 30)).toEqual([7, 14, 30]);
    expect(retentionOptions(0, 365)).toEqual([7, 30, 90, 365]);
  });
});

describe('proposal review', () => {
  it('groups by kind in reading order', () => {
    const groups = groupProposals([
      action(),
      { id: 's1', kind: 'summary', status: 'pending', text: 'x', confidence: 0.7 },
    ]);
    expect(groups.map((g) => g.kind)).toEqual(['summary', 'action']);
  });

  it('blocks an action without owner or due date', () => {
    const d = draftFor(action({ owner_name: '', owner_contact_id: null, due_date: 'next week' }));
    expect(actionProblems(d)).toEqual(['owner', 'due']);
    expect(canConfirm(action(), d)).toBe(false);
    expect(canConfirm(action(), draftFor(action()))).toBe(true);
  });

  it('sends only the fields of the kind, and nothing but the verdict on reject', () => {
    const p = action();
    expect(reviewEntry(p, draftFor(p), 'reject')).toEqual({ id: 'a1', decision: 'reject' });
    const confirmed = reviewEntry(p, draftFor(p), 'confirm');
    expect(confirmed).toMatchObject({
      id: 'a1',
      decision: 'confirm',
      owner_contact_id: 'c-1',
      due_date: '2026-11-02',
      linked_entity: { type: 'rfi', id: 'r-1' },
    });
    const correction: Proposal = {
      id: 'c2',
      kind: 'correction',
      status: 'pending',
      text: 'Mueler -> Müller',
      confidence: 0.9,
      heard: 'Mueler',
      term: 'Müller',
    };
    expect(reviewEntry(correction, draftFor(correction), 'confirm')).toMatchObject({ heard: 'Mueler', term: 'Müller' });
    expect(reviewEntry(correction, draftFor(correction), 'confirm')).not.toHaveProperty('owner_name');
  });

  it('carries the contact id of a known owner and drops it for a typed one', () => {
    const people = [{ name: 'Anna Berg', contact_id: 'c-1' }];
    expect(resolveOwner('anna berg', people)).toEqual({ owner_name: 'anna berg', owner_contact_id: 'c-1' });
    expect(resolveOwner('Site office', people)).toEqual({ owner_name: 'Site office', owner_contact_id: null });
  });
});
