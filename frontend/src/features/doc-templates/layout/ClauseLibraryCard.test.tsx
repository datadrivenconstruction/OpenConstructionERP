// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ClauseLibraryCard } from './ClauseLibraryCard';

const api = vi.hoisted(() => ({
  listClauses: vi.fn(),
  saveClause: vi.fn(),
  deleteClause: vi.fn(),
}));

vi.mock('./layoutApi', () => api);
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string; [k: string]: unknown }) =>
      (opts?.defaultValue ?? key).replace(/\{\{(\w+)\}\}/g, (_m, name: string) => String(opts?.[name] ?? '')),
    i18n: { language: 'en' },
  }),
}));

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClauseLibraryCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.listClauses.mockReset().mockResolvedValue({
    items: [
      { key: 'retention', category: 'payment', title: { en: 'Retention' }, text: { en: '5 % retained.' }, locked: false },
      {
        key: 'de_vob_b_warranty',
        category: 'warranty',
        title: { en: 'Claims for defects', de: 'Mängelansprüche' },
        text: { en: 'Claims for defects are governed by § 13 VOB/B.' },
        locked: true,
        country: 'DE',
        source: 'VOB/B § 13',
      },
    ],
    total: 2,
    languages: ['de', 'en', 'fr'],
    can_edit: true,
  });
  api.saveClause.mockReset().mockResolvedValue({});
});

describe('ClauseLibraryCard', () => {
  it('lists the firm clause as editable and the pack clause as read-only with its source', async () => {
    renderCard();
    expect(await screen.findByTestId('clause-retention')).toBeInTheDocument();
    expect(screen.getByTestId('clause-edit-retention')).toBeInTheDocument();
    expect(screen.getByTestId('clause-locked-de_vob_b_warranty').textContent).toContain('Country pack DE');
    expect(screen.queryByTestId('clause-edit-de_vob_b_warranty')).toBeNull();
    expect(screen.getByTestId('clause-de_vob_b_warranty').textContent).toContain('VOB/B § 13');
  });

  it('saves a new clause with its text in the chosen language', async () => {
    renderCard();
    fireEvent.click(await screen.findByTestId('clause-new'));
    fireEvent.change(screen.getByTestId('clause-key'), { target: { value: 'Payment Terms' } });
    fireEvent.change(screen.getByTestId('clause-language'), { target: { value: 'de' } });
    fireEvent.change(screen.getByTestId('clause-title'), { target: { value: 'Zahlungsbedingungen' } });
    fireEvent.change(screen.getByTestId('clause-text'), { target: { value: 'Zahlbar binnen 30 Tagen.' } });
    fireEvent.click(screen.getByTestId('clause-save'));
    await waitFor(() =>
      expect(api.saveClause).toHaveBeenCalledWith('payment_terms', {
        category: '',
        title: { de: 'Zahlungsbedingungen' },
        text: { de: 'Zahlbar binnen 30 Tagen.' },
      }),
    );
  });

  it('refuses a key that is taken and a clause without text', async () => {
    renderCard();
    fireEvent.click(await screen.findByTestId('clause-new'));
    fireEvent.change(screen.getByTestId('clause-key'), { target: { value: 'retention' } });
    fireEvent.change(screen.getByTestId('clause-text'), { target: { value: 'Something' } });
    expect(screen.getByRole('alert').textContent).toContain('exists already');
    expect(screen.getByTestId('clause-save')).toBeDisabled();
    fireEvent.change(screen.getByTestId('clause-key'), { target: { value: 'retention_two' } });
    fireEvent.change(screen.getByTestId('clause-text'), { target: { value: '   ' } });
    expect(screen.getByTestId('clause-save')).toBeDisabled();
  });
});
