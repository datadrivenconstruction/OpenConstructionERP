import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError } from '@/shared/lib/api';
import { ScheduleLifecycleActions } from './ScheduleLifecycleActions';
import { scheduleApi, type Schedule } from './api';

vi.mock('react-i18next', async () => {
  const actual = await vi.importActual<typeof import('react-i18next')>('react-i18next');
  const { default: en } = await import('@/app/locales/en');
  const t = (key: string, options: Record<string, unknown> = {}) =>
    String((en.translation as Record<string, string>)[key] ?? options.defaultValue ?? key)
      .replace(/\{\{\s*(\w+)\s*\}\}/g, (_match, field: string) => String(options[field] ?? ''));
  return { ...actual, useTranslation: () => ({ t, i18n: { language: 'en' } }) };
});
vi.mock('./api', () => ({ scheduleApi: {
  archiveSchedule: vi.fn(), restoreSchedule: vi.fn(), purgeSchedule: vi.fn(), getDeleteImpact: vi.fn(),
} }));

const schedule: Schedule = {
  id: 's1', project_id: 'p1', name: 'Contract plan', description: '', status: 'active',
  start_date: null, end_date: null, created_at: '', updated_at: '',
};

function view(overrides: Partial<Schedule> = {}, compact = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  const onChanged = vi.fn();
  const openCard = vi.fn();
  render(<QueryClientProvider client={client}><div onClick={openCard}>
    <ScheduleLifecycleActions schedule={{ ...schedule, ...overrides }} onChanged={onChanged} compact={compact} />
  </div></QueryClientProvider>);
  return { onChanged, openCard, invalidate };
}

beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({ userRole: 'editor' });
  useToastStore.setState({ toasts: [] });
  vi.mocked(scheduleApi.getDeleteImpact).mockResolvedValue({ activity_count: 3, baseline_count: 2,
    payment_milestone_count: 1, can_delete: true });
  vi.mocked(scheduleApi.restoreSchedule).mockResolvedValue({ ...schedule, status: 'draft' });
});

describe('reversible archive actions', () => {
  it.each(['active', 'draft', 'completed', 'frozen'])('archives %s, never calls permanent-delete APIs', async (status) => {
    const { onChanged, openCard, invalidate } = view({ status }, true);
    fireEvent.click(screen.getByRole('button', { name: 'Archive Contract plan' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('activities, baselines and links will be kept');
    expect(scheduleApi.archiveSchedule).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Archive' }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(scheduleApi.archiveSchedule).toHaveBeenCalledExactlyOnceWith('s1');
    expect(scheduleApi.getDeleteImpact).not.toHaveBeenCalled();
    expect(scheduleApi.purgeSchedule).not.toHaveBeenCalled();
    expect(openCard).not.toHaveBeenCalled();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['schedules'] });
  });

  it('cancel performs no request', async () => {
    view();
    fireEvent.click(screen.getByRole('button', { name: 'Archive Contract plan' }));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(scheduleApi.archiveSchedule).not.toHaveBeenCalled();
  });

  it.each(['draft', 'active', 'completed', 'frozen'])('restores the recorded %s status, never assumes active', async (status) => {
    vi.mocked(scheduleApi.restoreSchedule).mockResolvedValue({ ...schedule, status });
    view({ status: 'archived', metadata_: { _schedule_archive: { previous_status: status } } });
    fireEvent.click(screen.getByRole('button', { name: 'Restore Contract plan' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent(`status “${status}”`);
    expect(dialog).not.toHaveTextContent('previous status was not recorded');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Restore' }));
    await waitFor(() => expect(scheduleApi.restoreSchedule).toHaveBeenCalledExactlyOnceWith('s1'));
    await waitFor(() => expect(useToastStore.getState().toasts[0]?.title).toBe(`Schedule restored: ${status}`));
  });

  it('warns explicitly when a legacy archive must fall back to draft', async () => {
    vi.mocked(scheduleApi.restoreSchedule).mockResolvedValue({ ...schedule, status: 'draft',
      metadata_: { _schedule_archive: { previous_status: 'draft', restore_used_fallback: true } } });
    view({ status: 'archived' });
    fireEvent.click(screen.getByRole('button', { name: 'Restore Contract plan' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('previous status was not recorded');
    expect(dialog).toHaveTextContent('restored as a draft');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Restore' }));
    await waitFor(() => expect(useToastStore.getState().toasts[0]?.message).toMatch(/previous status was not recorded/));
  });

  it('shows an error without reporting success or changing screens', async () => {
    vi.mocked(scheduleApi.archiveSchedule).mockRejectedValue(new ApiError(403, 'Forbidden', { detail: 'Denied' }));
    const { onChanged } = view();
    fireEvent.click(screen.getByRole('button', { name: 'Archive Contract plan' }));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Archive' }));
    await waitFor(() => expect(useToastStore.getState().toasts[0]?.type).toBe('error'));
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Archive Contract plan' })).not.toBeDisabled();
  });
});

describe('permanent deletion is a separate administrator action', () => {
  it.each(['editor', 'manager', 'viewer'])('never offers purge to %s', (role) => {
    useAuthStore.setState({ userRole: role });
    view({ status: 'archived' });
    expect(screen.queryByRole('button', { name: /Permanently delete/ })).toBeNull();
    if (role === 'viewer') expect(screen.queryByRole('button', { name: /Restore/ })).toBeNull();
  });

  it('does not offer an administrator purge on a non-archived schedule', () => {
    useAuthStore.setState({ userRole: 'admin' });
    view();
    expect(screen.queryByRole('button', { name: /Permanently delete/ })).toBeNull();
  });

  it('checks impact and requires confirmation before purge', async () => {
    useAuthStore.setState({ userRole: 'admin' });
    const { onChanged } = view({ status: 'archived' });
    fireEvent.click(screen.getByRole('button', { name: 'Permanently delete Contract plan' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(scheduleApi.getDeleteImpact).toHaveBeenCalledExactlyOnceWith('s1');
    expect(dialog).toHaveTextContent('3 activities');
    expect(dialog).toHaveTextContent('2 baselines');
    expect(dialog).toHaveTextContent('1 contract payment instalments');
    expect(scheduleApi.purgeSchedule).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete permanently' }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
    expect(scheduleApi.purgeSchedule).toHaveBeenCalledExactlyOnceWith('s1');
    expect(scheduleApi.archiveSchedule).not.toHaveBeenCalled();
  });

  it('honours server refusal even if the UI role says admin', async () => {
    useAuthStore.setState({ userRole: 'admin' });
    vi.mocked(scheduleApi.getDeleteImpact).mockResolvedValue({ activity_count: 3, can_delete: false,
      blocked_reason: 'schedule_not_archived' });
    view({ status: 'archived' });
    fireEvent.click(screen.getByRole('button', { name: 'Permanently delete Contract plan' }));
    await waitFor(() => expect(useToastStore.getState().toasts[0]?.message).toMatch(/Archive the schedule before/));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(scheduleApi.purgeSchedule).not.toHaveBeenCalled();
  });
});
