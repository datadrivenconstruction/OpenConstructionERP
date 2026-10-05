// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The compact locked card that stands in for a panel.

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const template = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
      return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

import { meFixture } from './__fixtures__/me';
import { LockedPanelCard } from './LockedPanelCard';
import type { TrainerLockMode } from './LockedModulePage';
import type { TrainerMe } from './types';
import { useTrainerUiStore } from './useTrainerUiStore';

function markupsLocked(): TrainerMe {
  const me = structuredClone(meFixture);
  me.unlocks = me.unlocks.map((u) => (u.lock_id === 'boq.markups_panel' ? { ...u, state: 'locked' as const } : u));
  me.tasks = me.tasks.map((t) => (t.n === 1 ? { ...t, status: 'in_progress' as const } : t));
  return me;
}

function renderCard(mode: TrainerLockMode, anchorId: string | null = 'boq-markups-panel') {
  return render(
    <MemoryRouter initialEntries={['/boq/b1']}>
      <LockedPanelCard lockId="boq.markups_panel" anchorId={anchorId} mode={mode} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useTrainerUiStore.getState().reset();
});
afterEach(() => cleanup());

describe('LockedPanelCard', () => {
  it('takes over the panel id and uses a section heading, not a page heading', () => {
    renderCard({ state: 'enrolled', me: markupsLocked(), refetch: vi.fn() });
    const card = screen.getByTestId('trainer-locked-panel');
    expect(card).toHaveAttribute('id', 'boq-markups-panel');
    expect(within(card).getByRole('heading', { level: 2, name: 'Markups opens after task 1' })).toBeInTheDocument();
    expect(within(card).queryByRole('heading', { level: 1 })).toBeNull();
    expect(within(card).getByRole('link', { name: 'Go to task 1' })).toBeInTheDocument();
    expect(
      within(card).getByText('Your project and everything you entered stay as they are while a module is locked.'),
    ).toBeInTheDocument();
  });

  it('without an anchor it carries no id', () => {
    renderCard({ state: 'enrolled', me: markupsLocked(), refetch: vi.fn() }, null);
    expect(screen.getByTestId('trainer-locked-panel')).not.toHaveAttribute('id');
  });

  it('error variant inside the card: the reason, Retry and the course map', () => {
    const refetch = vi.fn();
    renderCard({ state: 'error', me: null, refetch });
    const card = screen.getByTestId('trainer-locked-panel');
    const alert = within(card).getByRole('alert');
    expect(alert).toHaveTextContent('Your course did not load');
    fireEvent.click(within(alert).getByRole('button'));
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(within(card).getByRole('link', { name: 'Course map' })).toHaveAttribute('href', '/academy');
  });

  it('loading variant: a status, no content', () => {
    renderCard({ state: 'loading', me: null, refetch: vi.fn() });
    expect(screen.getByRole('status')).toHaveTextContent('Loading your course');
    expect(screen.queryByRole('heading')).toBeNull();
  });
});
