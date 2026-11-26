// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tests for the Pillar 5 Hold / Witness section.
//
// The API layer is stubbed via vi.mock('../api') so we can verify:
//   - a loaded gate row renders with its number, title and status,
//   - creating a gate submits the create payload to the API,
//   - releasing a pending gate calls the release endpoint (success path).
//
// React Query runs with retry disabled so any error surfaces immediately.

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';

// Automock the whole feature-local API so every export is a vi.fn(). A partial
// factory mock here would bleed across the construction_control suite (the
// module path is shared) and strip exports the sibling sections need, so the
// section tests all automock '../api' consistently.
vi.mock('../api');

import { listGates, createGate, releaseGate } from '../api';
import { HoldWitnessSection } from './HoldWitnessSection';

const PROJECT_ID = 'proj-1';

type GateOverrides = Partial<Record<string, unknown>>;

function makeGate(overrides: GateOverrides = {}) {
  return {
    id: 'gate-1',
    project_id: PROJECT_ID,
    gate_number: 'HG-001',
    point_type: 'hold',
    title: 'Hold - rebar witness before pour',
    description: null,
    required_party_role: 'qa',
    inspection_id: null,
    criterion_id: null,
    attached_kind: null,
    attached_id: null,
    blocks_progress: true,
    status: 'pending',
    released_by: null,
    released_party_role: null,
    released_at: null,
    release_justification: null,
    release_signature_ip: null,
    release_signature_sha256: null,
    waived_by: null,
    waived_reason: null,
    approval_instance_id: null,
    created_by: null,
    metadata: {},
    created_at: '2026-06-23T00:00:00Z',
    updated_at: '2026-06-23T00:00:00Z',
    ...overrides,
  };
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HoldWitnessSection projectId={PROJECT_ID} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('HoldWitnessSection', () => {
  beforeEach(() => {
    useAuthStore.setState({ userRole: 'admin' } as never);
    vi.clearAllMocks();
    (listGates as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (createGate as ReturnType<typeof vi.fn>).mockResolvedValue(makeGate());
    (releaseGate as ReturnType<typeof vi.fn>).mockResolvedValue(
      makeGate({ status: 'released', released_party_role: 'qa' }),
    );
  });

  it('renders a loaded gate row', async () => {
    (listGates as ReturnType<typeof vi.fn>).mockResolvedValue([makeGate()]);
    renderSection();

    await waitFor(() => expect(listGates).toHaveBeenCalledWith(PROJECT_ID));
    expect(await screen.findByText('Hold - rebar witness before pour')).toBeInTheDocument();
    expect(screen.getByText('HG-001')).toBeInTheDocument();
    expect(screen.getByTestId('cc-gate-row-gate-1')).toBeInTheDocument();
  });

  it('shows the empty state when there are no gates', async () => {
    renderSection();
    expect(await screen.findByText(/No hold or witness points yet/i)).toBeInTheDocument();
  });

  it('submits the create-gate payload', async () => {
    renderSection();
    await waitFor(() => expect(listGates).toHaveBeenCalled());

    // Open the create modal (the toolbar button, not the empty-state action).
    fireEvent.click(screen.getByRole('button', { name: /New gate/i }));

    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/Title/i), {
      target: { value: 'Witness point - weld inspection' },
    });

    fireEvent.click(within(dialog).getByRole('button', { name: /Create gate/i }));

    await waitFor(() => expect(createGate).toHaveBeenCalledTimes(1));
    const [payload] = (createGate as ReturnType<typeof vi.fn>).mock.calls[0] ?? [];
    expect(payload).toMatchObject({
      project_id: PROJECT_ID,
      point_type: 'hold',
      title: 'Witness point - weld inspection',
      required_party_role: 'qa',
    });
  });

  it('releases a pending gate (success path)', async () => {
    (listGates as ReturnType<typeof vi.fn>).mockResolvedValue([makeGate()]);
    renderSection();

    expect(await screen.findByText('Hold - rebar witness before pour')).toBeInTheDocument();

    // Open the release modal from the row action.
    const row = screen.getByTestId('cc-gate-row-gate-1');
    fireEvent.click(within(row).getByRole('button', { name: /Release/i }));

    const dialog = await screen.findByRole('dialog');
    // The asserted role defaults to the gate's required role (qa), so the
    // confirm button is enabled immediately.
    fireEvent.click(within(dialog).getByRole('button', { name: /Release/i }));

    await waitFor(() => expect(releaseGate).toHaveBeenCalledTimes(1));
    const [gateId, releasePayload] = (releaseGate as ReturnType<typeof vi.fn>).mock.calls[0] ?? [];
    expect(gateId).toBe('gate-1');
    expect(releasePayload).toMatchObject({ party_role: 'qa' });
  });
});
