// @ts-nocheck
/**
 * MSW-based integration tests for React Query hooks.
 *
 * Uses msw@2 `setupServer` + `http` handlers to intercept fetch calls
 * made through the shared `apiGet` / `apiPost` helpers, and verifies
 * that data, loading, and error states propagate correctly when wrapped
 * in `@tanstack/react-query`.
 *
 * URL pattern: apiGet('/v1/projects/') → fetch('/api/v1/projects/')
 * (BASE_URL = '/api' is prepended in shared/lib/api.ts)
 */

import { describe, it, expect, beforeAll, afterEach, afterAll } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import React from 'react';

import { projectsApi, type Project } from '@/features/projects/api';
import { boqApi, type BOQ, type BOQWithPositions, type Position } from '@/features/boq/api';
import { ApiError } from '@/shared/lib/api';

/* ── Fixture data ──────────────────────────────────────────────────────── */

const MOCK_PROJECTS: Project[] = [
  {
    id: 'proj-001',
    name: 'Office Tower Berlin',
    description: 'High-rise office building',
    region: 'DE',
    classification_standard: 'DIN276',
    currency: 'EUR',
    locale: 'de-DE',
    validation_rule_sets: ['din276', 'gaeb'],
    status: 'active',
    owner_id: 'user-001',
    metadata: {},
    created_at: '2024-01-15T10:00:00Z',
    updated_at: '2024-01-15T10:00:00Z',
  },
  {
    id: 'proj-002',
    name: 'Residential Complex Hamburg',
    description: 'Multi-family residential',
    region: 'DE',
    classification_standard: 'DIN276',
    currency: 'EUR',
    locale: 'de-DE',
    validation_rule_sets: ['din276'],
    status: 'active',
    owner_id: 'user-001',
    metadata: {},
    created_at: '2024-02-20T09:00:00Z',
    updated_at: '2024-02-20T09:00:00Z',
  },
];

const MOCK_PROJECT_SINGLE: Project = MOCK_PROJECTS[0];

const MOCK_BOQS: BOQ[] = [
  {
    id: 'boq-001',
    project_id: 'proj-001',
    name: 'Main Estimate',
    description: 'Primary BOQ for office tower',
    status: 'draft',
    created_at: '2024-01-16T10:00:00Z',
    updated_at: '2024-01-16T10:00:00Z',
  },
  {
    id: 'boq-002',
    project_id: 'proj-001',
    name: 'Provisional Estimate',
    description: 'Early-stage cost plan',
    status: 'draft',
    created_at: '2024-01-17T10:00:00Z',
    updated_at: '2024-01-17T10:00:00Z',
  },
];

const MOCK_POSITION: Position = {
  id: 'pos-001',
  boq_id: 'boq-001',
  parent_id: null,
  ordinal: '01.001',
  description: 'Reinforced concrete wall C30/37',
  unit: 'm3',
  quantity: 120.5,
  unit_rate: 450.0,
  total: 54225.0,
  classification: { din276: '330' },
  source: 'manual',
  confidence: null,
  validation_status: 'passed',
  sort_order: 1,
  metadata: { notes: 'External walls only' },
};

const MOCK_BOQ_WITH_POSITIONS: BOQWithPositions = {
  ...MOCK_BOQS[0],
  positions: [MOCK_POSITION],
  grand_total: 54225.0,
};

/* ── MSW server setup ──────────────────────────────────────────────────── */

const handlers = [
  // GET /api/v1/projects/  →  returns project list
  http.get('/api/v1/projects/', () => {
    return HttpResponse.json(MOCK_PROJECTS);
  }),

  // GET /api/v1/projects/:id  →  returns single project
  http.get('/api/v1/projects/:id', ({ params }) => {
    const found = MOCK_PROJECTS.find((p) => p.id === params.id);
    if (!found) {
      return HttpResponse.json({ detail: 'Not found' }, { status: 404 });
    }
    return HttpResponse.json(found);
  }),

  // GET /api/v1/boq/boqs/?project_id=...  →  returns BOQ list
  http.get('/api/v1/boq/boqs/', ({ request }) => {
    const url = new URL(request.url);
    const projectId = url.searchParams.get('project_id');
    const results = projectId
      ? MOCK_BOQS.filter((b) => b.project_id === projectId)
      : MOCK_BOQS;
    return HttpResponse.json(results);
  }),

  // GET /api/v1/boq/boqs/:id  →  returns single BOQ with positions
  http.get('/api/v1/boq/boqs/:id', ({ params }) => {
    if (params.id === MOCK_BOQ_WITH_POSITIONS.id) {
      return HttpResponse.json(MOCK_BOQ_WITH_POSITIONS);
    }
    return HttpResponse.json({ detail: 'Not found' }, { status: 404 });
  }),
];

const server = setupServer(...handlers);

beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

/* ── React Query test wrapper ──────────────────────────────────────────── */

/**
 * Creates a fresh QueryClient for each test to prevent cache contamination.
 * Retries are disabled so error tests resolve immediately.
 */
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        // Suppress React Query's console.error noise in tests
        gcTime: 0,
      },
    },
  });
}

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

/* ═══════════════════════════════════════════════════════════════════════
   Projects API tests
═══════════════════════════════════════════════════════════════════════ */

describe('Projects API — MSW integration', () => {
  it('useQuery: fetches project list and returns correct data', async () => {
    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () => useQuery({ queryKey: ['projects'], queryFn: () => projectsApi.list() }),
      { wrapper },
    );

    // Initial state: loading
    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();

    // Wait for data
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toHaveLength(2);
    expect(result.current.data![0].id).toBe('proj-001');
    expect(result.current.data![0].name).toBe('Office Tower Berlin');
    expect(result.current.data![1].id).toBe('proj-002');
    expect(result.current.data![1].region).toBe('DE');
  });

  it('useQuery: fetches a single project by id', async () => {
    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ['projects', 'proj-001'],
          queryFn: () => projectsApi.get('proj-001'),
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const project = result.current.data!;
    expect(project.id).toBe('proj-001');
    expect(project.classification_standard).toBe('DIN276');
    expect(project.currency).toBe('EUR');
    expect(project.validation_rule_sets).toContain('din276');
  });

  it('useQuery: returns error state on 500 response from projects list', async () => {
    // Override the projects handler to return a 500 for this test only
    server.use(
      http.get('/api/v1/projects/', () => {
        return HttpResponse.json(
          { detail: 'Internal server error' },
          { status: 500 },
        );
      }),
    );

    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () => useQuery({ queryKey: ['projects'], queryFn: () => projectsApi.list() }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeInstanceOf(ApiError);
    const apiErr = result.current.error as ApiError;
    expect(apiErr.status).toBe(500);
    expect(result.current.data).toBeUndefined();
  });

  it('useQuery: returns error state on 404 for unknown project id', async () => {
    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ['projects', 'nonexistent'],
          queryFn: () => projectsApi.get('nonexistent'),
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));

    const apiErr = result.current.error as ApiError;
    expect(apiErr.status).toBe(404);
  });

  it('useQuery: passes through project fields accurately (shape validation)', async () => {
    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () => useQuery({ queryKey: ['projects'], queryFn: () => projectsApi.list() }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const first = result.current.data![0];
    // Validate all fields from the Project interface are present
    expect(first).toMatchObject({
      id: expect.any(String),
      name: expect.any(String),
      description: expect.any(String),
      region: expect.any(String),
      classification_standard: expect.any(String),
      currency: expect.any(String),
      locale: expect.any(String),
      validation_rule_sets: expect.any(Array),
      status: expect.any(String),
      owner_id: expect.any(String),
      metadata: expect.any(Object),
      created_at: expect.any(String),
      updated_at: expect.any(String),
    });
  });

  it('useQuery: handles network failure (fetch throws)', async () => {
    server.use(
      http.get('/api/v1/projects/', () => {
        return HttpResponse.error();
      }),
    );

    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () => useQuery({ queryKey: ['projects'], queryFn: () => projectsApi.list() }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Error);
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   BOQ API tests
═══════════════════════════════════════════════════════════════════════ */

describe('BOQ API — MSW integration', () => {
  it('useQuery: fetches BOQ list for a project and returns correct data', async () => {
    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ['boqs', 'proj-001'],
          queryFn: () => boqApi.list('proj-001'),
        }),
      { wrapper },
    );

    // Loading state before fetch completes
    expect(result.current.isLoading).toBe(true);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toHaveLength(2);
    expect(result.current.data![0].id).toBe('boq-001');
    expect(result.current.data![0].project_id).toBe('proj-001');
    expect(result.current.data![0].name).toBe('Main Estimate');
    expect(result.current.data![1].id).toBe('boq-002');
  });

  it('useQuery: fetches a single BOQ with positions', async () => {
    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ['boq', 'boq-001'],
          queryFn: () => boqApi.get('boq-001'),
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const boq = result.current.data!;
    expect(boq.id).toBe('boq-001');
    expect(boq.grand_total).toBe(54225.0);
    expect(boq.positions).toHaveLength(1);

    const pos = boq.positions[0];
    expect(pos.ordinal).toBe('01.001');
    expect(pos.unit).toBe('m3');
    expect(pos.quantity).toBe(120.5);
    expect(pos.unit_rate).toBe(450.0);
    expect(pos.total).toBe(54225.0);
  });

  it('useQuery: returns error state on 500 response from BOQ list', async () => {
    server.use(
      http.get('/api/v1/boq/boqs/', () => {
        return HttpResponse.json(
          { detail: 'Database connection failed' },
          { status: 500 },
        );
      }),
    );

    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ['boqs', 'proj-001'],
          queryFn: () => boqApi.list('proj-001'),
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeInstanceOf(ApiError);
    const apiErr = result.current.error as ApiError;
    expect(apiErr.status).toBe(500);
    expect(result.current.data).toBeUndefined();
  });

  it('useQuery: returns error state on 404 for unknown BOQ id', async () => {
    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ['boq', 'boq-nonexistent'],
          queryFn: () => boqApi.get('boq-nonexistent'),
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));

    const apiErr = result.current.error as ApiError;
    expect(apiErr.status).toBe(404);
  });

  it('useQuery: BOQ list is empty when project has no BOQs', async () => {
    // Project with no BOQs — handler returns empty array for unknown project id
    server.use(
      http.get('/api/v1/boq/boqs/', ({ request }) => {
        const url = new URL(request.url);
        const projectId = url.searchParams.get('project_id');
        if (projectId === 'proj-empty') {
          return HttpResponse.json([]);
        }
        return HttpResponse.json(MOCK_BOQS);
      }),
    );

    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ['boqs', 'proj-empty'],
          queryFn: () => boqApi.list('proj-empty'),
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toHaveLength(0);
    expect(Array.isArray(result.current.data)).toBe(true);
  });

  it('useQuery: passes through BOQ position fields accurately', async () => {
    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ['boq', 'boq-001'],
          queryFn: () => boqApi.get('boq-001'),
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const position = result.current.data!.positions[0];
    expect(position).toMatchObject({
      id: expect.any(String),
      boq_id: expect.any(String),
      ordinal: expect.any(String),
      description: expect.any(String),
      unit: expect.any(String),
      quantity: expect.any(Number),
      unit_rate: expect.any(Number),
      total: expect.any(Number),
      classification: expect.any(Object),
      source: expect.any(String),
      validation_status: expect.any(String),
      sort_order: expect.any(Number),
      metadata: expect.any(Object),
    });
  });

  it('useQuery: handles 503 Service Unavailable gracefully', async () => {
    server.use(
      http.get('/api/v1/boq/boqs/:id', () => {
        return HttpResponse.json(
          { detail: 'Service temporarily unavailable' },
          { status: 503 },
        );
      }),
    );

    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () =>
        useQuery({
          queryKey: ['boq', 'boq-001'],
          queryFn: () => boqApi.get('boq-001'),
        }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));

    const apiErr = result.current.error as ApiError;
    expect(apiErr.status).toBe(503);
    expect(apiErr.message).toContain('503');
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   Loading state / suspense transition tests
═══════════════════════════════════════════════════════════════════════ */

describe('React Query loading state transitions', () => {
  it('transitions from loading → success for project list', async () => {
    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () => useQuery({ queryKey: ['projects'], queryFn: () => projectsApi.list() }),
      { wrapper },
    );

    // Before resolution: pending
    expect(result.current.isPending).toBe(true);
    expect(result.current.isFetching).toBe(true);
    expect(result.current.isError).toBe(false);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // After resolution
    expect(result.current.isPending).toBe(false);
    expect(result.current.isFetching).toBe(false);
    expect(result.current.isError).toBe(false);
    expect(result.current.data).toBeDefined();
  });

  it('transitions from loading → error for 500 response', async () => {
    server.use(
      http.get('/api/v1/projects/', () => {
        return HttpResponse.json({ detail: 'Server error' }, { status: 500 });
      }),
    );

    const queryClient = makeQueryClient();
    const wrapper = createWrapper(queryClient);

    const { result } = renderHook(
      () => useQuery({ queryKey: ['projects'], queryFn: () => projectsApi.list() }),
      { wrapper },
    );

    // Initially fetching
    expect(result.current.isPending).toBe(true);

    await waitFor(() => expect(result.current.isError).toBe(true));

    // Terminal error state
    expect(result.current.isPending).toBe(false);
    expect(result.current.isSuccess).toBe(false);
    expect(result.current.data).toBeUndefined();
    expect(result.current.error).toBeDefined();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   ApiError class unit tests (no network required)
═══════════════════════════════════════════════════════════════════════ */

describe('ApiError class', () => {
  it('constructs with correct status, statusText and body', () => {
    const err = new ApiError(422, 'Unprocessable Entity', { detail: 'Validation failed' });
    expect(err.status).toBe(422);
    expect(err.statusText).toBe('Unprocessable Entity');
    expect(err.body).toEqual({ detail: 'Validation failed' });
    expect(err.message).toBe('API 422: Unprocessable Entity');
    expect(err.name).toBe('ApiError');
  });

  it('is an instance of Error', () => {
    const err = new ApiError(500, 'Internal Server Error', null);
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(ApiError);
  });

  it('accepts undefined body', () => {
    const err = new ApiError(401, 'Unauthorized', undefined);
    expect(err.body).toBeUndefined();
    expect(err.status).toBe(401);
  });
});
