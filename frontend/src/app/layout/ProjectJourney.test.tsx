// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ReactNode } from 'react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { act, render, screen, fireEvent, cleanup } from '@testing-library/react';
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

// The case index is a large lazy chunk; the map works without it.
vi.mock('@/features/cases/playbookModules', () => ({ playbooksForRoute: () => [] }));

import { ProjectJourneyButton } from './ProjectJourney';
import { JOURNEY_PHASES, resolveJourneyPhaseKey } from './projectJourneyData';

function openAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <ProjectJourneyButton />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByTestId('project-journey-button'));
}

afterEach(cleanup);

describe('ProjectJourney panel', () => {
  it('keeps the platform visible behind a light, blurred veil', () => {
    openAt('/boq');
    const veil = screen.getByTestId('project-journey-backdrop');
    expect(veil.className).toMatch(/bg-black\/25/);
    expect(veil.className).toMatch(/backdrop-blur/);
    expect(veil.className).not.toMatch(/bg-(white|surface-primary)(\s|$)/);
    expect(screen.getByTestId('project-journey-panel').className).toMatch(/max-w-5xl/);
  });

  it('shows progress, the current step and the next one', () => {
    openAt('/boq');
    const key = resolveJourneyPhaseKey('/boq')!;
    const idx = JOURNEY_PHASES.findIndex((p) => p.key === key);
    expect(screen.getByTestId('project-journey-progress').textContent).toBe(
      `Step ${idx + 1} of ${JOURNEY_PHASES.length}`,
    );
    expect(screen.getByTestId(`project-journey-node-${key}`).getAttribute('aria-current')).toBe('step');
    const current = screen.getByTestId('project-journey-current');
    expect(current.textContent).toContain(JOURNEY_PHASES[idx]!.name);
    const next = JOURNEY_PHASES[idx + 1]!;
    fireEvent.click(screen.getByTestId('project-journey-next'));
    expect(document.activeElement).toBe(screen.getByTestId(`project-journey-phase-${next.key}`));
  });

  it('says so when the screen is outside the line', () => {
    openAt('/zz-outside-the-line');
    expect(resolveJourneyPhaseKey('/zz-outside-the-line')).toBeNull();
    expect(screen.queryByTestId('project-journey-current')).toBeNull();
    expect(screen.getByTestId('project-journey-progress').textContent).toContain('Pick a step');
  });

  it('plays a step video over the map; Escape closes the video first', async () => {
    openAt('/boq');
    fireEvent.click(screen.getByTestId('project-journey-video'));
    await vi.waitFor(() => expect(screen.getAllByRole('dialog').length).toBe(2), { timeout: 60000 });
    // Let the lazily mounted player attach its key listener before pressing Escape.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.getByTestId('project-journey-panel')).toBeTruthy();
    await vi.waitFor(() => expect(screen.queryByTestId('video-player')).toBeNull(), { timeout: 30000 });
    expect(screen.getAllByRole('dialog').length).toBe(1);
  });
});
