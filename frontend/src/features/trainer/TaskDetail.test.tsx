// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

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
import { TaskDetail } from './TaskDetail';
import type { TaskSummary } from './types';
import { useTrainerUiStore } from './useTrainerUiStore';

const [t1, t2, t3, , t5] = meFixture.tasks as [TaskSummary, TaskSummary, TaskSummary, TaskSummary, TaskSummary];

function Probe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.hash}</div>;
}

function renderDetail(task: TaskSummary, next: TaskSummary | null = t2) {
  return render(
    <MemoryRouter initialEntries={['/academy']}>
      <Routes>
        <Route path="/academy" element={<TaskDetail task={task} nextTask={next} courseLocale="en-GB" id="d" />} />
        <Route path="*" element={<Probe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => useTrainerUiStore.getState().reset());
afterEach(() => cleanup());

describe('TaskDetail', () => {
  it('shows what is checked, where, how long, the video and what it opens', () => {
    renderDetail(t2);
    expect(screen.getByText('Task 2 · Bill of Quantities')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Add overheads and profit' })).toHaveAttribute('lang', 'en-GB');
    expect(screen.getByText('Type the overheads amount.')).toBeInTheDocument();
    expect(screen.getByText('About 20 min')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Markups on direct cost' })).toHaveAttribute('href', '/videos?episode=FX02');
    expect(screen.getByText('Bid Management')).toBeInTheDocument();
    expect(screen.getByText('Needs another look')).toBeInTheDocument();
  });

  it('Continue opens the task in the dock and goes to its screen with the anchor', () => {
    renderDetail(t2);
    fireEvent.click(screen.getByRole('button', { name: 'Continue in Bill of Quantities' }));
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b#boq-markups-panel',
    );
    const ui = useTrainerUiStore.getState();
    expect(ui.dockTaskId).toBe('t2-markups');
    expect(ui.dockOpen).toBe(true);
  });

  it('a task not started says Start task N', () => {
    renderDetail({ ...t2, status: 'not_started' });
    expect(screen.getByRole('button', { name: 'Start task 2' })).toBeInTheDocument();
  });

  it('a verified task can be opened again', () => {
    renderDetail(t1);
    fireEvent.click(screen.getByRole('button', { name: 'Open task' }));
    expect(useTrainerUiStore.getState().dockTaskId).toBe('t1-direct-cost');
  });

  it('a locked task says which task opens it and sends the learner to the open one', () => {
    renderDetail(t3);
    expect(screen.getByText(/This task opens after task 2\./)).toBeInTheDocument();
    expect(screen.getByText('Opens when task 2 passes.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Go to task 2' }));
    expect(useTrainerUiStore.getState().dockTaskId).toBe('t2-markups');
    expect(screen.getByTestId('location')).toHaveTextContent('/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b#boq-markups-panel');
  });

  it('a locked task with no open task to go to shows no dead button', () => {
    renderDetail(t3, null);
    expect(screen.queryByTestId('trainer-detail-action')).toBeNull();
  });

  it('the last task names the badge it earns', () => {
    renderDetail(t5);
    expect(screen.getByText('Earns')).toBeInTheDocument();
    expect(screen.getByText('Course badge')).toBeInTheDocument();
  });
});
