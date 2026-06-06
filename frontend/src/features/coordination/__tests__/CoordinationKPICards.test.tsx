/**
 * CoordinationKPICards UI tests.
 *
 * No network — the component is pure presentation over the supplied
 * data object; we render with synthetic dashboards and assert each KPI
 * card surfaces the right number.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

// Override the global i18n mock with one that interpolates {{var}}
// placeholders. The default ``setup.ts`` mock returns ``defaultValue``
// raw, which is fine for static strings but loses ``{{n}} resolved`` →
// "5 resolved" for the KPI subtitle assertions below.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const defaultValue =
        opts && typeof opts === 'object' && 'defaultValue' in opts
          ? (opts.defaultValue as string)
          : key;
      if (!opts) return defaultValue;
      return defaultValue.replace(/\{\{(\w+)\}\}/g, (_, name) =>
        String(opts[name] ?? ''),
      );
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
}));

import { CoordinationKPICards } from '../CoordinationKPICards';
import type { CoordinationDashboard } from '../types';

// MoneyDisplay reads from the preferences store; provide a minimal shim
// so the tests run without bootstrapping the whole Zustand graph.
const __mockPrefState = { currency: 'EUR', numberLocale: 'en-US' };
vi.mock('@/stores/usePreferencesStore', () => ({
  usePreferencesStore: (sel?: (s: unknown) => unknown) =>
    sel ? sel(__mockPrefState) : __mockPrefState,
}));

const SAMPLE: CoordinationDashboard = {
  project_id: 'p-1',
  currency: 'EUR',
  as_of: '2026-05-21T14:30:00Z',
  federations: { count: 3, total_members: 12, total_elements: 48330 },
  clashes: {
    open_count: 47,
    resolved_count: 213,
    ignored_count: 8,
    delta_since_last_run: { new: 12, resolved: 5, reopened: 1 },
    last_run_at: '2026-05-21T13:00:00Z',
  },
  rule_packs: {
    installed_count: 5,
    last_check_pass_count: 4820,
    last_check_fail_count: 134,
    last_check_at: '2026-05-20T10:00:00Z',
  },
  smart_views: { user_count: 4, project_count: 12 },
  bcf_activity: {
    topics_exported_30d: 47,
    topics_imported_30d: 18,
    last_export_at: '2026-05-19T08:00:00Z',
  },
  open_cost_impact_total: 47820.5,
};

beforeEach(() => cleanup());

describe('CoordinationKPICards', () => {
  it('renders four cards with the expected primary numbers', () => {
    render(<CoordinationKPICards data={SAMPLE} />);
    expect(screen.getByTestId('kpi-open-clashes')).toHaveTextContent('47');
    expect(screen.getByTestId('kpi-rule-pack')).toHaveTextContent('5');
    expect(screen.getByTestId('kpi-federations')).toHaveTextContent('3');
    // Cost-impact uses MoneyDisplay (compact). 47820.5 rounds to 47.82K or
    // similar; we just assert the card is present.
    expect(screen.getByTestId('kpi-cost-impact')).toBeInTheDocument();
  });

  it('shows the delta chip when new clashes appeared', () => {
    render(<CoordinationKPICards data={SAMPLE} />);
    const delta = screen.getByTestId('kpi-open-clashes-delta');
    expect(delta).toBeInTheDocument();
    // v4.2.0 redesign uses an arrow-up icon + absolute value (no `+`
    // prefix) so direction reads from the chevron, not punctuation.
    expect(delta).toHaveTextContent(/12/);
  });

  it('shows the skeleton when isLoading and no data', () => {
    render(<CoordinationKPICards data={undefined} isLoading />);
    expect(screen.getByTestId('coordination-kpi-skeleton')).toBeInTheDocument();
  });

  it('renders the secondary "resolved" subtitle on the clashes card', () => {
    render(<CoordinationKPICards data={SAMPLE} />);
    const card = screen.getByTestId('kpi-open-clashes');
    expect(card).toHaveTextContent('213');
  });

  it('renders the secondary subtitle on the rule-pack card', () => {
    render(<CoordinationKPICards data={SAMPLE} />);
    const card = screen.getByTestId('kpi-rule-pack');
    expect(card).toHaveTextContent('4820');
    expect(card).toHaveTextContent('134');
  });

  it('renders the secondary subtitle on the federations card', () => {
    render(<CoordinationKPICards data={SAMPLE} />);
    const card = screen.getByTestId('kpi-federations');
    expect(card).toHaveTextContent('12');
    expect(card).toHaveTextContent('48330');
  });

  it('is not interactive without onNavigate', () => {
    render(<CoordinationKPICards data={SAMPLE} />);
    const card = screen.getByTestId('kpi-open-clashes');
    expect(card).not.toHaveAttribute('role', 'button');
    expect(card).not.toHaveAttribute('tabindex');
  });

  it('drills the clash + cost cards into the open clash list scoped to the project', () => {
    const onNavigate = vi.fn();
    render(
      <CoordinationKPICards
        data={SAMPLE}
        projectId="p-1"
        onNavigate={onNavigate}
      />,
    );
    const clashCard = screen.getByTestId('kpi-open-clashes');
    expect(clashCard).toHaveAttribute('role', 'button');
    expect(clashCard).toHaveAttribute('tabindex', '0');
    fireEvent.click(clashCard);
    expect(onNavigate).toHaveBeenLastCalledWith(
      '/clash?project=p-1&status=open',
    );

    fireEvent.click(screen.getByTestId('kpi-cost-impact'));
    expect(onNavigate).toHaveBeenLastCalledWith(
      '/clash?project=p-1&status=open',
    );
  });

  it('drills rule packs and federations into their own pages', () => {
    const onNavigate = vi.fn();
    render(
      <CoordinationKPICards
        data={SAMPLE}
        projectId="p-1"
        onNavigate={onNavigate}
      />,
    );
    fireEvent.click(screen.getByTestId('kpi-rule-pack'));
    expect(onNavigate).toHaveBeenLastCalledWith('/bim/rules');

    fireEvent.click(screen.getByTestId('kpi-federations'));
    expect(onNavigate).toHaveBeenLastCalledWith('/bim/federations');
  });

  it('activates the drill-down via the keyboard (Enter)', () => {
    const onNavigate = vi.fn();
    render(
      <CoordinationKPICards
        data={SAMPLE}
        projectId="p-1"
        onNavigate={onNavigate}
      />,
    );
    fireEvent.keyDown(screen.getByTestId('kpi-federations'), { key: 'Enter' });
    expect(onNavigate).toHaveBeenLastCalledWith('/bim/federations');
  });
});
