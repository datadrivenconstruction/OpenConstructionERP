// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings, Developer: both cards render from the server, a new key's plaintext
 * is shown once and is gone after it is dismissed, and rotating or revoking asks first.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPost: vi.fn(), apiDelete: vi.fn(), apiPatch: vi.fn() };
});

import * as api from '@/shared/lib/api';
import DeveloperTab from '../DeveloperTab';

const apiGet = vi.mocked(api.apiGet);
const apiPost = vi.mocked(api.apiPost);
const apiDelete = vi.mocked(api.apiDelete);

const KEY = {
  id: 'k-1',
  name: 'BI export',
  key_prefix: 'oe_abcdefghi',
  description: '',
  is_active: true,
  permissions: ['boq.read'],
  rate_limit_per_min: null,
  allowed_cidrs: [],
  request_count: 42,
  rotated_from_id: null,
  expires_at: '2027-01-01T00:00:00Z',
  last_used_at: null,
  created_at: '2026-10-01T00:00:00Z',
};

const HOOK = {
  id: 'w-1',
  name: 'ERP feed',
  url: 'https://erp.example.com/in',
  secret: '***',
  events: ['*'],
  is_active: true,
  last_triggered_at: null,
  last_status_code: null,
  failure_count: 0,
  created_at: '2026-10-01T00:00:00Z',
};

const DELIVERY = {
  id: 'd-1',
  webhook_id: 'w-1',
  event_type: 'boq.position.created',
  status_code: 500,
  duration_ms: 12,
  attempt: 2,
  next_retry_at: null,
  status: 'dead',
  last_error: 'http 500',
  created_at: '2026-10-25T10:00:00Z',
};

function serve() {
  const routes: Record<string, unknown> = {
    '/v1/users/me/api-keys/': [KEY],
    '/v1/users/me/api-keys/scopes/': [
      { name: 'boq.read', module: 'boq', i18n_key: 'developer.scope.boq.read', action: 'read', min_role: 'viewer' },
    ],
    '/v1/integrations/webhooks/': [HOOK],
    '/v1/integrations/webhooks/events/': [
      { name: 'boq.position.created', module: 'boq', i18n_key: 'developer.event.boq.position.created' },
    ],
    '/v1/integrations/webhooks/w-1/deliveries/': [DELIVERY],
  };
  apiGet.mockImplementation(async (path: string) => {
    if (path in routes) return routes[path];
    throw new Error(`unexpected GET ${path}`);
  });
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DeveloperTab />
    </QueryClientProvider>,
  );
}

describe('DeveloperTab', () => {
  beforeEach(() => {
    cleanup();
    vi.clearAllMocks();
    serve();
  });

  it('lists the keys and webhooks the server returns', async () => {
    renderTab();
    expect(await screen.findByTestId('developer-key-k-1')).toHaveTextContent('BI export');
    expect(screen.getByTestId('developer-key-k-1')).toHaveTextContent('42');
    expect(await screen.findByTestId('developer-hook-w-1')).toHaveTextContent('https://erp.example.com/in');
  });

  it('shows the new key once and forgets it when dismissed', async () => {
    apiPost.mockResolvedValueOnce({ ...KEY, id: 'k-2', name: 'New', key: 'oe_PLAINTEXT_SECRET' });
    renderTab();
    await screen.findByTestId('developer-key-k-1');

    fireEvent.click(screen.getByTestId('developer-key-new'));
    fireEvent.change(await screen.findByTestId('developer-key-name'), { target: { value: 'New' } });
    fireEvent.click(screen.getByTestId('developer-key-create'));

    expect(await screen.findByTestId('developer-key-reveal-value')).toHaveTextContent('oe_PLAINTEXT_SECRET');
    const [path, body] = apiPost.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe('/v1/users/me/api-keys/');
    expect(body).toMatchObject({ name: 'New', permissions: [], expires_in_days: 90, allowed_cidrs: [] });

    fireEvent.click(screen.getByTestId('developer-key-reveal-done'));
    await waitFor(() => expect(screen.queryByText('oe_PLAINTEXT_SECRET')).toBeNull());
  });

  it('rotates only after the person confirms', async () => {
    apiPost.mockResolvedValueOnce({ ...KEY, id: 'k-3', key: 'oe_ROTATED' });
    renderTab();
    await screen.findByTestId('developer-key-k-1');

    fireEvent.click(screen.getByRole('button', { name: 'Rotate BI export' }));
    expect(apiPost).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole('button', { name: 'Rotate' }));
    expect(await screen.findByTestId('developer-key-reveal-value')).toHaveTextContent('oe_ROTATED');
    expect(apiPost).toHaveBeenCalledWith('/v1/users/me/api-keys/k-1/rotate/');
  });

  it('revokes only after the person confirms', async () => {
    apiDelete.mockResolvedValueOnce(undefined);
    renderTab();
    await screen.findByTestId('developer-key-k-1');

    fireEvent.click(screen.getByRole('button', { name: 'Revoke BI export' }));
    expect(apiDelete).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke' }));
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith('/v1/users/me/api-keys/k-1'));
  });

  it('sends a test event and lets a failed delivery be sent again', async () => {
    apiPost.mockResolvedValue({ ...DELIVERY, status: 'delivered' });
    renderTab();
    await screen.findByTestId('developer-hook-w-1');

    fireEvent.click(screen.getByTestId('developer-hook-test-w-1'));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/v1/integrations/webhooks/w-1/test/'));

    fireEvent.click(screen.getByRole('button', { name: /Deliveries/ }));
    fireEvent.click(await screen.findByTestId('developer-redeliver-d-1'));
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith('/v1/integrations/webhooks/deliveries/d-1/redeliver/'),
    );
  });
});
