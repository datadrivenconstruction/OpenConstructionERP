import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HolidayImport } from './HolidayImport';

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/shared/lib/api', () => ({ apiGet: mocks.get }));
vi.mock('react-i18next', () => ({ initReactI18next: { type: '3rdParty', init: () => undefined }, useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) =>
  String(options?.defaultValue ?? key).replace(/\{\{(\w+)\}\}/g, (_, field: string) => String(options?.[field] ?? '')) }) }));

function mount(onImport: (dates: string[]) => void, existing: string[] = []) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <HolidayImport projectId="p1" existing={existing} onImport={onImport} disabled={false} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset().mockImplementation((url: string) => {
    if (url.startsWith('/v1/schedule/work-calendar/')) return Promise.resolve({ holiday_country: 'FR' });
    return Promise.resolve({ country: 'FR', dates: ['2026-05-01', '2026-07-14'], coverage: [] });
  });
});
afterEach(cleanup);

describe('HolidayImport', () => {
  it('prefills the project country and merges the imported dates with the existing ones', async () => {
    const onImport = vi.fn();
    mount(onImport, ['2026-07-14', '2026-08-03']);
    const country = await screen.findByTestId('holiday-import-country');
    await waitFor(() => expect((country as HTMLInputElement).value).toBe('FR'));
    fireEvent.change(screen.getByTestId('holiday-import-year'), { target: { value: '2026' } });
    fireEvent.click(screen.getByTestId('holiday-import-button'));
    await waitFor(() => expect(onImport).toHaveBeenCalledWith(['2026-05-01', '2026-07-14', '2026-08-03']));
    expect(mocks.get).toHaveBeenCalledWith('/v1/schedule/holidays/?country=FR&years=2026');
  });
});
