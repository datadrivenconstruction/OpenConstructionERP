// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The Finish step's summary: each choice is listed with a way back to the step
 * that changes it, and an admin also gets the brand and the team rows.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useBrandingStore } from '@/stores/useBrandingStore';
import { APPEARANCE_PRESETS } from '@/shared/lib/appearance';
import { STEP } from '../OnboardingStepper';
import { SetupSummary } from '../SetupSummary';

function renderSummary(props: Partial<Parameters<typeof SetupSummary>[0]> = {}) {
  const onEdit = vi.fn();
  const onLeave = vi.fn();
  render(
    <MemoryRouter>
      <SetupSummary
        packInstalled={false}
        presetLabel="General Contractor"
        enabledCount={12}
        language="en"
        onEdit={onEdit}
        onLeave={onLeave}
        {...props}
      />
    </MemoryRouter>,
  );
  return { onEdit, onLeave };
}

const row = (id: string) => screen.getByTestId(`setup-summary-${id}`);

beforeEach(() => {
  localStorage.clear();
  const s = useAppearanceStore.getState();
  s.followWorkspace();
  s.setWorkspaceDefault(null);
  s.followWorkspaceMenu();
  s.setWorkspaceMenu(null);
  useBrandingStore.getState().reset();
  useAuthStore.setState({ userRole: 'editor' } as never);
});

afterEach(() => {
  cleanup();
  useAuthStore.setState({ userRole: null } as never);
});

describe('<SetupSummary>', () => {
  it('lists language, profile and look, each with a Change that goes to its step', () => {
    const { onEdit } = renderSummary();
    expect(row('language').textContent).toContain('English');
    expect(row('profile').textContent).toContain('General Contractor · 12 modules');
    expect(row('look').textContent).toContain('Classic');

    fireEvent.click(screen.getByRole('button', { name: 'Change Language' }));
    fireEvent.click(screen.getByRole('button', { name: 'Change Profile and modules' }));
    fireEvent.click(screen.getByRole('button', { name: 'Change Look' }));
    expect(onEdit.mock.calls.map((c) => c[0])).toEqual([STEP.welcome, STEP.profile, STEP.look]);
  });

  it('names the applied style, or Custom for a mix', () => {
    useAppearanceStore.getState().setAppearance(APPEARANCE_PRESETS.find((p) => p.id === 'studio')!.value);
    renderSummary();
    expect(row('look').textContent).toContain('Studio');
    cleanup();
    useAppearanceStore.getState().setAppearance({ ...useAppearanceStore.getState().effective, accent: 'amber' });
    renderSummary();
    expect(row('look').textContent).toContain('Custom');
  });

  it('after a ready-made pack, the profile row says so and goes back to the pack', () => {
    const { onEdit } = renderSummary({ packInstalled: true });
    expect(row('profile').textContent).toContain('Ready-made Pack');
    fireEvent.click(within(row('profile')).getByRole('button'));
    expect(onEdit).toHaveBeenCalledWith(STEP.start);
  });

  it('shows the brand and team rows to an admin only', () => {
    renderSummary();
    expect(screen.queryByTestId('setup-summary-brand')).toBeNull();
    expect(screen.queryByTestId('setup-summary-team')).toBeNull();
  });

  it('an admin sees the brand as set and can open the users page', () => {
    useAuthStore.setState({ userRole: 'admin' } as never);
    useBrandingStore.getState().setCompanyName('Acme Bau');
    const { onEdit, onLeave } = renderSummary();
    expect(row('brand').textContent).toContain('Acme Bau');
    fireEvent.click(screen.getByRole('button', { name: 'Change Your company' }));
    expect(onEdit).toHaveBeenCalledWith(STEP.look);

    const link = within(row('team')).getByRole('link');
    expect(link.getAttribute('href')).toBe('/users');
    fireEvent.click(link);
    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it('an admin without a brand is told it is not set yet', () => {
    useAuthStore.setState({ userRole: 'admin' } as never);
    renderSummary();
    expect(row('brand').textContent).toContain('Not set yet');
  });
});
