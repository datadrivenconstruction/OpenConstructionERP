// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The punch list had a rework cost column in the API and no way to enter one
 * on screen, so every snag was unpriced. That left the QMS cost of poor
 * quality short, and it left nothing to base the retainage held back for open
 * items on. What is pinned here: the typed amount reaches the API as a dot
 * decimal in the project's currency, an empty box means "not priced" rather
 * than zero, a price recorded in another currency is never relabelled, and a
 * project with no currency cannot be priced into USD by accident.
 *
 * Run:  npx vitest run src/features/punchlist/reworkCost.test.tsx
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({
  fetchPunchItem: vi.fn(),
  updatePunchItem: vi.fn(),
  transitionPunchStatus: vi.fn(),
}));

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return { ...actual, ...api };
});

// The gallery fetches and uploads photos; none of that is under test here.
vi.mock('./PunchPhotoGallery', () => ({ PunchPhotoGallery: () => null }));

import type { PunchItem } from './api';
import { PunchDetailDrawer } from './PunchDetailDrawer';
import {
  formatReworkCost,
  parseReworkCostInput,
  projectCurrencyCode,
  reworkCostForInput,
} from './reworkCost';

function punch(over: Partial<PunchItem> = {}): PunchItem {
  return {
    id: 'p-1',
    project_id: 'proj-1',
    title: 'Touch up paint at stair core',
    description: '',
    priority: 'medium',
    status: 'open',
    category: null,
    assigned_to: null,
    assigned_to_name: null,
    due_date: null,
    document_id: null,
    page: null,
    location_x: null,
    location_y: null,
    photos: [],
    trade: null,
    resolution_notes: null,
    verified_by: null,
    verified_by_name: null,
    metadata: {},
    created_by: null,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    resolved_at: null,
    verified_at: null,
    rework_cost: null,
    rework_cost_currency: 'USD',
    ...over,
  };
}

function renderDrawer(item: PunchItem, projectCurrency: string) {
  api.fetchPunchItem.mockResolvedValue(item);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PunchDetailDrawer
        itemId={item.id}
        projectId={item.project_id}
        initialItem={item}
        projectCurrency={projectCurrency}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

const section = () => screen.getByTestId('punch-rework-cost');
const box = () => section().querySelector('input') as HTMLInputElement;

beforeEach(() => {
  api.fetchPunchItem.mockReset();
  api.updatePunchItem.mockReset();
  api.updatePunchItem.mockImplementation(async (_id: string, body: Partial<PunchItem>) => punch(body));
});

afterEach(() => cleanup());

describe('reading a typed rework cost', () => {
  it.each([
    ['1.250,50', '1250.50'],
    ['1,250.50', '1250.50'],
    ['48,60', '48.60'],
    ['€ 1250', '1250'],
    ['0', '0'],
  ])('reads %s as %s', (typed, sent) => {
    expect(parseReworkCostInput(typed)).toEqual({ ok: true, value: sent });
  });

  it('reads an empty box as not priced, which is not zero', () => {
    expect(parseReworkCostInput('   ')).toEqual({ ok: true, value: null });
  });

  it.each(['-5', 'abc', '12 EUR', '1,2,3'])('refuses %s', (typed) => {
    expect(parseReworkCostInput(typed)).toEqual({ ok: false });
  });

  it('shows an exponent the API used to store as a plain amount', () => {
    expect(reworkCostForInput('9E+2')).toBe('900');
    expect(reworkCostForInput('1250.5')).toBe('1250.5');
    expect(reworkCostForInput(null)).toBe('');
  });

  it('takes a project currency only when it is an ISO code', () => {
    expect(projectCurrencyCode(' eur ')).toBe('EUR');
    expect(projectCurrencyCode('')).toBe('');
    expect(projectCurrencyCode('EURO')).toBe('');
    expect(projectCurrencyCode(undefined)).toBe('');
  });

  it('formats a cost in the currency it was recorded in, and nothing for an unpriced item', () => {
    expect(formatReworkCost({ rework_cost: null, rework_cost_currency: 'EUR' })).toBeNull();
    expect(formatReworkCost({ rework_cost: '', rework_cost_currency: 'EUR' })).toBeNull();
    const shown = formatReworkCost({ rework_cost: '1250.5', rework_cost_currency: 'USD' }) ?? '';
    expect(shown).toMatch(/1,250\.50/);
    expect(shown).toMatch(/\$/);
  });
});

describe('the rework cost in the punch item drawer', () => {
  it('prices an unpriced item in the project currency', async () => {
    renderDrawer(punch(), 'EUR');

    expect(section().textContent).toContain('Not priced');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(box(), { target: { value: '1.250,50' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(api.updatePunchItem).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.updatePunchItem).mock.calls[0]?.slice(0, 2)).toEqual(['p-1', {
      rework_cost: '1250.50',
      rework_cost_currency: 'EUR',
    }]);
  });

  it('clears a price with an empty box, sending null and never a null currency', async () => {
    renderDrawer(punch({ rework_cost: '900', rework_cost_currency: 'EUR' }), 'EUR');

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(box().value).toBe('900');
    fireEvent.change(box(), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(api.updatePunchItem).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.updatePunchItem).mock.calls[0]?.slice(0, 2)).toEqual(['p-1', {
      rework_cost: null,
      rework_cost_currency: 'EUR',
    }]);
  });

  it('does not save an amount it cannot read', () => {
    renderDrawer(punch(), 'EUR');

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(box(), { target: { value: '-40' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(section().textContent).toContain('Enter an amount of zero or more');
    expect(api.updatePunchItem).not.toHaveBeenCalled();
  });

  it('never carries a price in another currency into the box under the new code', () => {
    renderDrawer(punch({ rework_cost: '1200', rework_cost_currency: 'USD' }), 'EUR');

    // Shown as recorded, in dollars.
    expect(section().textContent).toMatch(/\$/);
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    expect(box().value).toBe('');
    expect(section().textContent).toContain('The current cost is in USD');
  });

  it('offers no edit on a project without a currency', () => {
    renderDrawer(punch(), '');

    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(section().textContent).toContain("Set the project's currency before pricing items.");
  });
});
