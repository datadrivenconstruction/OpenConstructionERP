// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The "Your company" block of the look step: an admin drafts the company name
 * and logo with a live preview; Apply writes them through the branding store
 * and the server, Skip leaves the brand as it was.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const apiPut = vi.fn().mockResolvedValue({});
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  apiPut: (...args: unknown[]) => apiPut(...args),
}));

import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { BRANDING_MAX_LOGO_BYTES, useBrandingStore } from '@/stores/useBrandingStore';
import { StepLook } from '../StepLook';

const png = (bytes = 8) => new File([new Uint8Array(bytes)], 'logo.png', { type: 'image/png' });

function renderStep() {
  const onNext = vi.fn();
  render(<StepLook onNext={onNext} onBack={vi.fn()} />);
  return { onNext };
}

const upload = (file: File) =>
  fireEvent.change(screen.getByTestId('onboarding-brand-file'), { target: { files: [file] } });

beforeEach(() => {
  localStorage.clear();
  const s = useAppearanceStore.getState();
  s.followWorkspace();
  s.setWorkspaceDefault(null);
  s.followWorkspaceMenu();
  s.setWorkspaceMenu(null);
  useBrandingStore.getState().reset();
  useBrandingStore.getState().setOptions(null);
  apiPut.mockClear();
  useAuthStore.setState({ userRole: 'admin' } as never);
});

afterEach(() => {
  cleanup();
  useAuthStore.setState({ userRole: null } as never);
});

describe('<StepLook> company brand', () => {
  it('is not offered to a non-admin, as in Settings', () => {
    useAuthStore.setState({ userRole: 'editor' } as never);
    renderStep();
    expect(screen.queryByTestId('onboarding-brand')).toBeNull();
  });

  it('previews a typed name and an uploaded logo in the mini menu before Apply', async () => {
    renderStep();
    expect(screen.queryByTestId('look-preview-brand')).toBeNull();
    fireEvent.change(screen.getByPlaceholderText('Acme Construction GmbH'), { target: { value: 'Acme Bau' } });
    expect(screen.getByTestId('look-preview-brand').textContent).toBe('Acme Bau');

    upload(png());
    await waitFor(() => expect(screen.getByTestId('look-preview-brand').querySelector('img')).not.toBeNull());
    expect(screen.getByRole('img', { name: 'Current logo' }).getAttribute('src')).toMatch(/^data:image\/png;base64,/);
    // Nothing reaches the app before Apply.
    expect(useBrandingStore.getState().mode).toBe('default');
  });

  it('takes a dropped file as well', async () => {
    renderStep();
    fireEvent.drop(screen.getByTestId('onboarding-brand-drop'), { dataTransfer: { files: [png()] } });
    await waitFor(() => expect(screen.getByRole('img', { name: 'Current logo' })).toBeTruthy());
  });

  it('refuses a file of the wrong type or over the size limit, saying why', async () => {
    renderStep();
    upload(new File(['x'], 'logo.gif', { type: 'image/gif' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Use an SVG, PNG, WebP or JPEG file.');
    upload(png(BRANDING_MAX_LOGO_BYTES + 1));
    expect((await screen.findByRole('alert')).textContent).toBe('The file is larger than 2 MB.');
    expect(screen.queryByRole('img', { name: 'Current logo' })).toBeNull();
  });

  it('Remove clears the drafted logo', async () => {
    renderStep();
    upload(png());
    await screen.findByRole('img', { name: 'Current logo' });
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(screen.queryByRole('img', { name: 'Current logo' })).toBeNull();
    expect(screen.getByTestId('onboarding-brand-drop')).toBeTruthy();
  });

  it('Apply saves name and logo for the workspace and turns the menu edit button off', async () => {
    const { onNext } = renderStep();
    fireEvent.change(screen.getByPlaceholderText('Acme Construction GmbH'), { target: { value: 'Acme Bau' } });
    upload(png());
    await screen.findByRole('img', { name: 'Current logo' });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    const b = useBrandingStore.getState();
    expect(b.mode).toBe('logo');
    expect(b.companyName).toBe('Acme Bau');
    expect(b.options.showLogoEdit).toBe(false);
    expect(apiPut).toHaveBeenCalledWith(
      '/v1/branding/',
      expect.objectContaining({ mode: 'logo', company_name: 'Acme Bau', show_logo_edit: false }),
    );
  });

  it('Apply with the brand untouched sends only the look', async () => {
    const { onNext } = renderStep();
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    expect(apiPut).toHaveBeenCalledTimes(1);
    expect(apiPut.mock.calls[0]?.[1]).toHaveProperty('appearance');
  });

  it('Skip leaves the brand as it was', async () => {
    const { onNext } = renderStep();
    upload(png());
    await screen.findByRole('img', { name: 'Current logo' });
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }));
    expect(onNext).toHaveBeenCalledTimes(1);
    expect(useBrandingStore.getState().mode).toBe('default');
    expect(apiPut).not.toHaveBeenCalled();
  });
});
