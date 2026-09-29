// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The update notice in the collapsed, icon-only sidebar. The card is too wide
// for the icon strip, and hiding it there meant a reader who keeps the sidebar
// collapsed never heard about a release. The badge names the version in its
// tooltip, opens About, and follows the same dismissal as the card.
//
// Which of the two the sidebar renders is pinned in Sidebar.learn.test.tsx.
//
// Run:  npx vitest run src/shared/ui/__tests__/updateBadge.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { UpdateBadge } from '../UpdateChecker';

const DISMISS_KEY = 'oe_update_dismissed_version';

function versionCheck(over: Record<string, unknown> = {}) {
  return {
    current_version: '18.1.0',
    latest_version: '18.2.0',
    update_available: true,
    release_url: '',
    release_notes: '',
    published_at: '',
    assets: [],
    self_upgrade_supported: false,
    upgrade_command: '',
    ...over,
  };
}

function answering(body: unknown): ReturnType<typeof vi.fn> {
  return vi.fn(async () => ({ ok: true, status: 200, json: async () => body }));
}

function renderBadge() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<UpdateBadge />} />
          <Route path="/about" element={<p>About page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Past the answer, so "nothing shown" is not read before the answer lands. */
async function settled(fetchMock: ReturnType<typeof vi.fn>) {
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
  await new Promise((resolve) => setTimeout(resolve, 50));
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('UpdateBadge', () => {
  it('names the new version and opens About', async () => {
    vi.stubGlobal('fetch', answering(versionCheck()));
    renderBadge();

    const badge = await screen.findByRole('button', { name: 'Version 18.2.0 is available.' });
    expect(badge.getAttribute('title')).toBe('Version 18.2.0 is available.');

    fireEvent.click(badge);
    expect(await screen.findByText('About page')).toBeTruthy();
  });

  it('shows nothing when this is the latest version', async () => {
    const fetchMock = answering(versionCheck({ latest_version: '18.1.0', update_available: false }));
    vi.stubGlobal('fetch', fetchMock);
    renderBadge();

    await settled(fetchMock);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('follows the dismissal the sidebar card set for that version', async () => {
    localStorage.setItem(DISMISS_KEY, '18.2.0');
    const fetchMock = answering(versionCheck());
    vi.stubGlobal('fetch', fetchMock);
    renderBadge();

    await settled(fetchMock);
    expect(screen.queryByRole('button')).toBeNull();
  });
});
