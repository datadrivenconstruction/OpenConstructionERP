// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { NormPricingCard } from './NormPricingCard';
import { averageLabourGrade, displayGrades, rateDerivation, type LabourRate } from './api';

const apiGet = vi.fn();
const apiPut = vi.fn();
const apiPost = vi.fn();
vi.mock('@/shared/lib/api', () => ({
  API_BASE: '/api',
  apiGet: (url: string) => apiGet(url),
  apiPut: (url: string, body: unknown) => apiPut(url, body),
  apiPost: (url: string, body: unknown) => apiPost(url, body),
  downloadWithAuth: vi.fn(),
  getErrorMessage: (e: unknown) => String(e),
}));
vi.mock('@/features/boq/api', () => ({
  boqApi: { list: () => Promise.resolve([{ id: 'b1', name: 'Кошторис 1' }]) },
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
      grade_field: 'grade',
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
  grading_status: 'sourced',
  grading_source: 'Настанова, Додаток 15',
  has_export_layout: true,
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
    apiPost.mockReset();
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
    expect(screen.getByTestId('norm-pricing-source')).toHaveTextContent('Додаток 15');
    expect(screen.queryByText(/interpolated/)).toBeNull();
  });

  it('writes only the labour rates the person kept ticked in the preview', async () => {
    const change = (id: string, current: string) => ({
      position_id: id,
      ordinal: id,
      description: '',
      resource_index: 0,
      resource_name: 'Затрати праці',
      grade: '3.5',
      current_rate: current,
      proposed_rate: '166.48',
      derivation: RATE_35,
    });
    apiGet.mockImplementation((url: string) => {
      if (url.includes('/labour-writeback')) {
        return Promise.resolve({
          boq_id: 'b1',
          estimate_wage: '30000',
          monthly_hours: '174',
          location_factor: '1',
          changes: [change('p1', '100'), change('p2', '120')],
          unchanged: 0,
          skipped: [{ position_id: 'p3', ordinal: '3', resource_index: 0, resource_name: 'x', reason: 'no_grade', grade: null }],
        });
      }
      if (url.includes('/labour-rates')) {
        return Promise.resolve({ estimate_wage: '30000', monthly_hours: '174', rates: [], missing_grades: [] });
      }
      return Promise.resolve(UA_PROFILE);
    });
    apiPost.mockResolvedValue({ updated_positions: 1, updated_resources: 1 });
    wrap(<NormPricingCard projectId="p-ua" />);
    await screen.findByRole('option', { name: 'Кошторис 1' });
    fireEvent.change(screen.getByLabelText('Bill'), { target: { value: 'b1' } });
    fireEvent.click(screen.getByRole('button', { name: /Preview labour rates/ }));
    const table = await screen.findByTestId('norm-writeback-preview');
    expect(table).toHaveTextContent('Labour rows left out (no grade, or a grade off the scale): 1');
    expect(apiPost).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText('p2 Затрати праці'));
    fireEvent.click(screen.getByRole('button', { name: /Apply rates: 1/ }));
    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    const [url, body] = apiPost.mock.calls[0] ?? [];
    expect(url).toContain('/labour-writeback?project_id=p-ua&boq_id=b1');
    expect(body).toEqual({ items: [{ position_id: 'p1', resource_index: 0, rate: '166.48' }] });
  });
});

describe('norm pricing helpers', () => {
  it('averages the labour grade by hours, to one decimal', () => {
    const meta = {
      resources: [
        { type: 'labor', quantity: 3, grade: '3.0' },
        { type: 'labor', quantity: 1, grade: '4.0' },
        { type: 'material', quantity: 10, grade: '9' },
      ],
    };
    expect(averageLabourGrade(meta)).toBe('3.3');
    expect(averageLabourGrade({ resources: [{ type: 'labour', grade: '5,2' }] })).toBe('5.2');
    expect(averageLabourGrade({ resources: [{ type: 'labor', quantity: 2 }] })).toBeNull();
    expect(averageLabourGrade(undefined)).toBeNull();
  });

  it('lists whole grades and the base grade', () => {
    expect(displayGrades({ grades: ['1.0', '3.5', '3.8', '4.0'], base_grade: '3.8' })).toEqual(['1.0', '3.8', '4.0']);
  });

  it('states the base grade rate without a second step', () => {
    expect(
      rateDerivation({ ...RATE_35, grade: '3.8', rate: '172.41' }, { estimate_wage: '30000', monthly_hours: '174' }),
    ).toBe('V3.8 = 30000 / 174 = 172.41');
  });
});
