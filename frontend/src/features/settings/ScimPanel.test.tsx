// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn() };
});

import { ScimPanel } from './ScimPanel';
import { apiGet, apiPost, apiPatch } from '@/shared/lib/api';

const getMock = vi.mocked(apiGet);
const postMock = vi.mocked(apiPost);
const patchMock = vi.mocked(apiPatch);

function status(over: Record<string, unknown> = {}) {
  return {
    base_path: '/scim/v2',
    users_provisioned: 2,
    last_change_at: '2026-11-03T10:00:00Z',
    allow_admin_groups: false,
    sso_enforced_domains: [],
    users: [
      { id: 'u1', email: 'anna@corp.example', full_name: 'Anna', role: 'editor', is_active: true, source: 'scim', last_sync_at: '2026-11-03T10:00:00Z' },
      { id: 'u2', email: 'bob@corp.example', full_name: '', role: 'viewer', is_active: false, source: 'oidc', last_sync_at: null },
      { id: 'u3', email: 'root@corp.example', full_name: '', role: 'admin', is_active: true, source: 'local', last_sync_at: null },
    ],
    groups: [{ id: 'g1', display_name: 'Estimators', role: null, member_count: 4 }],
    ...over,
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ScimPanel />
    </QueryClientProvider>,
  );
}

describe('<ScimPanel>', () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    patchMock.mockReset();
  });

  it('shows the base URL, the status line, source badges and the three IdP hints', async () => {
    getMock.mockResolvedValue(status());
    renderPanel();
    expect(screen.getByTestId('scim-base-url').textContent).toBe(`${window.location.origin}/scim/v2`);
    await screen.findByTestId('scim-users');
    expect(screen.getByTestId('scim-status-line').textContent).toMatch(/2 users provisioned, last change/);
    const users = within(screen.getByTestId('scim-users'));
    expect(users.getByText('SCIM')).toBeTruthy();
    expect(users.getByText('OIDC')).toBeTruthy();
    expect(users.getByText('Local')).toBeTruthy();
    expect(users.getByText('Inactive')).toBeTruthy();
    expect(screen.getByTestId('scim-hint').querySelectorAll('li').length).toBe(3);
  });

  it('creates a scim-scoped key and shows the token only until it is dismissed', async () => {
    getMock.mockResolvedValue(status());
    postMock.mockResolvedValue({ key: 'oek_secret_token' });
    renderPanel();
    await screen.findByTestId('scim-users');
    expect(screen.queryByTestId('scim-token')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Generate token/ }));
    expect((await screen.findByTestId('scim-token')).textContent).toBe('oek_secret_token');
    expect(postMock).toHaveBeenCalledWith(
      '/v1/users/me/api-keys/',
      expect.objectContaining({ permissions: ['scim'] }),
    );
    fireEvent.click(screen.getByRole('button', { name: /I have saved it/ }));
    expect(screen.queryByTestId('scim-token')).toBeNull();
    expect(document.body.textContent).not.toContain('oek_secret_token');
  });

  it('disables the admin option unless the server setting allows it', async () => {
    getMock.mockResolvedValue(status());
    renderPanel();
    const select = (await screen.findByLabelText('Role for Estimators')) as HTMLSelectElement;
    const admin = Array.from(select.options).find((o) => o.value === 'admin');
    expect(admin?.disabled).toBe(true);
    expect(Array.from(select.options).find((o) => o.value === 'manager')?.disabled).toBe(false);
  });

  it('enables the admin option when the setting is on and saves the chosen role', async () => {
    getMock.mockResolvedValue(status({ allow_admin_groups: true }));
    patchMock.mockResolvedValue({});
    renderPanel();
    const select = (await screen.findByLabelText('Role for Estimators')) as HTMLSelectElement;
    expect(Array.from(select.options).find((o) => o.value === 'admin')?.disabled).toBe(false);
    fireEvent.change(select, { target: { value: 'editor' } });
    await waitFor(() => expect(patchMock).toHaveBeenCalledWith('/v1/scim/groups/g1/', { role: 'editor' }));
  });

  it('says so when nobody is provisioned yet', async () => {
    getMock.mockResolvedValue(status({ users_provisioned: 0, last_change_at: null, users: [], groups: [] }));
    renderPanel();
    await screen.findByText(/No groups yet/);
    expect(screen.getByTestId('scim-status-line').textContent).toBe('No users provisioned yet');
  });
});
