// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The readiness card tells the user, before any upload, whether matching
// can work for the project and what to do when it cannot. These tests pin
// one sentence per backend code and the two actions the card offers
// (open Setup & tools, switch catalogue).

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const addToast = vi.fn();
vi.mock('@/stores/useToastStore', () => {
  const state = { addToast: (...a: unknown[]) => addToast(...a) };
  const hook = (selector?: (s: typeof state) => unknown) =>
    typeof selector === 'function' ? selector(state) : state;
  return { useToastStore: hook };
});

vi.mock('@/features/match/api', () => ({
  setProjectCatalog: vi.fn().mockResolvedValue({ cost_database_id: 'IT_ROME' }),
}));

vi.mock('../api', async (orig) => {
  const actual = await orig<typeof import('../api')>();
  return { ...actual, fetchMatchReadiness: vi.fn(), installQdrantNative: vi.fn() };
});

import {
  fetchMatchReadiness,
  installQdrantNative,
  MatchApiError,
  type MatchReadiness,
} from '../api';
import { setProjectCatalog } from '@/features/match/api';
import { MatchReadinessCard } from '../MatchReadinessCard';

const fetchSpy = fetchMatchReadiness as ReturnType<typeof vi.fn>;
const installSpy = installQdrantNative as ReturnType<typeof vi.fn>;

const switchWarning = {
  code: 'binding_language_differs' as const,
  params: { bound: 'USA_USD', bound_language: 'en', language: 'it', catalogue: 'IT_ROME' },
};

function readiness(over: Partial<MatchReadiness>): MatchReadiness {
  return {
    can_match: true,
    blockers: [],
    warnings: [],
    project_region: 'Italy',
    project_language: 'it',
    project_country: 'IT',
    installed_languages: ['it'],
    recommended_catalogue: { region: 'IT_ROME', language: 'it', country_iso: 'IT', installed: true },
    bound_catalogue: null,
    can_change_catalogue: true,
    ...over,
  };
}

function renderCard(data: MatchReadiness | Error, onOpenSetup = vi.fn()) {
  if (data instanceof Error) fetchSpy.mockRejectedValue(data);
  else fetchSpy.mockResolvedValue(data);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MatchReadinessCard projectId="p-1" onOpenSetup={onOpenSetup} />
    </QueryClientProvider>,
  );
  return { onOpenSetup };
}

beforeEach(() => {
  fetchSpy.mockReset();
  installSpy.mockReset();
  addToast.mockReset();
  (setProjectCatalog as ReturnType<typeof vi.fn>).mockClear();
});
afterEach(() => cleanup());

describe('MatchReadinessCard', () => {
  it('says matching is ready and names the catalogue', async () => {
    renderCard(readiness({}));
    expect(await screen.findByTestId('match-readiness-ready')).toHaveTextContent(
      'Ready to match against IT_ROME.',
    );
    expect(fetchSpy).toHaveBeenCalledWith('p-1');
  });

  it.each([
    ['demo_mode', 'self-hosted install'],
    ['search_client_missing', 'pip install openconstructionerp[semantic-clients]'],
    ['search_unreachable', 'is not answering'],
    ['search_not_configured', 'CWICR_QDRANT_URL'],
  ] as const)('explains the %s blocker before any upload', async (code, phrase) => {
    renderCard(readiness({ can_match: false, blockers: [{ code, params: {} }] }));
    const card = await screen.findByTestId('match-readiness-blocked');
    expect(card).toHaveTextContent('Matching cannot run here yet');
    expect(card).toHaveTextContent(phrase);
  });

  it('names the catalogue to install and opens Setup & tools', async () => {
    const { onOpenSetup } = renderCard(
      readiness({
        can_match: false,
        blockers: [{ code: 'no_catalogue_installed', params: { catalogue: 'IT_ROME' } }],
      }),
    );
    const card = await screen.findByTestId('match-readiness-blocked');
    expect(card).toHaveTextContent('Install IT_ROME under Setup & tools');
    fireEvent.click(screen.getByRole('button', { name: /Open Setup & tools/ }));
    expect(onOpenSetup).toHaveBeenCalledTimes(1);
  });

  it('warns when no catalogue in the project language is installed', async () => {
    renderCard(
      readiness({
        installed_languages: ['en'],
        warnings: [
          { code: 'no_catalogue_for_language', params: { language: 'it', catalogue: 'IT_ROME' } },
        ],
      }),
    );
    const card = await screen.findByTestId('match-readiness-warnings');
    expect(card).toHaveTextContent('Install IT_ROME under Setup & tools for local rates.');
    // The language is named, not shown as a bare code.
    expect(card).not.toHaveTextContent('in it is installed');
  });

  it('warns about keyword-only matching without the language model', async () => {
    renderCard(readiness({ warnings: [{ code: 'embedder_missing', params: {} }] }));
    expect(await screen.findByTestId('match-readiness-warnings')).toHaveTextContent(
      'matches rely on keywords only',
    );
  });

  it('asks for a catalogue when the region spans several languages', async () => {
    renderCard(
      readiness({
        project_language: null,
        warnings: [{ code: 'region_language_unknown', params: { region: 'Nordics' } }],
      }),
    );
    expect(await screen.findByTestId('match-readiness-warnings')).toHaveTextContent(
      'Your project region (Nordics) spans several languages',
    );
  });

  it('offers the catalogue switch and performs it on click', async () => {
    renderCard(
      readiness({
        bound_catalogue: 'USA_USD',
        warnings: [
          {
            code: 'binding_language_differs',
            params: { bound: 'USA_USD', bound_language: 'en', language: 'it', catalogue: 'IT_ROME' },
          },
        ],
      }),
    );
    const card = await screen.findByTestId('match-readiness-warnings');
    expect(card).toHaveTextContent('Matches already confirmed in this project use USA_USD');
    fireEvent.click(screen.getByRole('button', { name: 'Switch to IT_ROME' }));
    // Asks first, and says what the switch does and does not touch.
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('applies to new matches only');
    expect(setProjectCatalog).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Switch catalogue' }));
    await waitFor(() => expect(setProjectCatalog).toHaveBeenCalledWith('p-1', 'IT_ROME'));
    await waitFor(() => expect(addToast).toHaveBeenCalled());
    expect(addToast.mock.calls[0]![0]).toMatchObject({ type: 'success' });
  });

  it('does not switch when the confirmation is cancelled', async () => {
    renderCard(readiness({ bound_catalogue: 'USA_USD', warnings: [switchWarning] }));
    await screen.findByTestId('match-readiness-warnings');
    fireEvent.click(screen.getByRole('button', { name: 'Switch to IT_ROME' }));
    await screen.findByRole('alertdialog');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(setProjectCatalog).not.toHaveBeenCalled();
  });

  it('offers the switch only to people who may change match settings', async () => {
    renderCard(
      readiness({ bound_catalogue: 'USA_USD', can_change_catalogue: false, warnings: [switchWarning] }),
    );
    const card = await screen.findByTestId('match-readiness-warnings');
    expect(card).toHaveTextContent('Matches already confirmed in this project use USA_USD');
    expect(screen.queryByRole('button', { name: 'Switch to IT_ROME' })).toBeNull();
    expect(card).toHaveTextContent('Ask the project owner');
  });

  it('says a failed switch in the reader\'s words', async () => {
    (setProjectCatalog as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('403 Forbidden'));
    renderCard(readiness({ bound_catalogue: 'USA_USD', warnings: [switchWarning] }));
    await screen.findByTestId('match-readiness-warnings');
    fireEvent.click(screen.getByRole('button', { name: 'Switch to IT_ROME' }));
    await screen.findByRole('alertdialog');
    fireEvent.click(screen.getByRole('button', { name: 'Switch catalogue' }));
    await waitFor(() => expect(addToast).toHaveBeenCalled());
    const toast = addToast.mock.calls[0]![0];
    expect(toast).toMatchObject({ type: 'error' });
    expect(toast.message).not.toContain('403');
  });

  it('shows a placeholder while it checks, not nothing', () => {
    fetchSpy.mockReturnValue(new Promise(() => {}));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MatchReadinessCard projectId="p-1" />
      </QueryClientProvider>,
    );
    expect(screen.getByTestId('match-readiness-loading')).toBeInTheDocument();
  });

  it.each([
    ['INTL', 'We could not tell the project\'s language from its region (INTL)'],
    ['', 'The project has no region or address'],
  ])('says plainly when the region %j tells no language', async (region, phrase) => {
    renderCard(
      readiness({
        project_region: region,
        project_language: null,
        recommended_catalogue: null,
        warnings: [{ code: 'region_unknown', params: { region } }],
      }),
    );
    const card = await screen.findByTestId('match-readiness-warnings');
    expect(card).toHaveTextContent(phrase);
    expect(card).not.toHaveTextContent('spans several languages');
  });

  it('degrades to a quiet note when the readiness check itself fails', async () => {
    renderCard(new Error('500 Internal server error'));
    expect(await screen.findByTestId('match-readiness-error')).toHaveTextContent(
      'Could not check whether matching is ready',
    );
  });

  // The page used to show a second card about the GENERAL vector database,
  // which said "running" while the catalogue store was down. This card is
  // now the only voice, so it carries that card's install and refresh.
  describe('search service down', () => {
    const down = (params: Record<string, string>) =>
      readiness({ can_match: false, blockers: [{ code: 'search_unreachable', params }] });

    it('offers the one-click install where it brings up the catalogue store', async () => {
      installSpy.mockResolvedValue({ reachable: true });
      renderCard(down({ local_install: 'available' }));
      const card = await screen.findByTestId('match-readiness-blocked');
      expect(card).toHaveTextContent('is not installed on this computer');
      fireEvent.click(screen.getByRole('button', { name: /Install Qdrant/ }));
      await waitFor(() => expect(installSpy).toHaveBeenCalledTimes(1));
      // The answer after the install comes from readiness, not from the
      // install route's own "reachable", which is about another store.
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
      expect(addToast.mock.calls[0]![0]).toMatchObject({ type: 'success' });
    });

    it('offers no install where it would change nothing', async () => {
      renderCard(down({}));
      const card = await screen.findByTestId('match-readiness-blocked');
      expect(card).toHaveTextContent('is not answering');
      expect(screen.queryByRole('button', { name: /Install Qdrant/ })).toBeNull();
    });

    it('re-checks on demand', async () => {
      renderCard(down({}));
      await screen.findByTestId('match-readiness-blocked');
      fireEvent.click(screen.getByRole('button', { name: 'Refresh status' }));
      await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    });

    it('says plainly when the user may not install', async () => {
      installSpy.mockRejectedValue(new MatchApiError('http', '403 Forbidden', 403, 'Forbidden'));
      renderCard(down({ local_install: 'available' }));
      await screen.findByTestId('match-readiness-blocked');
      fireEvent.click(screen.getByRole('button', { name: /Install Qdrant/ }));
      await waitFor(() => expect(addToast).toHaveBeenCalled());
      expect(addToast.mock.calls[0]![0]).toMatchObject({
        type: 'error',
        message: expect.stringContaining('administrator'),
      });
    });
  });
});
