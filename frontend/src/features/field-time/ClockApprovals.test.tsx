// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiGetMock = vi.fn();
const apiPostMock = vi.fn();

vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  apiGet: (...a: unknown[]) => apiGetMock(...a),
  apiPost: (...a: unknown[]) => apiPostMock(...a),
}));
vi.mock('./GeofenceMap', () => ({ default: () => null, mapSupported: () => false }));

import { ClockApprovals } from './ClockApprovals';

const pendingEvent = {
  id: 'e1', project_id: 'p', resource_id: 'r1', resource_name: 'Ann Mason', kind: 'in',
  occurred_at: '2026-10-26T07:00:00Z', latitude: 52.5, longitude: 13.4, accuracy_m: 8,
  geofence_id: null, geofence_name: null, inside: false, distance_m: 320, approval_status: 'pending',
  approval_reason: null, approved_by: null, approved_at: null, pair_event_id: null, timesheet_id: null,
  position_purged: false, created_at: '',
};

describe('ClockApprovals', () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiPostMock.mockReset();
    apiGetMock.mockImplementation(async (url: string) =>
      url.includes('/clock/events/') ? { items: [pendingEvent], total: 1 } : [],
    );
  });
  afterEach(cleanup);

  it('needs a reason before approve or reject, then sends it', async () => {
    apiPostMock.mockResolvedValue({ ...pendingEvent, approval_status: 'approved' });
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ClockApprovals projectId="p" />
      </QueryClientProvider>,
    );
    expect(await screen.findByText('320 m outside the site area')).toBeTruthy();
    const approve = screen.getByRole('button', { name: /Approve/ });
    const reject = screen.getByRole('button', { name: /Reject/ });
    expect(approve).toBeDisabled();
    expect(reject).toBeDisabled();

    const box = screen.getByLabelText('Reason (required)');
    fireEvent.change(box, { target: { value: 'ab' } });
    expect(approve).toBeDisabled();
    fireEvent.change(box, { target: { value: 'Gate was closed' } });
    expect(approve).not.toBeDisabled();

    fireEvent.click(approve);
    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith('/v1/field-time/clock/events/e1/approve/', {
        reason: 'Gate was closed',
      }),
    );
  });
});
