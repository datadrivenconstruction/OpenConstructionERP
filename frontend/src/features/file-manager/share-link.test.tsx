// @ts-nocheck
/**
 * Unit tests for the password-protected share link feature.
 *
 * Two pieces under test:
 *   1. ``ShareLinkModal`` — owner-facing modal that mints links,
 *      copies the URL, and revokes existing links.
 *   2. ``SharePage`` — public landing page mounted at ``/share/:token``.
 *      Handles the loading / not-found / expired / password-prompt /
 *      auto-resolve flows.
 *
 * Uses MSW to intercept the backend share-link endpoints (relative URLs
 * under ``/api/v1/documents/...``) so the components exercise the real
 * fetch pipeline through ``src/shared/lib/api.ts``.
 */

import { describe, it, expect, beforeAll, afterEach, afterAll, vi } from 'vitest';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
// The global test setup mocks `useParams` to always return `{}`, which would
// strand SharePage on the "no token" path before any fetch fires. Restore the
// real react-router-dom surface inside this test file so the MemoryRouter +
// Route harness can populate `:token` from the URL.
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return actual;
});

import { ShareLinkModal } from './components/ShareLinkModal';
import { SharePage } from './SharePage';
import type { FileRow, ShareLinkResponse } from './types';

/* ── Fixtures ──────────────────────────────────────────────────────── */

const MOCK_ROW: FileRow = {
  id: 'doc-001',
  kind: 'document',
  name: 'spec.pdf',
  project_id: 'proj-001',
  size_bytes: 1024,
  mime_type: 'application/pdf',
  extension: '.pdf',
  modified_at: '2026-05-01T00:00:00Z',
  physical_path: '/storage/spec.pdf',
  relative_path: 'spec.pdf',
  storage_backend: 'local',
  download_url: '/api/v1/documents/doc-001/download/',
  preview_url: null,
  thumbnail_url: null,
  discipline: null,
  category: 'specification',
  extra: {},
};

const MOCK_LINK: ShareLinkResponse = {
  id: 'link-001',
  token: 'abcdefghijklmnop1234567890abcdef',
  url: '/share/abcdefghijklmnop1234567890abcdef',
  document_id: 'doc-001',
  requires_password: true,
  expires_at: '2026-06-01T00:00:00Z',
  created_at: '2026-05-12T00:00:00Z',
  download_count: 0,
  revoked: false,
};

/* ── MSW server ────────────────────────────────────────────────────── */

let existingLinks: ShareLinkResponse[] = [];
let createNextResponse: ShareLinkResponse = MOCK_LINK;
let publicInfoResponse: { status: number; body: unknown } = {
  status: 200,
  body: { filename: 'spec.pdf', requires_password: true, expired: false },
};
let accessResponse: { status: number; body: unknown } = {
  status: 200,
  body: {
    download_url: '/api/v1/documents/share-links/abcdefghijklmnop1234567890abcdef/file/',
    filename: 'spec.pdf',
  },
};

// MSW v2 in Node + jsdom resolves relative fetch URLs against the jsdom origin
// (http://localhost/), so handlers must match absolute URLs. Wildcard patterns
// (`*/api/v1/...`) match regardless of the resolved origin while still keeping
// :param tokens working — the simpler relative-path form silently no-ops.
//
// The `share-links/:token/` route is order-sensitive: registering it BEFORE the
// owner list / create routes prevents msw from matching the literal segment
// "share-links" as the `:id` placeholder, which would otherwise swallow the
// public probe request and return the owner-list response.
const server = setupServer(
  http.get('*/api/v1/documents/share-links/:token/', () =>
    HttpResponse.json(publicInfoResponse.body as object, {
      status: publicInfoResponse.status,
    }),
  ),
  http.post('*/api/v1/documents/share-links/:token/access/', () =>
    HttpResponse.json(accessResponse.body as object, {
      status: accessResponse.status,
    }),
  ),
  http.get('*/api/v1/documents/:id/share-links/', () =>
    HttpResponse.json(existingLinks),
  ),
  http.post('*/api/v1/documents/:id/share-links/', () =>
    HttpResponse.json(createNextResponse, { status: 201 }),
  ),
  http.delete('*/api/v1/documents/:id/share-links/:linkId/', () => {
    existingLinks = [];
    return new HttpResponse(null, { status: 204 });
  }),
);

// MSW's interceptor replaces `globalThis.fetch`; the global test setup
// can't drop the realm-mismatched AbortSignal after that swap, so we wrap
// the post-MSW fetch here. Without this, our production `request()` helper
// fails undici's `RequestInit.signal instanceof AbortSignal` check (the
// jsdom-provided AbortController is from a different realm than Node's
// native one).
beforeAll(() => {
  server.listen({ onUnhandledRequest: 'warn' });
  const mswFetch = globalThis.fetch;
  globalThis.fetch = ((input, init) => {
    if (init && 'signal' in init) {
      const { signal: _signal, ...rest } = init;
      return mswFetch(input, rest);
    }
    return mswFetch(input, init);
  }) as typeof fetch;
});
afterEach(() => {
  server.resetHandlers();
  existingLinks = [];
  createNextResponse = MOCK_LINK;
  publicInfoResponse = {
    status: 200,
    body: { filename: 'spec.pdf', requires_password: true, expired: false },
  };
  accessResponse = {
    status: 200,
    body: {
      download_url:
        '/api/v1/documents/share-links/abcdefghijklmnop1234567890abcdef/file/',
      filename: 'spec.pdf',
    },
  };
  cleanup();
});
afterAll(() => server.close());

/* ── Helpers ───────────────────────────────────────────────────────── */

function renderModal(open = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ShareLinkModal open={open} row={MOCK_ROW} onClose={() => {}} />
    </QueryClientProvider>,
  );
}

function renderSharePage(token = 'abcdefghijklmnop1234567890abcdef') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/share/${token}`]}>
        <Routes>
          <Route path="/share/:token" element={<SharePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/* ── ShareLinkModal ────────────────────────────────────────────────── */

describe('ShareLinkModal', () => {
  it('renders the password input and expiry buttons when open', async () => {
    renderModal();
    expect(
      await screen.findByLabelText(/password.*optional/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /1 day/i })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /7 days/i })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /30 days/i })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /never/i })).toBeInTheDocument();
  });

  it('renders nothing when closed', () => {
    const { container } = renderModal(false);
    expect(container.innerHTML).toBe('');
  });

  it('creates a link and renders the URL block', async () => {
    renderModal();
    const passwordInput = await screen.findByLabelText(/password.*optional/i);
    fireEvent.change(passwordInput, { target: { value: 'testpw' } });
    const createBtn = screen.getByRole('button', { name: /create link/i });
    fireEvent.click(createBtn);

    const urlBlock = await screen.findByTestId('share-link-url');
    expect(urlBlock.textContent).toContain(MOCK_LINK.token);
  });

  it('lists existing links and shows a revoke button per row', async () => {
    existingLinks = [MOCK_LINK];
    renderModal();
    const items = await screen.findAllByTestId('existing-share-link');
    expect(items).toHaveLength(1);
    expect(items[0].textContent).toContain(MOCK_LINK.token);
    // Revoke icon button must be present (aria-labelled "Revoke")
    expect(screen.getByRole('button', { name: /revoke/i })).toBeInTheDocument();
  });
});

/* ── SharePage ─────────────────────────────────────────────────────── */

describe('SharePage', () => {
  it('shows a generic protected-file label, no filename, for a protected link', async () => {
    publicInfoResponse = {
      status: 200,
      body: { filename: null, requires_password: true, expired: false },
    };
    renderSharePage();
    expect(await screen.findByTestId('share-password-input')).toBeInTheDocument();
    expect(screen.queryByTestId('share-filename')).toBeNull();
    expect(screen.getByText('Protected file')).toBeInTheDocument();
    expect(screen.getByTestId('share-password-input')).toBeInTheDocument();
    expect(screen.getByTestId('share-unlock-button')).toBeInTheDocument();
  });

  it('shows the "not found" panel when the probe 404s', async () => {
    publicInfoResponse = { status: 404, body: { detail: 'Share link not found' } };
    renderSharePage();
    expect(await screen.findByTestId('share-not-found')).toBeInTheDocument();
  });

  it('shows the "expired" panel when the probe reports expired=true', async () => {
    publicInfoResponse = {
      status: 200,
      body: { filename: 'spec.pdf', requires_password: false, expired: true },
    };
    renderSharePage();
    expect(await screen.findByTestId('share-expired')).toBeInTheDocument();
  });

  it('surfaces a "wrong password" error when access returns 401', async () => {
    publicInfoResponse = {
      status: 200,
      body: { filename: 'spec.pdf', requires_password: true, expired: false },
    };
    accessResponse = { status: 401, body: { detail: 'Invalid password' } };
    renderSharePage();

    const input = await screen.findByTestId('share-password-input');
    fireEvent.change(input, { target: { value: 'wrong' } });
    fireEvent.click(screen.getByTestId('share-unlock-button'));

    const err = await screen.findByTestId('share-error');
    expect(err.textContent?.toLowerCase()).toContain('wrong password');
  });

  it('renders the download link after a successful unlock', async () => {
    publicInfoResponse = {
      status: 200,
      body: { filename: 'spec.pdf', requires_password: true, expired: false },
    };
    accessResponse = {
      status: 200,
      body: {
        download_url:
          '/api/v1/documents/share-links/abcdefghijklmnop1234567890abcdef/file/',
        filename: 'spec.pdf',
      },
    };
    renderSharePage();
    const input = await screen.findByTestId('share-password-input');
    fireEvent.change(input, { target: { value: 'right' } });
    fireEvent.click(screen.getByTestId('share-unlock-button'));

    const dl = await screen.findByTestId('share-download-link');
    expect(dl.getAttribute('href')).toContain('/file/');
  });

  it('auto-resolves an open (no-password) link to the download link', async () => {
    publicInfoResponse = {
      status: 200,
      body: { filename: 'spec.pdf', requires_password: false, expired: false },
    };
    accessResponse = {
      status: 200,
      body: {
        download_url:
          '/api/v1/documents/share-links/abcdefghijklmnop1234567890abcdef/file/',
        filename: 'spec.pdf',
      },
    };
    renderSharePage();
    const dl = await screen.findByTestId('share-download-link');
    expect(dl.getAttribute('href')).toContain('/file/');
  });
});
