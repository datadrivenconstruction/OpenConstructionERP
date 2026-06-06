// OpenConstructionERP - AI Chat read-renderer deep links (CONN-80).
//
// The chat tool handlers already serialize the primary key on every row
// (project id, boq_id + position id, validation report id, risk id). These
// tests pin that each read renderer turns those ids into a one-click jump to
// the real module screen via react-router navigate() - never a dead display.
//
// The global test setup (src/test/setup.ts) mocks react-router-dom so
// useNavigate() returns a vi.fn(). We override it here with a captured spy so
// we can assert the exact path each affordance navigates to.

import { describe, expect, it, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const navigateSpy = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateSpy,
  };
});

import ProjectsGridRenderer from '../full-page/right/renderers/ProjectsGridRenderer';
import ProjectSummaryRenderer from '../full-page/right/renderers/ProjectSummaryRenderer';
import BOQRenderer from '../full-page/right/renderers/BOQRenderer';
import ScheduleRenderer from '../full-page/right/renderers/ScheduleRenderer';
import ValidationRenderer from '../full-page/right/renderers/ValidationRenderer';
import RiskMatrixRenderer from '../full-page/right/renderers/RiskMatrixRenderer';

beforeEach(() => {
  navigateSpy.mockClear();
});

describe('chat renderer deep links (CONN-80)', () => {
  it('ProjectsGrid card navigates to /projects/{id}', () => {
    render(
      <ProjectsGridRenderer
        data={{ projects: [{ id: 'p-1', name: 'Berlin Tower', status: 'active' }], total: 1 }}
      />,
    );
    fireEvent.click(screen.getByText('Berlin Tower'));
    expect(navigateSpy).toHaveBeenCalledWith('/projects/p-1');
  });

  it('ProjectSummary "Open project" navigates to /projects/{id}', () => {
    render(<ProjectSummaryRenderer data={{ id: 'p-2', name: 'Munich Hall' }} />);
    fireEvent.click(screen.getByText('Open project'));
    expect(navigateSpy).toHaveBeenCalledWith('/projects/p-2');
  });

  it('BOQ row deep-links into the BOQ editor with a highlighted position', () => {
    render(
      <BOQRenderer
        data={{
          boq_id: 'boq-9',
          positions: [
            { id: 'pos-1', ordinal: '01.001', description: 'Concrete', quantity: 10, unit_rate: 5 },
          ],
        }}
      />,
    );
    fireEvent.click(screen.getByText('Concrete'));
    expect(navigateSpy).toHaveBeenCalledWith('/boq/boq-9?highlight=pos-1');
  });

  it('BOQ footer "Open in BOQ" navigates to /boq/{boq_id}', () => {
    render(
      <BOQRenderer
        data={{
          boq_id: 'boq-9',
          positions: [{ id: 'pos-1', ordinal: '01.001', description: 'X', quantity: 1, unit_rate: 1 }],
        }}
      />,
    );
    fireEvent.click(screen.getByText('Open in BOQ'));
    expect(navigateSpy).toHaveBeenCalledWith('/boq/boq-9');
  });

  it('BOQ rows are NOT clickable when no boq_id is on the envelope', () => {
    render(
      <BOQRenderer data={{ positions: [{ id: 'pos-1', description: 'Loose', quantity: 1, unit_rate: 1 }] }} />,
    );
    fireEvent.click(screen.getByText('Loose'));
    expect(navigateSpy).not.toHaveBeenCalled();
    expect(screen.queryByText('Open in BOQ')).toBeNull();
  });

  it('Schedule footer navigates to /schedule', () => {
    render(
      <ScheduleRenderer
        data={{ activities: [{ id: 'a-1', name: 'Excavate', start_date: '2026-01-01', end_date: '2026-01-05' }] }}
      />,
    );
    fireEvent.click(screen.getByText('Open in 4D Schedule'));
    expect(navigateSpy).toHaveBeenCalledWith('/schedule');
  });

  it('Validation footer navigates to /validation', () => {
    render(
      <ValidationRenderer
        data={{ reports: [{ id: 'r-1', rule_set: 'din276', status: 'warnings' }] }}
      />,
    );
    fireEvent.click(screen.getByText('Open Validation'));
    expect(navigateSpy).toHaveBeenCalledWith('/validation');
  });

  it('Risk footer navigates to /risks', () => {
    render(
      <RiskMatrixRenderer
        data={{ risks: [{ id: 'k-1', title: 'Weather delay', probability: 3, impact_severity: 4 }], total: 1 }}
      />,
    );
    fireEvent.click(screen.getByText('Open Risk Register'));
    expect(navigateSpy).toHaveBeenCalledWith('/risks');
  });
});
