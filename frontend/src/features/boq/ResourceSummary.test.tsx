import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ResourceSummary } from './ResourceSummary';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string, options: Record<string, unknown> = {}) =>
    String(options.defaultValue ?? key).replace(/{{(\w+)}}/g, (_, name) => String(options[name] ?? '')) }),
}));
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ getQueryData: vi.fn(), invalidateQueries: vi.fn() }),
  useQuery: () => ({ data: {
    total_resources: 0, resources: [], by_type: {}, grand_total: '0.00',
    unconverted: { USD: '40.25', JPY: '15', KWD: '-1.125' },
  }, isLoading: false, isError: false }),
}));
vi.mock('@/stores/useToastStore', () => ({ useToastStore: () => vi.fn() }));
vi.mock('@/features/costs/VariantPicker', () => ({ VariantPicker: () => null }));

describe('resource summary excluded money', () => {
  it('keeps a wholly unconverted summary visible and displays each native currency separately', () => {
    render(<ResourceSummary boqId="test" locale="en-US" currency="EUR" />);
    fireEvent.click(screen.getByRole('button', { name: 'Resource Summary' }));
    expect(screen.getByTestId('unconverted-USD').textContent).toBe('Excluded from total: 40.25 USD');
    expect(screen.getByTestId('unconverted-JPY').textContent).toBe('Excluded from total: 15 JPY');
    expect(screen.getByTestId('unconverted-KWD').textContent).toBe('Excluded from total: -1.125 KWD');
    expect(screen.getByRole('status').textContent).toContain('Set a positive rate');
  });
});
