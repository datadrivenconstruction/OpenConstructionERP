// @ts-nocheck
/**
 * Task assignee: picked from contacts (every role) or users (managers), or typed.
 */
import { useState } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn() };
});

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
    (apiGet as any).mockImplementation(async (url: string) =>
      url.startsWith('/v1/contacts/pickable/')
        ? {
            team: [{ id: 't1', first_name: 'Tom', last_name: 'Team', company_name: null, primary_email: null }],
            company: [
              { id: 'k1', first_name: 'Ana', last_name: 'Lopez', company_name: 'Site Crew GmbH', primary_email: null },
            ],
          }
        : [{ id: 'u1', email: 'max@example.com', full_name: 'Max Manager' }],
    );
  });

  it('offers contacts to an editor without asking for the users list', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    renderPicker();
    fireEvent.focus(screen.getByTestId('task-assignee-input'));
    const option = await screen.findByTestId('task-assignee-option-contact-k1');
    expect(apiGet).not.toHaveBeenCalledWith(expect.stringContaining('/v1/users/'));

    fireEvent.click(option);
    expect(last).toEqual({ name: 'Ana Lopez', userId: '', contactId: 'k1' });
    // A contact goes by id; the server links its user, if any, and its name.
    expect(assigneeFields({ assigned_to: last.name, assignee_user_id: '', assignee_contact_id: 'k1' })).toEqual({
      assignee_contact_id: 'k1',
    });
  });

  it('lists the project team before the company contacts, each under its heading', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    renderPicker();
    fireEvent.focus(screen.getByTestId('task-assignee-input'));
    await screen.findByTestId('task-assignee-option-contact-k1');
    const ids = screen.getAllByRole('option').map((o) => o.getAttribute('data-testid'));
    expect(ids).toEqual(['task-assignee-option-contact-t1', 'task-assignee-option-contact-k1']);
    expect(screen.getByText('Project team')).toBeInTheDocument();
    expect(screen.getByText('Company contacts')).toBeInTheDocument();
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
  it('finds a contact past the first page by asking the server with the typed text', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    (apiGet as any).mockImplementation(async (url: string) =>
      url.startsWith('/v1/contacts/pickable/') && url.includes('q=Zoe')
        ? {
            team: [],
            company: [{ id: 'k9', first_name: 'Zoe', last_name: 'Late', company_name: null, primary_email: null }],
          }
        : { team: [], company: [] },
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
