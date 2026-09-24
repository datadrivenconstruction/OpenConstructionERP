// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, expect, it } from 'vitest';
import type { TimelineEntry } from '../api';
import { assistantRecordRoute } from '../assistantRoute';

const PROJECT = '5f0c2a52-7d1e-4f59-9a55-2f4c1f6f0b11';
const TASK = '0b6f3f0e-3a55-4a0e-8d8f-6c1b0f2d9e21';
const LINE = 'c3b1d7a4-1f7e-4c55-9b0a-8e3f2d1c0a99';
const BILL = 'e2a9c8b7-6d5f-4e3a-9c1b-0a8f7e6d5c4b';

function row(overrides: Partial<TimelineEntry>): TimelineEntry {
  return {
    id: 'a1',
    entity_type: 'task',
    entity_id: TASK,
    action: 'created',
    module: 'erp_chat',
    from_status: null,
    to_status: null,
    parent_entity_type: 'project',
    parent_entity_id: PROJECT,
    actor_id: null,
    reason: null,
    metadata: { via: 'ai_assistant' },
    created_at: null,
    ...overrides,
  };
}

describe('assistantRecordRoute', () => {
  it('follows the link the row carries', () => {
    const url = `/boq/${BILL}?highlight=${LINE}`;
    expect(assistantRecordRoute(row({ entity_type: 'position', entity_id: LINE, metadata: { url } }))).toBe(url);
  });

  it('opens a task in its project task list without a stored link', () => {
    expect(assistantRecordRoute(row({}))).toBe(`/projects/${PROJECT}/tasks?id=${TASK}`);
  });

  it('gives the undo that deleted a task no link to the task it deleted', () => {
    expect(assistantRecordRoute(row({ action: 'reverted' }))).toBeNull();
  });

  it('gives a BOQ line without a stored link no link rather than a guessed one', () => {
    expect(assistantRecordRoute(row({ entity_type: 'position', entity_id: LINE }))).toBeNull();
  });

  it.each(['//evil.example/boq', '/\\evil.example', 'https://evil.example/boq', 'javascript:alert(1)'])(
    'never follows %s out of the app',
    (url) => {
      expect(assistantRecordRoute(row({ entity_type: 'position', entity_id: LINE, metadata: { url } }))).toBeNull();
    },
  );
});
