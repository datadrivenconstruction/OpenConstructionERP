// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for the shared <CommentThread /> used by project discussions
// (CollaborationModule, entityType="project").
//
// Focus: issue #279 - a comment's author must render as a readable name
// (full name / email) resolved from the users directory, not the raw
// truncated UUID it printed before. The thread must also survive a failed
// users fetch by falling back to the short id (never crash).

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

/* ── API mock — the component imports the shared http helpers directly. ── */

const apiMocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
vi.mock('@/shared/lib/api', () => apiMocks);

import { CommentThread } from '../CommentThread';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Helpers ──────────────────────────────────────────────────────────── */

const AUTHOR_ID = '11111111-2222-3333-4444-555555555555';

function makeComment(over: Record<string, unknown> = {}) {
  return {
    id: 'c-1',
    entity_type: 'project',
    entity_id: 'p-1',
    author_id: AUTHOR_ID,
    text: 'First post in the discussion.',
    comment_type: 'comment',
    parent_comment_id: null,
    edited_at: null,
    is_deleted: false,
    metadata: {},
    mentions: [],
    replies: [],
    created_at: '2026-05-28T10:00:00Z',
    updated_at: '2026-05-28T10:00:00Z',
    ...over,
  };
}

/** Route the two GETs the component issues: comments list + users list. */
function wireApi(opts: {
  comments: ReturnType<typeof makeComment>[];
  users?: unknown;
  usersReject?: boolean;
}) {
  apiMocks.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/collaboration/comments')) {
      return Promise.resolve({ items: opts.comments, total: opts.comments.length });
    }
    if (path.startsWith('/v1/users/')) {
      if (opts.usersReject) return Promise.reject(new Error('boom'));
      return Promise.resolve(opts.users ?? []);
    }
    return Promise.resolve({});
  });
}

function renderThread() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <CommentThread entityType="project" entityId="p-1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  // The author directory is read through users.list, which starts at manager.
  useAuthStore.setState({ userRole: 'manager' });
});

afterEach(() => {
  cleanup();
});

/* ── Tests ────────────────────────────────────────────────────────────── */

describe('<CommentThread /> author resolution (#279)', () => {
  it('renders the author full name resolved from the users directory', async () => {
    wireApi({
      comments: [makeComment()],
      users: [
        {
          id: AUTHOR_ID,
          email: 'jane@example.com',
          full_name: 'Jane Builder',
          role: 'manager',
          is_active: true,
        },
      ],
    });

    renderThread();

    await waitFor(() => {
      expect(screen.getByText('Jane Builder')).toBeTruthy();
    });
    // The raw truncated UUID must NOT be shown once the name resolves.
    expect(screen.queryByText(AUTHOR_ID.slice(0, 8))).toBeNull();
  });

  it('falls back to email when the user has no full name', async () => {
    wireApi({
      comments: [makeComment()],
      users: [
        {
          id: AUTHOR_ID,
          email: 'noname@example.com',
          full_name: '',
          role: 'member',
          is_active: true,
        },
      ],
    });

    renderThread();

    await waitFor(() => {
      expect(screen.getByText('noname@example.com')).toBeTruthy();
    });
  });

  it('falls back to the short id and never crashes when the users fetch fails', async () => {
    wireApi({ comments: [makeComment()], usersReject: true });

    renderThread();

    // The comment body still renders (thread did not crash) and the author
    // degrades to the short id rather than throwing.
    await waitFor(() => {
      expect(screen.getByText('First post in the discussion.')).toBeTruthy();
    });
    expect(screen.getByText(AUTHOR_ID.slice(0, 8))).toBeTruthy();
  });
});
