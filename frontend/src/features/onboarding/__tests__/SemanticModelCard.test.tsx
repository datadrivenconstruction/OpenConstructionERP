// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The card has one job beyond looking right: never let an optional extra look
// like a required one. So the tests here are about what the reader is told in
// each of the five situations, and about the card staying out of the way.
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { SemanticModelCard } from '../SemanticModelCard';

vi.mock('@/features/ai-estimator/api', () => ({
  aiEstimatorApi: {
    embeddingModelStatus: vi.fn(),
    installEmbeddingModel: vi.fn(() => Promise.resolve({})),
  },
}));

function statusOf(overrides = {}) {
  return {
    state: 'not_requested',
    enabled: true,
    model: 'intfloat/multilingual-e5-small',
    installed: false,
    percent: 0,
    files_done: 0,
    files_total: 0,
    downloaded_bytes: 0,
    error: '',
    library_installed: true,
    env_var: 'OE_DOWNLOAD_EMBEDDING_MODEL',
    locked: false,
    message: '',
    ...overrides,
  };
}

function renderCard(props = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const defaults = {
    enabled: true,
    onToggle: () => undefined,
    fetchStatus: () => Promise.resolve(statusOf()),
  };
  return render(
    <QueryClientProvider client={client}>
      <SemanticModelCard {...defaults} {...props} />
    </QueryClientProvider>,
  );
}

describe('SemanticModelCard', () => {
  it('offers the option pre-ticked and says plainly that it is optional', async () => {
    renderCard({ enabled: true });

    const toggle = await screen.findByRole('switch');
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    // "Optional" is not decoration here: it is the promise that unticking it
    // costs the user nothing.
    expect(screen.getByText(/Optional/i)).toBeTruthy();
    expect(screen.getByText(/Search works without it/i)).toBeTruthy();
  });

  it('states the size and purpose before anything is downloaded', async () => {
    renderCard({ enabled: false });

    await screen.findByRole('switch');
    expect(screen.getByText(/470 MB/)).toBeTruthy();
    expect(screen.getByText(/only when you switch this on/i)).toBeTruthy();
  });

  it('hides the toggle where an operator has switched the download off', async () => {
    // The production unit sets OE_DOWNLOAD_EMBEDDING_MODEL=0, which refuses a
    // click too. Leaving the switch on screen there would take the tick and
    // silently drop it, which is worse than not offering it.
    renderCard({
      enabled: true,
      fetchStatus: () => Promise.resolve(statusOf({ locked: true })),
    });

    expect(await screen.findByText(/Turned off for this installation/i)).toBeTruthy();
    expect(screen.queryByRole('switch')).toBeNull();
  });

  it('reports the toggle to its owner without doing anything itself', async () => {
    const onToggle = vi.fn();
    renderCard({ enabled: true, onToggle });

    fireEvent.click(await screen.findByRole('switch'));

    expect(onToggle).toHaveBeenCalledWith(false);
  });

  it('shows live progress in files rather than a percentage it cannot justify', async () => {
    renderCard({
      fetchStatus: () =>
        Promise.resolve(
          statusOf({ state: 'downloading', files_done: 3, files_total: 8, percent: 38 }),
        ),
    });

    await waitFor(() => expect(screen.getByText(/Downloading 3 of 8 files/i)).toBeTruthy());
    // No switch while it is arriving: there is nothing left to decide.
    expect(screen.queryByRole('switch')).toBeNull();
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('38');
  });

  it('says the model is installed once it is', async () => {
    renderCard({ fetchStatus: () => Promise.resolve(statusOf({ state: 'ready', installed: true })) });

    await waitFor(() => expect(screen.getByText(/Installed/i)).toBeTruthy());
  });

  it('tells the reader a failure cost them nothing, and offers a retry', async () => {
    renderCard({
      fetchStatus: () =>
        Promise.resolve(statusOf({ state: 'failed', error: 'connection reset' })),
    });

    await waitFor(() => expect(screen.getByText(/Everything else keeps working/i)).toBeTruthy());
    expect(screen.getByText(/Try again/i)).toBeTruthy();
  });

  it('does not offer a switch when this installation has no semantic library', async () => {
    // The distinction the five states exist for: this is not "off", and a
    // toggle here would promise something no amount of clicking can deliver.
    renderCard({
      fetchStatus: () => Promise.resolve(statusOf({ state: 'library_missing', library_installed: false })),
    });

    await waitFor(() => expect(screen.getByText(/Not available here/i)).toBeTruthy());
    expect(screen.queryByRole('switch')).toBeNull();
    expect(screen.getByText(/Everything else works without it/i)).toBeTruthy();
  });

  it('still renders when the status endpoint is unreachable', async () => {
    // An older backend has no such endpoint. The wizard must not stall on it.
    renderCard({ fetchStatus: () => Promise.reject(new Error('404')) });

    expect(await screen.findByRole('switch')).toBeTruthy();
    expect(screen.getByText(/Semantic search model/i)).toBeTruthy();
  });
});
