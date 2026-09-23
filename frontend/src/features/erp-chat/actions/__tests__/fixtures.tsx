// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ReactElement } from 'react';
import { render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ChatAction } from '../types';

/** A proposal to change an existing BOQ position: quantity 80 -> 120 m3. */
export function makeAction(overrides: Partial<ChatAction> = {}): ChatAction {
  return {
    id: 'act-1',
    session_id: 's-1',
    message_id: null,
    project_id: 'p-1',
    project_name: 'Residential House',
    action_type: 'boq.update_position',
    status: 'proposed',
    title: 'Update BOQ position',
    title_key: 'erp_chat.action.type.boq.update_position',
    summary: 'Set position 03.012 to 120 m3',
    subtitle: 'Structural works',
    fields: [
      {
        key: 'description',
        label_key: 'erp_chat.action.field.description',
        label: 'Description',
        kind: 'text',
        value: 'Concrete C30/37 for the level 3 slab',
        before: null,
        editable: true,
        required: true,
      },
      {
        key: 'quantity',
        label_key: 'erp_chat.action.field.quantity',
        label: 'Quantity',
        kind: 'number',
        value: 120,
        before: 80,
        unit: 'm3',
        editable: true,
        required: true,
      },
      {
        key: 'unit_rate',
        label_key: 'erp_chat.action.field.unit_rate',
        label: 'Unit rate',
        kind: 'money',
        value: '145.50',
        before: '145.50',
        currency: 'EUR',
        editable: true,
        required: false,
      },
    ],
    payload: { description: 'Concrete C30/37 for the level 3 slab', quantity: 120, unit_rate: '145.50' },
    original_payload: { description: 'Concrete C30/37 for the level 3 slab', quantity: 120, unit_rate: '145.50' },
    edited: false,
    confidence: 0.86,
    rationale: 'The slab drawing gives 120 m3 for level 3; the position still has the earlier 80 m3.',
    target: { entity_type: 'position', entity_id: 'pos-1', label: 'Position 03.012', url: '/boq/boq-9?highlight=pos-1' },
    result: null,
    requested_by: { id: 'u-1', name: 'Anna Schmidt' },
    decided_by: null,
    decided_at: null,
    reverted_by: null,
    reverted_at: null,
    decision_note: null,
    revert_note: null,
    error: null,
    error_code: null,
    can_apply: true,
    can_edit: true,
    can_reject: true,
    can_revert: false,
    notes: [],
    blocked_reason_key: null,
    blocked_reason: null,
    revert_hint_key: null,
    revert_hint: null,
    batch_id: 'b-1',
    created_at: '2026-09-23T10:00:00Z',
    updated_at: '2026-09-23T10:00:00Z',
    ...overrides,
  };
}

/** The same action after Ben applied it. */
export function appliedAction(overrides: Partial<ChatAction> = {}): ChatAction {
  return makeAction({
    status: 'applied',
    decided_by: { id: 'u-2', name: 'Ben Keller' },
    decided_at: '2026-09-23T10:05:00Z',
    result: { entity_type: 'position', entity_id: 'pos-1', label: 'Position 03.012', url: '/boq/boq-9?highlight=pos-1' },
    can_apply: false,
    can_edit: false,
    can_reject: false,
    can_revert: true,
    updated_at: '2026-09-23T10:05:00Z',
    ...overrides,
  });
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

export function renderWithClient(ui: ReactElement, client: QueryClient = makeQueryClient()) {
  const result = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  return { ...result, client };
}
