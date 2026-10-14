// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The page's empty, loading-done and error states, and the proof that every
// design key the feature uses resolves in both English and German.

import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', async () => (await import('./i18nMock')).i18nMockModule);
vi.mock('@/features/teams/api', () => ({ listRoster: vi.fn(async () => ({ items: [], total: 0 })) }));
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    getSetup: vi.fn(),
    createSetup: vi.fn(),
    listSchemes: vi.fn(),
    listRoles: vi.fn(),
    listOptions: vi.fn(),
    listWbs: vi.fn(),
    listDeliverables: vi.fn(),
    listDrawings: vi.fn(),
    listReadiness: vi.fn(),
    listValidation: vi.fn(),
    listUnresolvedWbs: vi.fn(),
  };
});

import en from '@/app/locales/en';
import de from '@/app/locales/de';
import { ApiError } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import * as api from '../api';
import { DesignManagementPage } from '../DesignManagementPage';
import { ERROR_TEXT } from '../errors';
import { ALL_KEY_MAPS } from '../labels';
import { UI } from '../text';
import { drawing, readiness, setup, wbsNode } from './fixtures';

const mocked = vi.mocked(api);

function renderPage(path = '/projects/p1/design') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/projects/:projectId/design" element={<DesignManagementPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function withSetup() {
  mocked.getSetup.mockResolvedValue(setup());
  mocked.listRoles.mockResolvedValue([]);
  mocked.listOptions.mockImplementation(async (_project, kind) => ({ kind, available: false, reason: 'source_not_installed', items: [] }));
  mocked.listWbs.mockResolvedValue([]);
  mocked.listDeliverables.mockResolvedValue([]);
  mocked.listDrawings.mockResolvedValue([]);
  mocked.listReadiness.mockResolvedValue([]);
  mocked.listValidation.mockResolvedValue([]);
  mocked.listUnresolvedWbs.mockResolvedValue([]);
}

describe('DesignManagementPage states', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    useAuthStore.setState({ userRole: 'manager' });
    mocked.listSchemes.mockResolvedValue([
      {
        kind: 'drawing_numbering',
        source: 'shipped',
        id: 'simple_sequential',
        code: 'simple_sequential',
        name: { key: 'design.catalogue.simple_sequential.name', text: null },
        state: 'published',
        versions: [1],
        latest_version: 1,
        review_status: 'verified',
        jurisdiction_countries: [],
      },
      {
        kind: 'drawing_numbering',
        source: 'tenant',
        id: 'draft_scheme',
        code: 'draft_scheme',
        name: { key: null, text: { en: 'Unfinished scheme' } },
        state: 'draft',
        versions: [],
        latest_version: null,
        review_status: 'unverified',
        jurisdiction_countries: [],
      },
    ]);
  });
  afterEach(cleanup);

  it('a project without a setup says what to do first and offers the published schemes', async () => {
    mocked.getSetup.mockRejectedValue(
      new ApiError(404, 'Not Found', { detail: { code: 'setup_missing', message: 'Design management is not set up for this project yet.' } }),
    );
    renderPage();
    expect(await screen.findByText('Design management is not set up yet')).toBeInTheDocument();
    expect(await screen.findByText(en.translation['design.catalogue.simple_sequential.name']!)).toBeInTheDocument();
    // a scheme that is not published cannot be chosen
    expect(screen.queryByText('Unfinished scheme')).toBeNull();
    expect(screen.getByTestId('setup-save')).toHaveTextContent('Set up design management');
    expect(mocked.listRoles).not.toHaveBeenCalled();
  });

  it('a refused setup shows the reason the server gave', async () => {
    mocked.getSetup.mockRejectedValue(new ApiError(404, 'Not Found', { detail: { code: 'setup_missing', message: 'No setup' } }));
    mocked.createSetup.mockRejectedValue(
      new ApiError(403, 'Forbidden', { detail: { code: 'project_not_found', message: 'Project not found.' } }),
    );
    renderPage();
    fireEvent.click(await screen.findByTestId('setup-save'));
    expect(await screen.findByTestId('setup-refusal')).toHaveTextContent('Project not found.');
    expect(mocked.createSetup).toHaveBeenCalledWith('p1', { four_eyes_release: true });
  });

  it('a failing setup request shows the error, not the empty state', async () => {
    mocked.getSetup.mockRejectedValue(new ApiError(500, 'Server Error', { detail: 'database unavailable' }));
    renderPage();
    expect(await screen.findByText('Design management could not be loaded')).toBeInTheDocument();
    expect(screen.queryByText('Design management is not set up yet')).toBeNull();
  });

  it('a 404 for a project the user cannot see is an error, not "set it up"', async () => {
    mocked.getSetup.mockRejectedValue(
      new ApiError(404, 'Not Found', { detail: { code: 'project_not_found', message: 'Project not found.' } }),
    );
    renderPage();
    expect(await screen.findByText('Design management could not be loaded')).toBeInTheDocument();
    expect(screen.queryByTestId('setup-save')).toBeNull();
  });

  it('a set-up project without phases opens on the overview and points to project governance', async () => {
    withSetup();
    renderPage();
    expect(await screen.findByText('No phases yet')).toBeInTheDocument();
    expect(screen.getByText('Open project governance')).toBeInTheDocument();
    expect(await screen.findByTestId('checks-passed')).toHaveTextContent('Every check passed.');
  });

  it('the overview says per phase what is still open', async () => {
    withSetup();
    mocked.listReadiness.mockResolvedValue([
      readiness({ open_deliverables: ['DL-001', 'DL-002'], open_major_comments: 1 }),
      readiness({ code: 'concept', order: 1, name: { key: null, text: { en: 'Concept design' } }, met: true }),
    ]);
    mocked.listValidation.mockResolvedValue([
      { rule_id: 'wbs_code_unique', passed: false, severity: 'error', message: 'Code 1.2 is used twice.', element_ref: 'w2', suggestion: 'Rename one of them.' },
      { rule_id: 'drawing_number_matches_scheme', passed: true, severity: 'error', message: 'ok', element_ref: null, suggestion: null },
    ]);
    renderPage();
    const cards = await screen.findAllByTestId('readiness-card');
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveTextContent('Permit design');
    expect(cards[0]).toHaveTextContent('2 schedule lines not accepted:');
    expect(cards[0]).toHaveTextContent('1 major review comment still open');
    expect(cards[1]).toHaveTextContent('Nothing is open for this phase.');
    const findings = await screen.findAllByTestId('check-finding');
    expect(findings).toHaveLength(1);
    expect(findings[0]).toHaveTextContent('Code 1.2 is used twice.');
  });

  it('on a project without gates the overview shows one row for the whole project and no filing action', async () => {
    withSetup();
    mocked.getSetup.mockResolvedValue(setup({ phases: [], gates_in_use: false }));
    mocked.listReadiness.mockResolvedValue([readiness({ code: null, order: 0, name: null, open_deliverables: ['DL-001'] })]);
    renderPage();
    const card = await screen.findByTestId('readiness-card');
    expect(card).toHaveTextContent('Whole project');
    expect(await screen.findByTestId('no-frame-document')).toHaveTextContent('This project does not use gates');
    expect(screen.queryByTestId('file-register')).toBeNull();
    expect(screen.getByTestId('export-register-pdf')).toBeEnabled();
  });

  it('with gates the registers can be filed as a frame document', async () => {
    withSetup();
    renderPage();
    expect(await screen.findByTestId('file-register')).toBeEnabled();
    expect(screen.queryByTestId('no-frame-document')).toBeNull();
  });

  it('a viewer sees the registers but no add, edit or filing buttons', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    withSetup();
    renderPage('/projects/p1/design?tab=wbs');
    expect(await screen.findByTestId('design-wbs-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('wbs-add')).toBeNull();
    cleanup();
    renderPage();
    expect(await screen.findByTestId('export-register-pdf')).toBeEnabled();
    expect(screen.queryByTestId('file-register')).toBeNull();
  });

  it('an editor can add but cannot change the setup, which needs a manager', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    withSetup();
    renderPage('/projects/p1/design?tab=wbs');
    expect(await screen.findByTestId('wbs-add')).toBeEnabled();
    cleanup();
    renderPage('/projects/p1/design?tab=setup');
    expect(await screen.findByTestId('setup-scheme')).toBeInTheDocument();
    expect(screen.queryByTestId('setup-edit')).toBeNull();
    expect(screen.queryByTestId('scheme-change')).toBeNull();
  });

  it('the tab in the URL opens that list, and a failing list is an error', async () => {
    withSetup();
    mocked.listWbs.mockResolvedValue([wbsNode()]);
    mocked.listDrawings.mockResolvedValue([drawing()]);
    renderPage('/projects/p1/design?tab=wbs');
    expect(await screen.findByTestId('design-wbs-panel')).toBeInTheDocument();
    expect(screen.getByTestId('wbs-row')).toHaveTextContent('Building');
    cleanup();

    mocked.listRoles.mockRejectedValue(new ApiError(500, 'Server Error', { detail: 'database unavailable' }));
    renderPage('/projects/p1/design?tab=team');
    expect(await screen.findByText('Design management could not be loaded')).toBeInTheDocument();
    expect(screen.queryByTestId('design-team-panel')).toBeNull();
  });
});

describe('design i18n keys', () => {
  const featureDir = join(__dirname, '..');
  const sources = readdirSync(featureDir)
    .filter((f) => /\.(ts|tsx)$/.test(f) && f !== 'text.ts')
    .map((f) => readFileSync(join(featureDir, f), 'utf-8'))
    .join('\n');

  const used = new Set<string>();
  for (const m of sources.matchAll(/['"](design\.ui\.[a-z0-9_.]+)['"]/g)) used.add(m[1]!);
  for (const map of Object.values(ALL_KEY_MAPS)) {
    for (const [key] of Object.values(map)) used.add(key);
  }
  for (const code of Object.keys(ERROR_TEXT)) used.add(`design.errors.${code}`);

  const resolves = (table: Record<string, string>, key: string) => key in table || (`${key}_one` in table && `${key}_other` in table);

  it('finds the keys it is meant to check', () => {
    // A broken extraction would make the tests below pass on nothing.
    expect(used.size).toBeGreaterThan(450);
    expect(used.has('design.ui.permit.load_failed')).toBe(true);
    expect(used.has('design.ui.wbs.references')).toBe(true);
    expect(used.has('design.errors.setup_missing')).toBe(true);
    expect(used.has('design.cde_state.shared')).toBe(true);
  });

  it.each([
    ['en', en.translation],
    ['de', de.translation],
  ] as const)('every key resolves in %s', (_lang, table) => {
    expect([...used].filter((k) => !resolves(table, k))).toEqual([]);
  });

  it('every key a screen names has its English in text.ts', () => {
    const known = UI as Record<string, string>;
    const missing = [...used].filter((k) => k.startsWith('design.ui.') && !resolves(known, k));
    expect(missing).toEqual([]);
  });

  it('the English locale says what text.ts says', () => {
    const differing = Object.entries(UI).filter(([key, english]) => en.translation[key] !== english);
    expect(differing).toEqual([]);
  });

  it('every catalogue key the backend ships has a German name', () => {
    const catalogue = Object.keys(en.translation).filter((k) => k.startsWith('design.catalogue.'));
    expect(catalogue.length).toBeGreaterThan(100);
    expect(catalogue.filter((k) => !(k in de.translation))).toEqual([]);
  });

  it('German is translated, not copied from English', () => {
    const copied = Object.keys(en.translation).filter((k) => {
      if (!k.startsWith('design.')) return false;
      const e = en.translation[k];
      const d = de.translation[k];
      return !!e && e === d && e.split(' ').length > 2;
    });
    expect(copied).toEqual([]);
  });

  it('keeps the same placeholders in both languages', () => {
    const vars = (s: string | undefined) => (s?.match(/\{\{\w+\}\}/g) ?? []).sort().join();
    const differing = Object.keys(en.translation).filter(
      (k) => k.startsWith('design.') && vars(en.translation[k]) !== vars(de.translation[k]),
    );
    expect(differing).toEqual([]);
  });
});
