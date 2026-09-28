// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// About's "Check for updates" button. It asks nothing until it is pressed,
// asks past the server's cache when it is, and says which of its four answers
// it got, because a click followed by silence reads as a broken button.
//
// Run:  npx vitest run src/shared/ui/__tests__/checkForUpdatesButton.test.tsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CheckForUpdatesButton } from '../UpdateChecker';

function versionCheck(over: Record<string, unknown> = {}) {
  return {
    current_version: '18.1.0',
    latest_version: '18.1.0',
    update_available: false,
    release_url: '',
    release_notes: '',
    published_at: '',
    assets: [],
    self_upgrade_supported: false,
    upgrade_command: '',
    ...over,
  };
}

function answering(body: unknown, status = 200): ReturnType<typeof vi.fn> {
  return vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }));
}

function renderButton() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CheckForUpdatesButton />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('CheckForUpdatesButton', () => {
  it('asks nothing until pressed, then asks past the cache', async () => {
    const fetchMock = answering(versionCheck());
    vi.stubGlobal('fetch', fetchMock);

    renderButton();
    expect(fetchMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /check for updates/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe('/api/system/version-check?force=true');
    expect(await screen.findByText('You have the latest version.')).toBeTruthy();
  });

  it('names the newer version it found', async () => {
    vi.stubGlobal('fetch', answering(versionCheck({ latest_version: '18.2.0', update_available: true })));
    renderButton();
    fireEvent.click(screen.getByRole('button', { name: /check for updates/i }));
    expect(await screen.findByText('Version 18.2.0 is available.')).toBeTruthy();
  });

  it('says so when the server could not be asked', async () => {
    vi.stubGlobal('fetch', answering({}, 503));
    renderButton();
    fireEvent.click(screen.getByRole('button', { name: /check for updates/i }));
    expect(await screen.findByText(/Could not check for updates/)).toBeTruthy();
  });

  it('says so when update checks are turned off', async () => {
    vi.stubGlobal('fetch', answering(versionCheck({ check_disabled: true })));
    renderButton();
    fireEvent.click(screen.getByRole('button', { name: /check for updates/i }));
    expect(await screen.findByText('Update checks are turned off on this computer.')).toBeTruthy();
  });
});
