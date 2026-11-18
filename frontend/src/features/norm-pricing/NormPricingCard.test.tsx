// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { NormPricingCard } from './NormPricingCard';
import { displayGrades, rateDerivation, type LabourRate } from './api';

const apiGet = vi.fn();
const apiPut = vi.fn();
vi.mock('@/shared/lib/api', () => ({
  apiGet: (url: string) => apiGet(url),
  apiPut: (url: string, body: unknown) => apiPut(url, body),
  getErrorMessage: (e: unknown) => String(e),
}));

const UA_PROFILE = {
  available: true,
  pack_slug: 'ukraine-ua',
  currency: 'UAH',
  norm_bases: [
    {
      key: 'knu',
      name: 'Кошторисні норми України (KNU)',
      classification_key: 'knu',
      code_example: 'КБ1-13-1',
      types: [],
      legacy_prefixes: {},
    },
  ],
  funding_classes: [
    {
      key: 'public',
      label: 'Бюджетні або державні кошти',
      source: 'Постанова КМУ №1512',
      markup_caps: [
        { key: 'general_production', label: 'Загальновиробничі витрати', cap_percent: '10' },
        { key: 'administrative', label: 'Адміністративні витрати', cap_percent: '3' },
        { key: 'profit', label: 'Кошторисний прибуток', cap_percent: '15' },
      ],
      investor_estimate_at_cap: true,
      min_quotes: 3,
    },
  ],
  location_factors: [{ key: 'active_hostilities', label: 'Active hostilities', source: '', factor: '2.0' }],
  grades: ['1.0', '3.5', '3.8', '4.0'],
  base_grade: '3.8',
  grading_status: 'derived',
  default_monthly_hours: '174',
  settings: { estimate_wage: '30000', monthly_hours: '174', funding_class: 'public', estimate_role: 'investor' },
};

const RATE_35: LabourRate = {
  grade: '3.5',
  base_grade: '3.8',
  base_rate: '172.41',
  grade_one_rate: '131.81',
  base_coefficient: '1.308',
  coefficient: '1.263',
  rate: '166.48',
  location_factor: '1',
  rate_with_location: '166.48',
};

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('NormPricingCard', () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPut.mockReset();
  });

  it('renders nothing where no pack supplies norm pricing', async () => {
    apiGet.mockResolvedValue({ available: false });
    const { container } = wrap(<NormPricingCard projectId="p-de" />);
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(container.innerHTML).toBe('');
  });

  it('shows the caps of the funding type and the derived rates', async () => {
    apiGet.mockImplementation((url: string) =>
      url.includes('/labour-rates')
        ? Promise.resolve({ estimate_wage: '30000', monthly_hours: '174', rates: [RATE_35], missing_grades: [] })
        : Promise.resolve(UA_PROFILE),
    );
    wrap(<NormPricingCard projectId="p-ua" />);
    expect(await screen.findByTestId('norm-pricing-caps')).toHaveTextContent('Загальновиробничі витрати ≤ 10 %');
    const rates = await screen.findByTestId('norm-pricing-rates');
    await waitFor(() => expect(rates).toHaveTextContent('166.48'));
    const row = screen.getByText('166.48').closest('tr');
    expect(row?.getAttribute('title')).toBe(
      'V3.8 = 30000 / 174 = 172.41; V1 = 172.41 / 1.308 = 131.81; V3.5 = 131.81 × 1.263 = 166.48',
    );
  });
});

describe('norm pricing helpers', () => {
  it('lists whole grades and the base grade', () => {
    expect(displayGrades({ grades: ['1.0', '3.5', '3.8', '4.0'], base_grade: '3.8' })).toEqual(['1.0', '3.8', '4.0']);
  });

  it('states the base grade rate without a second step', () => {
    expect(
      rateDerivation({ ...RATE_35, grade: '3.8', rate: '172.41' }, { estimate_wage: '30000', monthly_hours: '174' }),
    ).toBe('V3.8 = 30000 / 174 = 172.41');
  });
});
