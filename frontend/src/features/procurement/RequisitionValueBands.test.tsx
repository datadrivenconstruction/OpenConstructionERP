// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Requisition approval by value. Bands 5 000 EUR -> PM and 50 000 EUR ->
// Director (or anyone with a role): the draft check refuses a list the server would refuse, and an
// approver added by a band shows the band it came from.

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
  getErrorMessage: (e: unknown) => String(e),
}));

import { ApprovalChainView } from './RequisitionOrdering';
import { bandDraftProblem, type RequisitionApprovalStep } from './requisitionsApi';

const PM = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1';
const DIRECTOR = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2';

describe('bandDraftProblem', () => {
  it('accepts rising bands with one approver each', () => {
    expect(
      bandDraftProblem('EUR', [
        { from_amount: '5000', approvers: [PM] },
        { from_amount: '50000.00', approvers: [DIRECTOR] },
      ]),
    ).toBeNull();
  });

  it('accepts an empty list, which switches value routing off', () => {
    expect(bandDraftProblem('', [])).toBeNull();
  });

  it('names the first problem of a list the server would refuse', () => {
    expect(bandDraftProblem('EU', [{ from_amount: '5000', approvers: [PM] }])).toBe('currency');
    expect(bandDraftProblem('EUR', [{ from_amount: '0', approvers: [PM] }])).toBe('amount');
    expect(bandDraftProblem('EUR', [{ from_amount: '5000', approvers: [] }])).toBe('approvers');
    expect(
      bandDraftProblem('EUR', [
        { from_amount: '50000', approvers: [PM] },
        { from_amount: '5000', approvers: [DIRECTOR] },
      ]),
    ).toBe('order');
    expect(
      bandDraftProblem('EUR', [
        { from_amount: '5000', approvers: [PM] },
        { from_amount: '9000', approvers: [PM] },
      ]),
    ).toBe('repeated');
  });

  it('accepts a role as a band approver, alone or beside people', () => {
    expect(
      bandDraftProblem('EUR', [
        { from_amount: '5000', approvers: [], roles: ['manager'] },
        { from_amount: '50000', approvers: [DIRECTOR], roles: ['admin'] },
      ]),
    ).toBeNull();
  });

  it('refuses a role in two bands and more than five approvers in one', () => {
    expect(
      bandDraftProblem('EUR', [
        { from_amount: '5000', approvers: [], roles: ['manager'] },
        { from_amount: '50000', approvers: [], roles: ['manager'] },
      ]),
    ).toBe('repeated');
    const five = ['1', '2', '3', '4', '5'].map((n) => `aaaaaaaa-aaaa-4aaa-8aaa-00000000000${n}`);
    expect(bandDraftProblem('EUR', [{ from_amount: '5000', approvers: five, roles: ['manager'] }])).toBe('too_many');
  });
});

describe('ApprovalChainView', () => {
  it('shows the value band that added an approver and nothing for a designated one', () => {
    const steps: RequisitionApprovalStep[] = [
      { user_id: DIRECTOR, name: 'Site buyer', state: 'next', decided_at: null, comment: null },
      {
        user_id: PM,
        name: 'Project manager',
        state: 'waiting',
        decided_at: null,
        comment: null,
        band_from: '5000',
        band_currency: 'EUR',
      },
    ];
    render(<ApprovalChainView steps={steps} />);
    const bands = screen.getAllByTestId('approval-step-band');
    expect(bands).toHaveLength(1);
    expect(bands[0]!.textContent).toMatch(/Value band from/);
    expect(screen.queryByText(/Anyone with the role/)).toBeNull();
    expect(bands[0]!.textContent).toMatch(/5[,.\s  ]?000/);
  });
});

describe('ApprovalChainView with a role step', () => {
  it('names the role of an open role step and the person who decided a closed one', () => {
    const steps: RequisitionApprovalStep[] = [
      { user_id: 'role:manager', name: 'Project manager', state: 'approved', decided_at: null, comment: null, role: 'manager' },
      { user_id: 'role:admin', name: null, state: 'next', decided_at: null, comment: null, role: 'admin' },
    ];
    render(<ApprovalChainView steps={steps} />);
    expect(screen.getByText('Project manager')).toBeTruthy();
    expect(screen.getByText(/Anyone with the role/)).toBeTruthy();
  });
});
