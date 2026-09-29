// @ts-nocheck
/**
 * Task assignee: picked from contacts (every role) or users (managers), or typed.
 */
import { useState } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/features/contacts/api', () => ({ fetchContacts: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn() };
});

import { fetchContacts } from '@/features/contacts/api';
import { apiGet } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { AssigneePicker } from './AssigneePicker';
import { assigneeFields } from '@/features/tasks/assignee';

let last;
function Harness() {
  const [value, setValue] = useState({ name: '', userId: '', contactId: '' });
  last = value;
  return <AssigneePicker value={value} onChange={setValue} inputClassName="" />;
}

function renderPicker() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
}

describe('AssigneePicker', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchContacts as any).mockResolvedValue({
      items: [{ id: 'k1', first_name: 'Ana', last_name: 'Lopez', company_name: 'Site Crew GmbH', primary_email: null }],
      total: 1,
    });
    (apiGet as any).mockResolvedValue([{ id: 'u1', email: 'max@example.com', full_name: 'Max Manager' }]);
  });

  it('offers contacts to an editor without asking for the users list', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    renderPicker();
    fireEvent.focus(screen.getByTestId('task-assignee-input'));
    const option = await screen.findByTestId('task-assignee-option-contact-k1');
    expect(apiGet).not.toHaveBeenCalled();

    fireEvent.click(option);
    expect(last).toEqual({ name: 'Ana Lopez', userId: '', contactId: 'k1' });
    // A contact goes by id; the server links its user, if any, and its name.
    expect(assigneeFields({ assigned_to: last.name, assignee_user_id: '', assignee_contact_id: 'k1' })).toEqual({
      assignee_contact_id: 'k1',
    });
  });

  it('offers users next to contacts to a manager', async () => {
    useAuthStore.setState({ userRole: 'manager' });
    renderPicker();
    fireEvent.focus(screen.getByTestId('task-assignee-input'));
    fireEvent.click(await screen.findByTestId('task-assignee-option-user-u1'));
    expect(last).toEqual({ name: 'Max Manager', userId: 'u1', contactId: '' });
  });

  it('turns a pick back into a typed name when the text is edited', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderPicker();
    const input = screen.getByTestId('task-assignee-input');
    fireEvent.focus(input);
    fireEvent.click(await screen.findByTestId('task-assignee-option-contact-k1'));
    fireEvent.change(input, { target: { value: 'Ana L.' } });
    await waitFor(() => expect(last).toEqual({ name: 'Ana L.', userId: '', contactId: '' }));
  });
});

describe('assigneeFields', () => {
  it('links a user and clears the contact link and the typed name', () => {
    expect(assigneeFields({ assigned_to: 'Max', assignee_user_id: 'u1', assignee_contact_id: '' })).toEqual({
      responsible_id: 'u1',
      assignee_contact_id: null,
      metadata: { assignee_name: null },
    });
  });

  it('keeps a typed name as a name, and clears everything when emptied', () => {
    expect(assigneeFields({ assigned_to: ' John ', assignee_user_id: '', assignee_contact_id: '' })).toEqual({
      responsible_id: null,
      assignee_contact_id: null,
      metadata: { assignee_name: 'John' },
    });
    expect(assigneeFields({ assigned_to: '', assignee_user_id: '', assignee_contact_id: '' })).toEqual({
      responsible_id: null,
      assignee_contact_id: null,
      metadata: { assignee_name: null },
    });
  });
});

describe('AssigneePicker search', () => {
  it('finds a contact past the first page through the contacts search', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    (fetchContacts as any).mockResolvedValue({ items: [], total: 500 });
    (apiGet as any).mockImplementation(async (url: string) =>
      url.startsWith('/v1/contacts/search/')
        ? { items: [{ id: 'k9', first_name: 'Zoe', last_name: 'Late', company_name: null, primary_email: null }], total: 1 }
        : [],
    );
    renderPicker();
    const input = screen.getByTestId('task-assignee-input');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'Zoe' } });
    fireEvent.click(await screen.findByTestId('task-assignee-option-contact-k9'));
    expect(last).toEqual({ name: 'Zoe Late', userId: '', contactId: 'k9' });
    expect((apiGet as any).mock.calls.some(([u]) => String(u).startsWith('/v1/users/'))).toBe(false);
  });
});
