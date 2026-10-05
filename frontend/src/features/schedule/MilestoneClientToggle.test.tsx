// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A milestone reaches the client portal only when a person ticks the box,
// and the box always says what the server last stored.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, fireEvent, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { Activity } from './api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
  initReactI18next: { type: '3rdParty', init: () => undefined },
}));

const updateActivity = vi.hoisted(() => vi.fn());
vi.mock('./api', async (importOriginal) => {
  const real = await importOriginal<typeof import('./api')>();
  return { ...real, scheduleApi: { ...real.scheduleApi, updateActivity } };
});

const { MilestoneClientToggle } = await import('./MilestoneClientToggle');
const { useToastStore } = await import('@/stores/useToastStore');

function mount(clientVisible: boolean | undefined) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  const activity = { id: 'a1', name: 'Roof on', activity_type: 'milestone', client_visible: clientVisible };
  render(
    <QueryClientProvider client={client}>
      <MilestoneClientToggle scheduleId="s1" activity={activity as unknown as Activity} />
    </QueryClientProvider>,
  );
  return { invalidate, box: screen.getByRole('checkbox') as HTMLInputElement };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('showing a milestone to the client', () => {
  it('starts unticked for a milestone nobody released, including one without the field', () => {
    expect(mount(undefined).box.checked).toBe(false);
    cleanup();
    expect(mount(false).box.checked).toBe(false);
  });

  it('starts ticked for a released milestone', () => {
    expect(mount(true).box.checked).toBe(true);
  });

  it('sends the new value and refreshes the gantt it came from', async () => {
    updateActivity.mockResolvedValue({});
    const { box, invalidate } = mount(false);
    fireEvent.click(box);
    await waitFor(() => expect(updateActivity).toHaveBeenCalledWith('a1', { client_visible: true }));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['gantt', 's1'] }));
  });

  it('can take a milestone back from the client', async () => {
    updateActivity.mockResolvedValue({});
    const { box } = mount(true);
    fireEvent.click(box);
    await waitFor(() => expect(updateActivity).toHaveBeenCalledWith('a1', { client_visible: false }));
  });

  it('says so when the server refuses', async () => {
    const addToast = vi.spyOn(useToastStore.getState(), 'addToast');
    updateActivity.mockRejectedValue(new Error('403'));
    const { box, invalidate } = mount(false);
    fireEvent.click(box);
    await waitFor(() =>
      expect(addToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'error', title: 'Could not change what the client sees.' }),
      ),
    );
    expect(invalidate).not.toHaveBeenCalled();
  });
});
