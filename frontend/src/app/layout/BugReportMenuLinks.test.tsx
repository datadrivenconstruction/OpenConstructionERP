// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Every channel in the bug menu has to leave the app, on both builds.
 *
 * Reported against 18.5.0 as "none of the links work". Two things in this menu
 * made that true without any link being broken on its own:
 *
 *  - the e-mail channel assigned `window.location.href = 'mailto:...'`, which
 *    the desktop webview does not hand to a mail client, so it did nothing;
 *  - while the recent errors were only network blips, the whole channel list
 *    sat under `opacity-40 pointer-events-none`. The desktop app logs a few of
 *    those on every start while its server comes up, so the menu read as a
 *    column of dead links until somebody found "report anyway".
 *
 * `openLink` is the one place that knows how to open a link on each build (see
 * desktop.test.ts), so here it is observed rather than exercised.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const openLink = vi.hoisted(() => vi.fn());
const networkOnly = vi.hoisted(() => ({ value: false }));

vi.mock('@/shared/lib/desktop', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/desktop')>();
  return { ...actual, openLink };
});

vi.mock('@/shared/lib/errorLogger', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/errorLogger')>();
  return { ...actual, isLastErrorNetworkOnly: () => networkOnly.value };
});

import { BugReportMenu } from './Header';

const REAL_DESCRIPTION =
  'I clicked Install on the UK JCT pack on the modules page and nothing happened.';

function openMenu() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BugReportMenu />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByLabelText('Report a bug or send feedback'));
  fireEvent.change(screen.getByLabelText(/What happened/), { target: { value: REAL_DESCRIPTION } });
}

const channel = (label: string) => screen.getByText(label).closest('button') as HTMLButtonElement;

describe('bug menu channels', () => {
  beforeEach(() => {
    openLink.mockClear();
    networkOnly.value = false;
  });

  it('sends the e-mail channel through openLink, not a webview navigation', () => {
    openMenu();
    fireEvent.click(channel('Email the team'));

    expect(openLink).toHaveBeenCalledTimes(1);
    const url = openLink.mock.calls[0]![0] as string;
    expect(url.startsWith('mailto:info@datadrivenconstruction.io?subject=')).toBe(true);
    expect(decodeURIComponent(url)).toContain(REAL_DESCRIPTION);
  });

  it('opens the web form through openLink', () => {
    openMenu();
    fireEvent.click(channel('Web feedback form'));

    expect(openLink).toHaveBeenCalledWith(
      expect.stringMatching(/^https:\/\/openconstructionerp\.com\/contact\.html\?report=true/),
    );
  });

  it('keeps every channel usable while the network banner is showing', () => {
    networkOnly.value = true;
    openMenu();

    // The banner is still there to explain, it just no longer locks the menu.
    expect(screen.getByRole('alert')).toBeTruthy();
    const list = channel('Web feedback form').parentElement as HTMLElement;
    expect(list.className).not.toMatch(/pointer-events-none|opacity-40/);

    fireEvent.click(channel('Web feedback form'));
    fireEvent.click(screen.getByLabelText('Report a bug or send feedback'));
    fireEvent.change(screen.getByLabelText(/What happened/), { target: { value: REAL_DESCRIPTION } });
    fireEvent.click(channel('Report a bug (with logs)'));

    expect(openLink).toHaveBeenCalledTimes(2);
  });
});
