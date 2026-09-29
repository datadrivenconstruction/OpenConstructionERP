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
import { assigneeFields } from './assignee';

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
    expect(assigneeFields({ assigned_to: last.name, assignee_user_id: '', assignee_contact_id: 'k1' })).toEqual({
      responsible_id: null,
      metadata: { assignee_name: 'Ana Lopez', assignee_contact_id: 'k1' },
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
  it('links a user and clears both metadata keys', () => {
    expect(assigneeFields({ assigned_to: 'Max', assignee_user_id: 'u1', assignee_contact_id: '' })).toEqual({
      responsible_id: 'u1',
      metadata: { assignee_name: null, assignee_contact_id: null },
    });
  });

  it('keeps a typed name as a name, and clears everything when emptied', () => {
    expect(assigneeFields({ assigned_to: ' John ', assignee_user_id: '', assignee_contact_id: '' })).toEqual({
      responsible_id: null,
      metadata: { assignee_name: 'John', assignee_contact_id: null },
    });
    expect(assigneeFields({ assigned_to: '', assignee_user_id: '', assignee_contact_id: '' })).toEqual({
      responsible_id: null,
      metadata: { assignee_name: null, assignee_contact_id: null },
    });
  });
});
