// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * #416 - opening a page executed every installed converter.
 *
 * `verify=true` makes the server start each installed converter binary with an
 * 8 s timeout to smoke-test it. This banner asked for that on mount, and it
 * mounts on /bim, /projects and /settings - so a converter that cannot start
 * produced a Windows loader error on arrival at a page, with no file to
 * convert. (Rate: the backend caches health 5 min and the client holds
 * staleTime 30 s, so it is once per five-minute window per converter, not per
 * render. It is still the first thing that happens on a cold cache.)
 *
 * The listing itself - installed, missing, size, upstream version - needs no
 * execution, so that is what the automatic fetch asks for now, and the check
 * runs when the user asks for it. Two things have to hold together: the panel
 * must not execute anything by itself, and it must not read as "all fine"
 * while it has not looked. Both are asserted below.
 *
 * Run:  npx vitest run src/features/bim/BIMConverterVerifyGate.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import type {
  BIMConverterInfo,
  BIMConvertersResponse,
  ConverterVersionCheck,
} from './api';

/* ── Mock the API module - the calls are the thing under test ─────────── */

const fetchBIMConverters = vi.fn();
const fetchConverterVersionCheck = vi.fn();
const verifyBIMConverter = vi.fn();
const installBIMConverter = vi.fn();

vi.mock('./api', () => ({
  fetchBIMConverters: (...args: unknown[]) => fetchBIMConverters(...args),
  fetchConverterVersionCheck: (...args: unknown[]) =>
    fetchConverterVersionCheck(...args),
  verifyBIMConverter: (...args: unknown[]) => verifyBIMConverter(...args),
  installBIMConverter: (...args: unknown[]) => installBIMConverter(...args),
}));

import { BIMConverterStatusBanner } from './BIMConverterStatusBanner';

/* ── Fixtures ─────────────────────────────────────────────────────────── */

function converter(id: string, name: string): BIMConverterInfo {
  return {
    id,
    name,
    description: '',
    engine: 'ddc',
    extensions: [`.${id}`],
    exe: `${id}.exe`,
    version: '1.0.0',
    size_mb: 120,
    installed: true,
    path: `C:/converters/${id}/${id}.exe`,
  };
}

/** Three converters on disk and no smoke-test verdict for any of them - what
 *  the server returns when nobody asked it to run anything. */
const INSTALLED_UNCHECKED: BIMConvertersResponse = {
  converters: [
    converter('rvt', 'Revit converter'),
    converter('ifc', 'IFC converter'),
    converter('dwg', 'DWG converter'),
  ],
  installed_count: 3,
  total_count: 3,
};

/** The same three, checked, with the DWG one refusing to start - the reporter's
 *  machine. */
const DWG_BROKEN: BIMConvertersResponse = {
  converters: INSTALLED_UNCHECKED.converters.map((c) =>
    c.id === 'dwg'
      ? {
          ...c,
          health: 'failed' as const,
          health_message:
            'dwg2excel.exe cannot start because one of the libraries beside it is built for a different processor architecture.',
          suggested_actions: ['reinstall_converter' as const],
        }
      : { ...c, health: 'ok' as const },
  ),
  installed_count: 3,
  healthy_count: 2,
  total_count: 3,
};

/** An update waiting upstream. Independent of the smoke test - the backend
 *  compares blob SHAs and never starts anything - so it can land on top of
 *  the unchecked listing above, and on a machine that has not updated in a
 *  while it usually does. */
const DWG_OUTDATED: ConverterVersionCheck = {
  converters: [
    {
      id: 'dwg',
      name: 'DWG converter',
      exe: 'dwg2excel.exe',
      installed: true,
      installed_path: 'C:/converters/dwg/cli/dwg2excel.exe',
      installed_size: 120,
      installed_sha: 'def5678',
      latest_size: 121,
      latest_sha: 'abc1234',
      is_outdated: true,
      download_url: null,
      html_url: null,
    },
  ],
  any_outdated: true,
  network_ok: true,
  checked_at: '2026-08-04T09:00:00Z',
  ttl_seconds: 21600,
};

/* ── Helpers ──────────────────────────────────────────────────────────── */

function renderBanner() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BIMConverterStatusBanner />
    </QueryClientProvider>,
  );
}

/** The `verify` flag of every converter listing the panel asked for. */
function verifyFlags(): unknown[] {
  return fetchBIMConverters.mock.calls.map(
    (call) => (call[0] as { verify?: boolean } | undefined)?.verify,
  );
}

beforeEach(() => {
  localStorage.clear();
  fetchBIMConverters.mockReset();
  fetchConverterVersionCheck.mockReset();
  verifyBIMConverter.mockReset();
  installBIMConverter.mockReset();
  fetchBIMConverters.mockResolvedValue(INSTALLED_UNCHECKED);
  fetchConverterVersionCheck.mockResolvedValue(null);
});

/* ── Tests ────────────────────────────────────────────────────────────── */

describe('The converter panel does not run the converters to render itself (#416)', () => {
  it('lists them on mount without asking the server to start any', async () => {
    renderBanner();

    await screen.findByText('BIM converters');

    // Every fetch the panel made on its own must be a listing. One
    // `verify: true` here is one execution of every installed binary,
    // triggered by nothing but a page opening.
    expect(verifyFlags().length).toBeGreaterThan(0);
    expect(verifyFlags().every((v) => v === false)).toBe(true);
  });

  it('runs the check when the user presses the button, and not before', async () => {
    renderBanner();

    const check = await screen.findByTestId('bim-converters-check');
    expect(verifyFlags()).toEqual([false]);

    fireEvent.click(check);

    await waitFor(() => {
      expect(verifyFlags()).toContain(true);
    });
  });
});

describe('An unchecked panel says so rather than guessing (#416)', () => {
  it('counts what it knows - installed - instead of reporting nothing works', async () => {
    renderBanner();

    // With no verdicts, "working" is not a number the panel has. Reusing the
    // verified wording here printed "0/3 up to date" and the install nag on a
    // machine where all four converters are present and fine.
    expect(await screen.findByText('3/3 installed · not checked')).toBeInTheDocument();
    expect(screen.queryByText('3/3 up to date')).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        'Without these, drag-and-drop of native CAD/BIM files will fail. One-time install from GitHub.',
      ),
    ).not.toBeInTheDocument();
    // ...and it offers the check by name, so the user knows the panel is
    // waiting for them rather than reporting a verdict.
    expect(screen.getByText('Check now')).toBeInTheDocument();
  });

  it('keeps the collapsed badge when everything is installed and unchecked', async () => {
    // A user who collapsed the panel to the badge sees it because nothing
    // needs their attention. Gating that on the smoke-test result alone put
    // the full amber install panel back on all three pages the moment the
    // panel stopped verifying on mount.
    localStorage.setItem('oe_bim_converter_panel_collapsed', '1');

    renderBanner();

    expect(await screen.findByTestId('bim-converters-mini-icon')).toHaveTextContent(
      '3/3',
    );
  });

  it('does not ask an unchecked user to install what they already have, update or not', async () => {
    // An update available is not a converter missing, but it is enough to
    // keep the panel out of its "nothing to report" state - so the wording
    // and the collapsed badge cannot hang off one flag. Off one flag the
    // header read "3/3 installed" with "One-time install from GitHub"
    // directly underneath it.
    fetchConverterVersionCheck.mockResolvedValue(DWG_OUTDATED);

    renderBanner();

    expect(await screen.findByText('3/3 installed · not checked')).toBeInTheDocument();
    expect(
      screen.queryByText(
        'Without these, drag-and-drop of native CAD/BIM files will fail. One-time install from GitHub.',
      ),
    ).not.toBeInTheDocument();
    // The update still has to reach the user - suppressing the install nag
    // must not suppress this too. By testid and `toHaveTextContent`, because
    // the sentence is a <span> plus two sibling text nodes and `getByText`
    // matches on an element's own direct text.
    expect(screen.getByTestId('bim-converters-update-banner')).toHaveTextContent(
      'A new version is available - we recommend updating',
    );
  });

  it('still reports a converter that cannot start, once it has been checked', async () => {
    // The guard on the change above: not verifying by default must not turn a
    // broken converter into a silent success. This passes before and after -
    // it is here so a future "just drop the verified branch" cannot go
    // unnoticed.
    fetchBIMConverters.mockResolvedValue(DWG_BROKEN);

    renderBanner();

    expect(await screen.findByText('Broken')).toBeInTheDocument();
    expect(screen.getByText('1 broken · 2/3 working')).toBeInTheDocument();
  });
});
