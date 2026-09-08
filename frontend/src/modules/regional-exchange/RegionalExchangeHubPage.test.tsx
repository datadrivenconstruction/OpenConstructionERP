// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The hub is the way into the twenty market screens, and it is now also the
// module's sidebar row, so what it has to keep true has grown.
//
// The original reason for this file has not changed and is worth restating,
// because it is the reason the assertions are shaped the way they are. The
// twenty country routes were mounted, tested, translated and shipped, and
// nothing anywhere under `frontend/src` linked to any of them: every gate the
// repo owns was green, because every gate asked whether the route mounts and
// none asked whether a person can get to it. So these tests assert
// reachability, not rendering.
//
// Two things are asserted that the old file did not.
//
// Reachability must not depend on the network. The market list is now served
// by the backend, and if a failed request could empty it, the twenty screens
// would go straight back to being reachable only by typing a URL, with the
// page looking merely empty rather than broken. So the strip is asserted
// against a catalogue request that fails.
//
// The capability words must come from the payload. This screen tells a user
// whether we can read their market's file, and the whole design of the
// endpoint behind it is that Python computes that from its registries. A test
// that let the page decide would be pinning the mirror we deliberately did not
// build, so the payload is varied and the screen is required to follow it.
//
// The API layer is mocked here, which is exactly how an import bug survived on
// the sibling page for a long time: a mocked client cannot tell you the request
// you send is one the server refuses. That is a real limit and it is why the
// assertions below are about routing, reachability and rendering, and why the
// wire shape of the import is tested against the real route elsewhere rather
// than here.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const apiGet = vi.fn();

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return {
    ...actual,
    apiGet: (path: string) => apiGet(path),
    downloadWithAuth: vi.fn(async () => undefined),
    getAuthToken: () => 'test-token',
  };
});

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (selector?: (s: { addToast: unknown }) => unknown) => {
    const state = { addToast: vi.fn() };
    return selector ? selector(state) : state.addToast;
  },
}));

vi.mock('@/stores/useProjectContextStore', () => ({
  useProjectContextStore: (selector?: (s: { activeProjectId: string | null }) => unknown) => {
    const state = { activeProjectId: null };
    return selector ? selector(state) : state;
  },
}));

import RegionalExchangeHubPage from './RegionalExchangeHubPage';
import { COUNTRY_TEMPLATES } from './regionalRegistry';
import { manifest } from './manifest';

const HUB_PATH = '/regional-exchange';

/** A catalogue payload in the shape the endpoint really sends. */
function catalogue(overrides: Record<string, unknown> = {}) {
  return {
    formats: [
      {
        format_id: 'gaeb_xml',
        name: 'GAEB DA XML 3.3',
        countries: ['DE', 'AT', 'CH', 'LU'],
        extensions: ['.x83', '.xml'],
        summary: 'The DACH interchange for a bill of quantities.',
        standard: 'GAEB DA XML 3.3',
        rule_packs: ['gaeb'],
        header_language: null,
        import_support: 'native',
        export_support: 'native',
        export_route: 'export/gaeb',
        export_extension: '.x83',
        export_media_type: 'application/xml',
      },
      {
        format_id: 'oenorm_a2063',
        name: 'ÖNORM A 2063',
        countries: ['AT'],
        extensions: ['.onlv', '.xml'],
        summary: "Austria's own bill of quantities interchange.",
        standard: 'ÖNORM A 2063',
        rule_packs: ['onorm'],
        header_language: null,
        import_support: 'assisted',
        export_support: 'none',
        export_route: null,
        export_extension: null,
        export_media_type: null,
      },
      {
        format_id: 'excel',
        name: 'Spreadsheet workbook',
        countries: [],
        extensions: ['.xlsx', '.csv'],
        summary: 'Any workbook with a row per item.',
        standard: '',
        rule_packs: [],
        header_language: null,
        import_support: 'native',
        export_support: 'native',
        export_route: 'export/excel',
        export_extension: '.xlsx',
        export_media_type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      },
    ],
    country: null,
    default_format_id: null,
    header_languages: ['en', 'de'],
    ...overrides,
  };
}

function renderHub() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[HUB_PATH]}>
        <RegionalExchangeHubPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiGet.mockReset();
  apiGet.mockImplementation(async (path: string) => {
    if (path.includes('exchange-formats')) return catalogue();
    return [];
  });
});

describe('the world exchange hub', () => {
  it('is the route the manifest enters the module by', () => {
    // First, so `routes[0]` is the hub and not whichever country happens to
    // sort first in the registry.
    expect(manifest.routes[0]?.path).toBe(HUB_PATH);
    expect(manifest.routes).toHaveLength(COUNTRY_TEMPLATES.length + 1);
  });

  it('is switched on by default, because a row for a module nobody enabled is no row', () => {
    expect(manifest.defaultEnabled).toBe(true);
  });

  it('offers every market that has a screen of its own', async () => {
    renderHub();
    const strip = await screen.findByTestId('exchange-market-strip');
    for (const tpl of COUNTRY_TEMPLATES) {
      expect(
        within(strip).getByTestId(`exchange-market-${tpl.countryCode.toUpperCase()}`),
        `${tpl.id} has a dedicated screen but its market is not offered`,
      ).toBeInTheDocument();
    }
  });

  it('reaches every country route the manifest mounts, and no other path', async () => {
    const user = userEvent.setup();
    renderHub();
    await screen.findByTestId('exchange-market-strip');

    const linked = new Set<string>();
    for (const tpl of COUNTRY_TEMPLATES) {
      await user.click(screen.getByTestId(`exchange-market-${tpl.countryCode.toUpperCase()}`));
      const link = await screen.findByTestId('exchange-specialist');
      linked.add(link.getAttribute('href') ?? '');
      // Deselect, so the next market starts from the same state rather than
      // from whatever the previous one left behind.
      await user.click(screen.getByTestId(`exchange-market-${tpl.countryCode.toUpperCase()}`));
    }

    const mounted = new Set(manifest.routes.map((r) => r.path).filter((p) => p !== HUB_PATH));
    // Two sets built from different sources, the rendered DOM and the route
    // table, so equality is a claim about both rather than a restatement of
    // one of them.
    expect([...linked].sort()).toEqual([...mounted].sort());
  });

  it('still lists the market screens when the catalogue request fails', async () => {
    apiGet.mockImplementation(async (path: string) => {
      if (path.includes('exchange-formats')) throw new Error('backend unreachable');
      return [];
    });
    renderHub();
    const strip = await screen.findByTestId('exchange-market-strip');
    for (const tpl of COUNTRY_TEMPLATES) {
      expect(
        within(strip).getByTestId(`exchange-market-${tpl.countryCode.toUpperCase()}`),
        `${tpl.id} disappeared because a network request failed`,
      ).toBeInTheDocument();
    }
  });

  it('takes the format capability from the payload rather than deciding it', async () => {
    const user = userEvent.setup();
    renderHub();
    await user.click(await screen.findByTestId('exchange-market-AT'));

    // Austria's own interchange, which the payload says we cannot write.
    await user.click(await screen.findByTestId('exchange-format-oenorm_a2063'));
    await user.click(screen.getByTestId('exchange-tab-export'));
    expect(screen.queryByTestId('exchange-export')).not.toBeInTheDocument();

    // GAEB, which the same payload says we can, in the same market.
    await user.click(screen.getByTestId('exchange-format-gaeb_xml'));
    expect(screen.getByTestId('exchange-export')).toBeInTheDocument();
  });

  it('lands on the format the backend picked for the market', async () => {
    // The mock answers for the market it was asked about, as the endpoint
    // does: a default is always a row that lists that country, so the card
    // the page highlights is one the page is showing. The market is chosen
    // by a click rather than left to the page, because before any click the
    // page infers one from the interface language, and this test does not
    // own that inference.
    apiGet.mockImplementation(async (path: string) => {
      if (path.includes('exchange-formats')) {
        return path.includes('country=AT') ? catalogue({ country: 'AT', default_format_id: 'gaeb_xml' }) : catalogue();
      }
      return [];
    });
    const user = userEvent.setup();
    renderHub();
    await user.click(await screen.findByTestId('exchange-market-AT'));
    const card = await screen.findByTestId('exchange-format-gaeb_xml');
    await waitFor(() => expect(card).toHaveAttribute('aria-pressed', 'true'));
    expect(screen.getByTestId('exchange-panel')).toHaveTextContent('GAEB DA XML 3.3');
  });

  it('falls back to a row on the page when the catalogue has no default for the market', async () => {
    // The backend answers null for a market it has no row for, rather than
    // borrowing another market's document. The page then has to land on a
    // row it is actually showing for that market, which is the spreadsheet
    // row that belongs to everybody. Landing on the first row of the whole
    // catalogue instead would highlight nothing, because that row is not on
    // the page for this market, and would open a German interchange format
    // for a market that has never seen one.
    const user = userEvent.setup();
    renderHub();
    // France has a screen of its own so it is on the strip, and the mock
    // catalogue lists no format for it, so only the universal rows show.
    await user.click(await screen.findByTestId('exchange-market-FR'));
    const card = await screen.findByTestId('exchange-format-excel');
    await waitFor(() => expect(card).toHaveAttribute('aria-pressed', 'true'));
    expect(screen.queryByTestId('exchange-format-gaeb_xml')).not.toBeInTheDocument();
    expect(screen.getByTestId('exchange-panel')).toHaveTextContent('Spreadsheet workbook');
  });

  it('keeps every format on the page after a market is chosen', async () => {
    // The market is a preselection and never a filter: the ordinary reason to
    // be on this screen is a file from a market that is not yours.
    const user = userEvent.setup();
    renderHub();
    await user.click(await screen.findByTestId('exchange-market-DE'));
    expect(screen.getByTestId('exchange-format-gaeb_xml')).toBeInTheDocument();
    expect(screen.getByTestId('exchange-format-excel')).toBeInTheDocument();
  });

  it('asks the backend about the market it is showing', async () => {
    const user = userEvent.setup();
    renderHub();
    await user.click(await screen.findByTestId('exchange-market-DE'));
    const asked = apiGet.mock.calls.map(([path]) => String(path)).filter((p) => p.includes('exchange-formats'));
    expect(asked.some((p) => p.includes('country=DE'))).toBe(true);
  });
});
