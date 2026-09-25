// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The Simple / Advanced mode: a choice follows the login, a default writes
 * nothing, and one user's cached choice does not leak to the next.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiGet = vi.fn();
const apiPut = vi.fn();

vi.mock('@/shared/lib/api', () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPut: (...args: unknown[]) => apiPut(...args),
}));

async function freshStore() {
  vi.resetModules();
  return import('./useViewModeStore');
}

beforeEach(() => {
  localStorage.clear();
  apiGet.mockReset();
  apiPut.mockReset();
  apiPut.mockResolvedValue({});
});

describe('useViewModeStore', () => {
  it('a default is shown but never stored, here or on the server', async () => {
    apiGet.mockResolvedValue({ mode: null });
    const { useViewModeStore, hydrateViewModeFromServer } = await freshStore();
    await hydrateViewModeFromServer('u1');

    useViewModeStore.getState().applyDefault('advanced');

    expect(useViewModeStore.getState().mode).toBe('advanced');
    expect(useViewModeStore.getState().chosen).toBe(false);
    expect(localStorage.getItem('oe_view_mode')).toBeNull();
    expect(apiPut).not.toHaveBeenCalled();
  });

  it('a pick is stored on the server and beats any later default', async () => {
    apiGet.mockResolvedValue({ mode: null });
    const { useViewModeStore, hydrateViewModeFromServer } = await freshStore();
    await hydrateViewModeFromServer('u1');

    useViewModeStore.getState().setMode('simple');
    useViewModeStore.getState().applyDefault('advanced');

    expect(useViewModeStore.getState().mode).toBe('simple');
    expect(apiPut).toHaveBeenCalledWith('/v1/users/me/view-mode/', { mode: 'simple' });
  });

  it('the server choice wins over what this browser remembers', async () => {
    localStorage.setItem('oe_view_mode', 'simple');
    apiGet.mockResolvedValue({ mode: 'advanced' });
    const { useViewModeStore, hydrateViewModeFromServer } = await freshStore();
    expect(useViewModeStore.getState().mode).toBe('simple');

    await hydrateViewModeFromServer('u1');

    expect(useViewModeStore.getState().mode).toBe('advanced');
    expect(useViewModeStore.getState().chosen).toBe(true);
    expect(localStorage.getItem('oe_view_mode')).toBe('advanced');
    expect(apiPut).not.toHaveBeenCalled();
  });

  it("another user's cached choice gives way to the default", async () => {
    localStorage.setItem('oe_view_mode', 'simple');
    localStorage.setItem('oe_view_mode_owner', 'someone-else');
    apiGet.mockResolvedValue({ mode: null });
    const { useViewModeStore, hydrateViewModeFromServer } = await freshStore();

    await hydrateViewModeFromServer('u1');
    useViewModeStore.getState().applyDefault('advanced');

    expect(useViewModeStore.getState().mode).toBe('advanced');
    expect(localStorage.getItem('oe_view_mode')).toBeNull();
  });

  it('a legacy per-browser choice is kept but not promoted to the server', async () => {
    localStorage.setItem('oe_view_mode', 'simple');
    apiGet.mockResolvedValue({ mode: null });
    const { useViewModeStore, hydrateViewModeFromServer } = await freshStore();

    await hydrateViewModeFromServer('u1');
    useViewModeStore.getState().applyDefault('advanced');

    expect(useViewModeStore.getState().mode).toBe('simple');
    expect(apiPut).not.toHaveBeenCalled();
  });
});
