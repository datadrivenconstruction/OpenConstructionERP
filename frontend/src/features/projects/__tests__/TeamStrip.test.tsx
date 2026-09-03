// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Vitest component tests for the TeamStrip.
 *
 * The component renders avatar circles for up to 6 members and a
 * "+N more" chip after that, plus an "Add member" button that opens a
 * modal. These tests cover the four explicit cases in the spec:
 *
 *   1. empty members → "No members yet" placeholder rendered
 *   2. 3 members → exactly 3 avatars, no overflow chip
 *   3. 8 members → 6 avatars + "+2 more" chip
 *   4. clicking "+" opens the Add Member modal
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TeamStrip, type ProjectMember, getInitials } from '../components/TeamStrip';
import { ASSIGNABLE_PROJECT_ROLES } from '../components/projectRoles';

// Avoid hitting the network — the TeamStrip's useQuery is short-circuited
// when `initialMembers` is passed via props (see component source).
const apiPatch = vi.fn();
const apiDelete = vi.fn();

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: (path: string, body: unknown) => apiPatch(path, body),
  apiDelete: (path: string) => apiDelete(path),
}));

// UserSearchInput hits /v1/users/ via React Query — stub it out so the
// Add-Member modal renders without firing a real request.
vi.mock('@/shared/ui/UserSearchInput', () => ({
  UserSearchInput: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (id: string, name: string) => void;
  }) => (
    <input
      data-testid="mock-user-search"
      value={value}
      onChange={(e) => onChange(e.target.value, e.target.value)}
    />
  ),
}));

function makeMember(i: number): ProjectMember {
  return {
    user_id: `user-${i}`,
    email: `user${i}@example.com`,
    full_name: `User ${i} Lastname`,
    role: i === 0 ? 'owner' : 'estimator',
    is_owner: i === 0,
  };
}

function renderStrip(members: ProjectMember[], canManage = true) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TeamStrip
        projectId="proj-test-1"
        canManage={canManage}
        initialMembers={members}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('TeamStrip', () => {
  describe('getInitials helper', () => {
    it('returns two-letter uppercase initials from first+last name', () => {
      expect(
        getInitials({ full_name: 'Jane Doe', email: 'jd@example.com' }),
      ).toBe('JD');
    });

    it('falls back to first two letters of single-word name', () => {
      expect(
        getInitials({ full_name: 'Madonna', email: 'm@example.com' }),
      ).toBe('MA');
    });

    it('falls back to email local part when name is empty', () => {
      expect(
        getInitials({ full_name: '', email: 'art@datadriven.io' }),
      ).toBe('AR');
    });

    it('returns ? when both name and email are empty', () => {
      expect(getInitials({ full_name: '', email: '' })).toBe('?');
    });
  });

  it('renders the empty placeholder when no members exist', () => {
    renderStrip([]);
    expect(screen.getByTestId('team-strip-empty')).toBeInTheDocument();
    expect(screen.queryAllByTestId('team-strip-avatar')).toHaveLength(0);
    // The + button is still rendered so the owner can invite the first
    // member — the spec wires it to the add-member modal.
    expect(screen.getByTestId('team-strip-add-button')).toBeInTheDocument();
  });

  it('renders exactly 3 avatars when there are 3 members', () => {
    const members = [0, 1, 2].map(makeMember);
    renderStrip(members);
    expect(screen.getAllByTestId('team-strip-avatar')).toHaveLength(3);
    // No overflow chip below the 7-member threshold.
    expect(screen.queryByTestId('team-strip-more')).toBeNull();
  });

  it('renders 6 avatars + "+2 more" chip when there are 8 members', () => {
    const members = Array.from({ length: 8 }, (_, i) => makeMember(i));
    renderStrip(members);
    expect(screen.getAllByTestId('team-strip-avatar')).toHaveLength(6);
    const moreChip = screen.getByTestId('team-strip-more');
    expect(moreChip).toBeInTheDocument();
    expect(moreChip.textContent).toMatch(/\+2/);
  });

  it('opens the Add Member modal when the "+" button is clicked', () => {
    renderStrip([makeMember(0)]);
    // Modal isn't mounted initially.
    expect(screen.queryByTestId('team-strip-add-modal')).toBeNull();
    fireEvent.click(screen.getByTestId('team-strip-add-button'));
    // Modal becomes visible with the role selector + user search.
    expect(screen.getByTestId('team-strip-add-modal')).toBeInTheDocument();
    expect(screen.getByTestId('mock-user-search')).toBeInTheDocument();
    expect(screen.getByTestId('team-strip-add-submit')).toBeInTheDocument();
  });

  it('hides the add controls when canManage is false', () => {
    renderStrip([makeMember(0), makeMember(1)], false);
    expect(screen.queryByTestId('team-strip-add-button')).toBeNull();
    expect(screen.queryByTestId('team-strip-manage')).toBeNull();
    // Avatars still render in read-only mode.
    expect(screen.getAllByTestId('team-strip-avatar')).toHaveLength(2);
  });

  /* ── Widened role list ─────────────────────────────────────────────── */

  describe('role picker', () => {
    function openAddModal() {
      renderStrip([makeMember(0)]);
      fireEvent.click(screen.getByTestId('team-strip-add-button'));
      return screen.getByTestId('team-strip-role-select') as HTMLSelectElement;
    }

    it('is grouped into optgroups, not a flat list', () => {
      const select = openAddModal();
      const groups = Array.from(select.querySelectorAll('optgroup')).map(
        (g) => g.label,
      );
      expect(groups).toEqual([
        'Project',
        'Engineering',
        'Workshop & site',
        'Commercial',
        'External',
      ]);
    });

    it('offers every assignable role from the shared list', () => {
      const select = openAddModal();
      const values = Array.from(select.querySelectorAll('option')).map(
        (o) => o.value,
      );
      expect(values).toEqual(ASSIGNABLE_PROJECT_ROLES.map((r) => r.key));
      // A few of the new ones, spelled out so a silent truncation fails here.
      expect(values).toContain('site_supervisor');
      expect(values).toContain('automation_engineer');
      expect(values).toContain('apprentice');
      expect(values).toContain('contracts_admin');
      expect(values).toContain('client_contact');
      // `owner` is derived from project ownership, never handed out.
      expect(values).not.toContain('owner');
    });

    it('labels roles readably rather than printing the wire key', () => {
      const select = openAddModal();
      const labels = Array.from(select.querySelectorAll('option')).map(
        (o) => o.textContent,
      );
      expect(labels).toContain('Automation engineer');
      expect(labels).toContain('Site supervisor');
      expect(labels).not.toContain('automation_engineer');
    });
  });

  /* ── Managing an existing member ───────────────────────────────────── */

  describe('member management', () => {
    function openManageModal(members: ProjectMember[]) {
      renderStrip(members);
      fireEvent.click(screen.getByTestId('team-strip-manage'));
    }

    it('prints the role label, not the raw key, in the member list', () => {
      const member = { ...makeMember(1), role: 'automation_engineer' };
      openManageModal([makeMember(0), member]);
      const rows = screen.getAllByTestId('team-strip-member-row');
      const row = rows.find((r) => r.textContent?.includes('user1@example.com'))!;
      expect(row.textContent).toContain('Automation engineer');
      expect(row.textContent).not.toContain('automation_engineer');
    });

    it('PATCHes the new role when an existing member is re-assigned', async () => {
      apiPatch.mockResolvedValue({});
      openManageModal([makeMember(0), makeMember(1)]);
      const picker = screen.getAllByTestId('team-strip-role-picker')[0]!;
      fireEvent.change(picker, { target: { value: 'workshop_lead' } });
      await waitFor(() =>
        expect(apiPatch).toHaveBeenCalledWith(
          '/v1/projects/proj-test-1/members/user-1/',
          { role: 'workshop_lead' },
        ),
      );
    });

    it('gives the owner no role picker and no remove button', () => {
      openManageModal([makeMember(0), makeMember(1)]);
      // Two members, but only the non-owner gets the controls.
      expect(screen.getAllByTestId('team-strip-role-picker')).toHaveLength(1);
      expect(screen.getAllByTestId('team-strip-remove-btn')).toHaveLength(1);
    });

    it('removes a member through the DELETE endpoint', async () => {
      apiDelete.mockResolvedValue(undefined);
      openManageModal([makeMember(0), makeMember(1)]);
      fireEvent.click(screen.getByTestId('team-strip-remove-btn'));
      await waitFor(() =>
        expect(apiDelete).toHaveBeenCalledWith(
          '/v1/projects/proj-test-1/members/user-1/',
        ),
      );
    });

    it('surfaces the backend detail when a role change is refused', async () => {
      apiPatch.mockRejectedValue({
        body: { detail: 'Cannot change the project owner’s role.' },
      });
      openManageModal([makeMember(0), makeMember(1)]);
      fireEvent.change(screen.getAllByTestId('team-strip-role-picker')[0]!, {
        target: { value: 'hse' },
      });
      expect(
        await screen.findByTestId('team-strip-manage-error'),
      ).toHaveTextContent('Cannot change the project owner');
    });
  });
});
