// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
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
vi.mock('@/shared/lib/useI18nReady', () => ({ useI18nReady: () => 0 }));

const modeState = vi.hoisted(() => ({ current: null as unknown }));
vi.mock('./useTrainerMode', () => ({ useTrainerMode: () => modeState.current }));

import { meFixture } from './__fixtures__/me';
import { TrainerHeaderChip } from './TrainerHeaderChip';
import type { TrainerMe } from './types';
import type { TrainerModeState } from './useTrainerMode';

function setMode(state: TrainerModeState, me: TrainerMe | null = null) {
  modeState.current = {
    state,
    academyMode: state !== 'off',
    known: true,
    active: state === 'enrolled',
    me,
    refetch: vi.fn(),
  };
}

function renderChip() {
  return render(
    <MemoryRouter>
      <TrainerHeaderChip />
    </MemoryRouter>,
  );
}

afterEach(() => cleanup());

describe('TrainerHeaderChip', () => {
  it('renders nothing when the trainer is off', () => {
    setMode('off');
    const { container } = renderChip();
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when there is no course', () => {
    setMode('none');
    const { container } = renderChip();
    expect(container).toBeEmptyDOMElement();
  });

  it.each(['checking', 'loading', 'error'] as const)('%s shows a plain Academy chip to the map', (state) => {
    setMode(state);
    renderChip();
    const link = screen.getByRole('link', { name: 'Academy' });
    expect(link).toHaveAttribute('href', '/academy');
  });

  it('enrolled: "Academy · Task 2 of 5" linking to the course map, plus the week goal', () => {
    setMode('enrolled', meFixture);
    renderChip();
    const link = screen.getByRole('link', { name: 'Academy · Task 2 of 5' });
    expect(link).toHaveAttribute('href', '/academy');
    expect(link).toHaveTextContent('2/5');
    expect(screen.getByTestId('trainer-header-week')).toHaveTextContent('Week goal 1/3');
  });

  it('no week from the API: no week pill', () => {
    setMode('enrolled', { ...meFixture, week: null });
    renderChip();
    expect(screen.queryByTestId('trainer-header-week')).toBeNull();
  });

  it('finished course says so', () => {
    setMode('enrolled', { ...meFixture, tasks: meFixture.tasks.map((t) => ({ ...t, status: 'passed' as const })) });
    renderChip();
    expect(screen.getByRole('link', { name: 'Academy · Course complete' })).toHaveAttribute('href', '/academy');
  });

  it('with every remaining task locked it still counts the first unpassed task', () => {
    setMode('enrolled', {
      ...meFixture,
      tasks: meFixture.tasks.map((t) => (t.status === 'passed' ? t : { ...t, status: 'locked' as const })),
    });
    renderChip();
    expect(screen.getByRole('link', { name: 'Academy · Task 2 of 5' })).toBeInTheDocument();
  });
});
