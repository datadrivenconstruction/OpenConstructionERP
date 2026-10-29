// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { PartyChip } from '../PartyChip';
import * as api from '../bidInvitations';
import type { BidInvitation } from '../bidInvitations';

vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({
    t: (key: string, o?: { defaultValue?: string; [k: string]: unknown }) =>
      (o?.defaultValue ?? key).replace(/\{\{(\w+)\}\}/g, (_m, n) => String(o?.[n] ?? '')),
  }),
}));
vi.mock('@/shared/ui/ContactSearchInput', () => ({ ContactSearchInput: () => <div>picker</div> }));

const base: BidInvitation = {
  id: 'inv1',
  package_id: 'pkg1',
  recipient_id: 'r1',
  company_name: 'Alpha',
  email: 'a@alpha.io',
  status: 'not_opened',
  expires_at: '',
  opened_at: null,
  draft_saved_at: null,
  submitted_at: null,
  revoked_at: null,
  bid_id: null,
  created_at: '',
};

function renderChip(inv: BidInvitation) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <PartyChip invitation={inv} />
    </QueryClientProvider>,
  );
}

describe('PartyChip', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('shows the linked party and unlinks it', async () => {
    const spy = vi.spyOn(api, 'unlinkInvitationParty').mockResolvedValue({} as never);
    renderChip({ ...base, contact_id: 'c1', contact_name: 'Alpha GmbH' });
    expect(screen.getByText('Party: Alpha GmbH')).toBeTruthy();
    fireEvent.click(screen.getByTestId('party-unlink-inv1'));
    await waitFor(() => expect(spy).toHaveBeenCalledWith('pkg1', 'inv1'));
  });

  it('warns without a party and confirms a suggestion only on click', async () => {
    const spy = vi.spyOn(api, 'decidePartySuggestion').mockResolvedValue({});
    renderChip({
      ...base,
      suggestion: { review_id: 'rv1', contact_id: 'c1', contact_name: 'Alpha GmbH', method: 'name', confidence: 0.6 },
    });
    expect(screen.getByText('No party')).toBeTruthy();
    expect(screen.getByText('Suggested: Alpha GmbH (60%)')).toBeTruthy();
    expect(spy).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('party-confirm-inv1'));
    await waitFor(() => expect(spy).toHaveBeenCalledWith('rv1', true));
  });
});
