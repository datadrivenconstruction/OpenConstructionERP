// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CalendarCoverageNotice } from './CalendarCoverageNotice';
import type { HolidayCoverage, Schedule, WorkCalendarResponse } from './api';

const mocks = vi.hoisted(() => ({ get: vi.fn(), calendars: vi.fn() }));
vi.mock('@/shared/lib/api', () => ({ apiGet: mocks.get }));
vi.mock('@/features/schedule-advanced/api', () => ({ listCalendars: mocks.calendars }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) =>
  String(options?.defaultValue ?? key).replace(/\{\{(\w+)\}\}/g, (_, field: string) => String(options?.[field] ?? '')) }) }));

const complete = (year: number): HolidayCoverage => ({ year, applied: true,
  jurisdiction: { source: 'declared' }, effective_year: { source: 'declared' }, holiday_extent: { source: 'declared' },
  omitted: [], placeholder_spans: [] });
const plan: Schedule = { id: 's1', project_id: 'p1', name: 'Plan', description: '',
  start_date: '2026-12-21', end_date: '2027-01-05', status: 'draft', created_at: '', updated_at: '' };
const regional: WorkCalendarResponse = { region: 'DE', hours_per_day: 8, work_days_per_week: 5,
  label: 'Germany', week_fallback: false, holiday_coverage: complete(2026) };

function mount(schedule = plan) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const wrap = (value: Schedule) => <QueryClientProvider client={client}><CalendarCoverageNotice schedule={value} /></QueryClientProvider>;
  const view = render(wrap(schedule));
  return { ...view, switchTo: (value: Schedule) => view.rerender(wrap(value)) };
}

beforeEach(() => { mocks.get.mockReset().mockResolvedValue(regional); mocks.calendars.mockReset().mockResolvedValue([]); });
afterEach(cleanup);

describe('calendar coverage presented to the planner', () => {

  it.each([true, false, undefined])('uses only explicit saved fallback %s without a regional fetch', fallback => {
    mount({ ...plan, metadata_: { calendar: { work_days: [0, 1, 2, 3, 4], regional_holiday_country: 'ZZ',
      ...(fallback === undefined ? {} : { week_fallback: fallback }), holiday_coverage: [] } } });
    expect(screen.queryByText(/regional working week is unavailable/) !== null).toBe(fallback === true);
    expect(mocks.get).not.toHaveBeenCalled();
    expect(mocks.calendars).not.toHaveBeenCalled();
  });

  it('ignores a stale fallback marker on a manual calendar', () => {
    const { container } = mount({ ...plan, metadata_: { calendar: { work_days: [0, 2, 4],
      week_fallback: true, exceptions: [] } } });
    expect(container).toBeEmptyDOMElement();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it('shows loading without an invented DACH week while the project calendars are pending', () => {
    mocks.calendars.mockReturnValue(new Promise(() => {}));
    mount();
    expect(screen.getByRole('status')).toHaveTextContent('Loading');
    expect(screen.queryByText(/8h\/day/)).not.toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it('shows loading until regional data resolves too', async () => {
    mocks.get.mockReturnValue(new Promise(() => {}));
    mount();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(screen.getByRole('status')).toHaveTextContent('Loading');
    expect(screen.queryByText(/8h\/day/)).not.toBeInTheDocument();
  });

  it.each(['calendars', 'get'] as const)('offers retry when %s fails instead of showing a default week', async target => {
    mocks[target].mockRejectedValueOnce(new Error('offline'));
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Error');
    expect(screen.queryByText(/8h\/day/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('8h/day, 5 days/week')).toBeInTheDocument();
  });

  it('warns on unknown-country holidays and fallback week using the response year', async () => {
    mocks.get.mockResolvedValue({ ...regional, week_fallback: true,
      holiday_coverage: { ...complete(2028), applied: false, jurisdiction: { source: 'fallback' } } });
    mount();
    expect(await screen.findByText(/regional working week is unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/Public holidays are not available for 2028/)).toBeInTheDocument();
  });

  it.each(['effective_year', 'holiday_extent'] as const)('reports partial %s without claiming holidays are absent', async axis => {
    mocks.get.mockResolvedValue({ ...regional, holiday_coverage: { ...complete(2026), [axis]: { source: 'fallback' } } });
    mount();
    expect(await screen.findByText(/coverage is incomplete for 2026/)).toBeInTheDocument();
    expect(screen.queryByText(/are not available/)).not.toBeInTheDocument();
  });

  it('does not warn when all regional axes are covered', async () => {
    mount();
    await screen.findByText('8h/day, 5 days/week');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('does not treat an empty coverage object as confirmed data', async () => {
    mocks.get.mockResolvedValueOnce({ ...regional, holiday_coverage: {} });
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Error');
    expect(screen.queryByText(/8h\/day/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('8h/day, 5 days/week')).toBeInTheDocument();
  });

  it('uses persisted years and warns when dates extend beyond recorded coverage', () => {
    mount({ ...plan, metadata_: { calendar: { work_days: [0, 1, 2, 3, 4], regional_holiday_country: 'DE',
      holiday_coverage: [{ ...complete(2026), omitted: ['Festival'] }] } } });
    expect(screen.getByText(/coverage is incomplete for 2026/)).toBeInTheDocument();
    expect(screen.getByText(/are not available for 2027/)).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it('does not substitute regional warnings for an explicit schedule calendar', () => {
    const { container } = mount({ ...plan, metadata_: { calendar: { work_days: [0, 2, 4], exceptions: [] } } });
    expect(container).toBeEmptyDOMElement();
    expect(mocks.get).not.toHaveBeenCalled();
    expect(mocks.calendars).not.toHaveBeenCalled();
  });

  it('does not substitute regional warnings for the project default calendar', async () => {
    mocks.calendars.mockResolvedValue([{ id: 'c1', project_id: 'p1', is_default: true }]);
    const { container } = mount();
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it('switches schedules without keeping warnings from the previous persisted calendar', () => {
    const view = mount({ ...plan, metadata_: { calendar: { work_days: [0, 1], regional_holiday_country: 'PT', holiday_coverage: [] } } });
    expect(screen.getByText(/are not available for 2026, 2027/)).toBeInTheDocument();
    view.switchTo({ ...plan, id: 's2', metadata_: { calendar: { work_days: [0, 1], exceptions: [] } } });
    expect(screen.queryByText(/are not available/)).not.toBeInTheDocument();
  });
});
