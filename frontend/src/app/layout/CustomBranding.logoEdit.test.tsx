// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The quick edit button beside the sidebar logo: it goes off when a logo first
 * appears, wherever it was set, and only the Settings switch brings it back.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const apiPut = vi.fn().mockResolvedValue({});
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  apiPut: (...args: unknown[]) => apiPut(...args),
}));

import { useAuthStore } from '@/stores/useAuthStore';
import { logoEditAfterLogoChange, useBrandingStore } from '@/stores/useBrandingStore';
import { CustomBranding } from './CustomBranding';

const LOGO = 'data:image/png;base64,QUJD';
const OTHER = 'data:image/png;base64,REVG';
const pencil = () => screen.queryByTitle('Add your logo or company name');

function renderBrand() {
  render(
    <MemoryRouter>
      <CustomBranding iconified={false} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  apiPut.mockClear();
  useBrandingStore.getState().reset();
  useBrandingStore.getState().setOptions(null);
  useAuthStore.setState({ userRole: 'admin' } as never);
});

afterEach(() => {
  cleanup();
  useAuthStore.setState({ userRole: null } as never);
});

describe('logoEditAfterLogoChange', () => {
  it('turns the button off only when the first logo appears', () => {
    expect(logoEditAfterLogoChange(null, LOGO, true)).toBe(false);
    expect(logoEditAfterLogoChange(LOGO, OTHER, true)).toBe(true);
    expect(logoEditAfterLogoChange(LOGO, null, false)).toBe(false);
    expect(logoEditAfterLogoChange(null, null, true)).toBe(true);
  });
});

describe('the sidebar edit button', () => {
  it('shows to an admin while no logo is set', () => {
    renderBrand();
    expect(pencil()).not.toBeNull();
  });

  it('disappears once a logo is set, and the choice is stored', () => {
    renderBrand();
    act(() => useBrandingStore.getState().setLogo(LOGO));
    expect(pencil()).toBeNull();
    expect(useBrandingStore.getState().options.showLogoEdit).toBe(false);
    expect(JSON.parse(localStorage.getItem('oe_branding_options_v1')!).showLogoEdit).toBe(false);
  });

  it('comes back from the Settings switch and stays on when the logo is replaced', () => {
    useBrandingStore.getState().setLogo(LOGO);
    renderBrand();
    expect(pencil()).toBeNull();
    act(() => useBrandingStore.getState().setOptions({ show_logo_edit: true }));
    expect(pencil()).not.toBeNull();
    act(() => useBrandingStore.getState().setLogo(OTHER));
    expect(pencil()).not.toBeNull();
  });

  it('a company name alone keeps the button', () => {
    renderBrand();
    act(() => useBrandingStore.getState().setCompanyName('Acme Bau'));
    expect(pencil()).not.toBeNull();
  });

  it('sends the switch with the brand, so the workspace keeps the same rule', async () => {
    useBrandingStore.getState().setLogo(LOGO);
    await useBrandingStore.getState().persistToServer();
    expect(apiPut).toHaveBeenCalledWith('/v1/branding/', expect.objectContaining({ mode: 'logo', show_logo_edit: false }));
  });
});
