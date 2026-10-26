// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The MCP settings card: what it asks the server for, that a new token's secret
 * and client configuration are shown once, that revoking asks first, and that
 * the review button opens the assistant's Changes tab.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(), apiPut: vi.fn(), apiPost: vi.fn(), apiDelete: vi.fn() };
});

import * as api from '@/shared/lib/api';
import { useFloatingChatStore } from '@/features/erp-chat/useFloatingChat';
import { McpSettingsPanel } from '../McpSettingsPanel';

const apiGet = vi.mocked(api.apiGet);
const apiPut = vi.mocked(api.apiPut);
const apiPost = vi.mocked(api.apiPost);
const apiDelete = vi.mocked(api.apiDelete);

const TOKEN = {
  id: 't-1',
  name: 'Laptop',
  key_prefix: 'oe_abcdefghi',
  is_active: true,
  can_propose: true,
  expires_at: '2027-01-01T00:00:00Z',
  last_used_at: null,
  created_at: '2026-10-01T00:00:00Z',
};

function serve(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    '/v1/mcp/settings/': { enabled: true, rate_limit_per_minute: 60, endpoint_path: '/api/v1/mcp', protocol_versions: ['2025-06-18'] },
    '/v1/mcp/tokens/': [TOKEN],
    '/v1/mcp/calls/?limit=25': [
      {
        id: 'c-1', tool: 'get_boq', kind: 'read', outcome: 'denied', duration_ms: 12, project_id: null,
        token_prefix: 'oe_abcdefghi', action_id: null, error: 'project_not_found', created_at: '2026-10-25T10:00:00Z',
      },
    ],
    '/v1/mcp/validation/': {
      status: 'warnings',
      score: 0.8,
      findings: [
        { rule_id: 'mcp.token_unused', severity: 'warning', key: 'mcp.validation.token_unused', message: "Token 'Laptop' has not been used for 40 days.", params: { name: 'Laptop', days: 40 }, element_ref: 't-1' },
      ],
    },
    ...overrides,
  };
  apiGet.mockImplementation(async (path: string) => {
    if (path.startsWith('/v1/erp_chat/actions/')) {
      return { items: [], total: 0, counts: { proposed: 3, applied: 0, rejected: 0, failed: 0, reverted: 0 } };
    }
    if (path in routes) return routes[path];
    throw new Error(`unexpected GET ${path}`);
  });
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <McpSettingsPanel origin="https://erp.example.com" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useFloatingChatStore.setState({ isOpen: false, changesRequested: false });
});

describe('McpSettingsPanel', () => {
  it('shows tokens, findings, recent calls and the waiting proposals of external clients', async () => {
    serve();
    renderPanel();
    expect(await screen.findByText('Laptop')).toBeInTheDocument();
    expect(await screen.findByText("Token 'Laptop' has not been used for 40 days.")).toBeInTheDocument();
    expect(await screen.findByText('get_boq')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('mcp-pending')).toHaveTextContent('3'));
    expect(apiGet).toHaveBeenCalledWith(expect.stringMatching(/source=mcp/));
    expect(apiGet).toHaveBeenCalledWith(expect.stringMatching(/status=proposed/));
  });

  it('creates a token and shows its secret and the client configuration once', async () => {
    serve();
    apiPost.mockResolvedValue({ ...TOKEN, id: 't-2', name: 'IDE', token: 'oe_the_secret' });
    renderPanel();
    await screen.findByText('Laptop');
    fireEvent.change(screen.getByTestId('mcp-token-name'), { target: { value: 'IDE' } });
    fireEvent.click(screen.getByTestId('mcp-create-token'));
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith('/v1/mcp/tokens/', { name: 'IDE', expires_in_days: 90, can_propose: true }),
    );
    const config = await screen.findByTestId('mcp-config');
    expect(config.textContent).toContain('Bearer oe_the_secret');
    expect(config.textContent).toContain('https://erp.example.com/api/v1/mcp');
  });

  it('cannot create a token while MCP is switched off', async () => {
    serve({ '/v1/mcp/settings/': { enabled: false, rate_limit_per_minute: 60, endpoint_path: '/api/v1/mcp', protocol_versions: [] } });
    renderPanel();
    await screen.findByText('Laptop');
    fireEvent.change(screen.getByTestId('mcp-token-name'), { target: { value: 'IDE' } });
    expect(screen.getByTestId('mcp-create-token')).toBeDisabled();
  });

  it('switches MCP through the settings endpoint', async () => {
    serve();
    apiPut.mockResolvedValue({ enabled: false, rate_limit_per_minute: 60, endpoint_path: '/api/v1/mcp', protocol_versions: [] });
    renderPanel();
    const toggle = await screen.findByTestId('mcp-enabled');
    await waitFor(() => expect(toggle).toBeChecked());
    fireEvent.click(toggle);
    await waitFor(() => expect(apiPut).toHaveBeenCalledWith('/v1/mcp/settings/', { enabled: false }));
  });

  it('asks before revoking and then calls the revoke endpoint', async () => {
    serve();
    apiDelete.mockResolvedValue(undefined);
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Revoke Laptop' }));
    expect(apiDelete).not.toHaveBeenCalled();
    const dialog = await screen.findByRole('alertdialog');
    const confirmButtons = Array.from(dialog.querySelectorAll('button')).filter((b) => b.textContent === 'Revoke');
    fireEvent.click(confirmButtons[confirmButtons.length - 1]!);
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith('/v1/mcp/tokens/t-1/'));
  });

  it('opens the assistant on its Changes tab to review proposals', async () => {
    serve();
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Review changes' }));
    expect(useFloatingChatStore.getState().isOpen).toBe(true);
    expect(useFloatingChatStore.getState().changesRequested).toBe(true);
  });
});
