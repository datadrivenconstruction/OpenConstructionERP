// @ts-nocheck
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api', () => ({ listEquipment: vi.fn().mockResolvedValue({ items: [{ id: 'e1', code: 'EX-01', name: 'Excavator' }] }) }));
vi.mock('../telematicsApi', () => ({
  createTelematicsDevice: vi.fn(),
  revokeTelematicsDevice: vi.fn(),
  fetchTelematicsDevices: vi.fn().mockResolvedValue([
    { id: 'd1', equipment_id: 'e1', label: 'cab', token_prefix: 'oet_abc', active: true, last_seen_at: null, silent_hours: 30 },
    { id: 'd2', equipment_id: 'e1', label: 'spare', token_prefix: 'oet_def', active: true, last_seen_at: null, silent_hours: null },
  ]),
}));

import { TelematicsDevices } from './TelematicsDevices';

describe('TelematicsDevices', () => {
  it('flags only the device that went silent while hired', async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <TelematicsDevices />
      </QueryClientProvider>,
    );
    await screen.findByText('cab');
    expect(screen.getAllByText(/No signal for over a day/i)).toHaveLength(1);
  });
});
