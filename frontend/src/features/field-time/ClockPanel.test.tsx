// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiGetMock = vi.fn();
const apiPostMock = vi.fn();
const enqueueMock = vi.fn();
let online = true;

vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  apiGet: (...a: unknown[]) => apiGetMock(...a),
  apiPost: (...a: unknown[]) => apiPostMock(...a),
}));
vi.mock('@/features/resources/api', () => ({
  listResources: async () => ({
    items: [{ id: 'r1', name: 'Ann Mason', resource_type: 'person' }],
    total: 1,
  }),
}));
vi.mock('@/shared/hooks/useOnlineStatus', () => ({ useOnlineStatus: () => online }));
vi.mock('./clockOffline', () => ({ enqueueClockEvent: (...a: unknown[]) => enqueueMock(...a) }));

import { ClockPanel } from './ClockPanel';
import { useClockStore } from './clockStore';

const getPosition = vi.fn();

function setup(consentGranted: boolean) {
  apiGetMock.mockImplementation(async (url: string) => {
    if (url.includes('/clock/settings/'))
      return { project_id: 'p', enabled: true, retention_days: 45, consent_text_version: 'v2', default_break_minutes: 30 };
    if (url.includes('/clock/status/'))
      return { project_id: 'p', on_site: [], on_site_count: 0, pending_approvals: 0, missing_clock_outs: 0, today_hours: '0' };
    if (url.includes('/clock/consent/'))
      return { resource_id: 'r1', project_id: 'p', granted: consentGranted, granted_at: null, withdrawn_at: null, text_version: 'v2' };
    return {};
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ClockPanel projectId="p" />
    </QueryClientProvider>,
  );
}

async function pickWorker() {
  const select = await screen.findByLabelText('Who is clocking?');
  await screen.findByText('Ann Mason');
  fireEvent.change(select, { target: { value: 'r1' } });
}

describe('ClockPanel', () => {
  beforeEach(() => {
    online = true;
    useClockStore.getState().reset();
    getPosition.mockReset();
    getPosition.mockImplementation((ok: (p: unknown) => void) =>
      ok({ coords: { latitude: 52.5, longitude: 13.4, accuracy: 8 } }),
    );
    Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition: getPosition }, configurable: true });
    apiGetMock.mockReset();
    apiPostMock.mockReset();
    enqueueMock.mockReset();
  });
  afterEach(cleanup);

  it('asks for consent first, without touching the position, and posts it', async () => {
    setup(false);
    await pickWorker();
    // The consent answer decides what the tap does, so wait for it to land.
    await waitFor(() => expect(apiGetMock.mock.calls.some((c) => String(c[0]).includes('/clock/consent/'))).toBe(true));
    await new Promise((r) => setTimeout(r, 20));
    fireEvent.click(await screen.findByRole('button', { name: /Clock in/ }));
    const dialog = await screen.findByRole('dialog');
    expect(dialog.textContent).toContain('45 days');
    expect(getPosition).not.toHaveBeenCalled();

    apiPostMock.mockResolvedValue({});
    fireEvent.click(screen.getByRole('button', { name: 'I agree' }));
    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith('/v1/field-time/clock/consent/', {
        project_id: 'p',
        resource_id: 'r1',
        granted: true,
        text_version: 'v2',
      }),
    );
  });

  it('reads the position once and warns, without blocking, when outside', async () => {
    setup(true);
    await pickWorker();
    await screen.findByText('Withdraw my location consent');
    apiPostMock.mockResolvedValue({
      id: 'e1', kind: 'in', occurred_at: '2026-10-26T07:00:00Z', inside: false, distance_m: 250.4,
      geofence_name: null, approval_status: 'pending',
    });
    fireEvent.click(screen.getByRole('button', { name: /Clock in/ }));
    const status = await screen.findByRole('status');
    expect(status.textContent).toContain('250 m');
    expect(status.textContent).toContain('flagged for supervisor approval');
    expect(getPosition).toHaveBeenCalledTimes(1);
    const body = apiPostMock.mock.calls[0]![1] as Record<string, unknown>;
    expect(body).toMatchObject({ kind: 'in', latitude: 52.5, longitude: 13.4, accuracy_m: 8 });
    expect(typeof body.client_op_id).toBe('string');
    expect(typeof body.occurred_at).toBe('string');
  });

  it('queues the tap on the device when offline', async () => {
    online = false;
    setup(true);
    await pickWorker();
    await screen.findByText('Withdraw my location consent');
    fireEvent.click(screen.getByRole('button', { name: /Clock in/ }));
    await waitFor(() => expect(enqueueMock).toHaveBeenCalledTimes(1));
    expect(apiPostMock).not.toHaveBeenCalled();
    expect((await screen.findByRole('status')).textContent).toContain('Saved on this device');
  });
});
