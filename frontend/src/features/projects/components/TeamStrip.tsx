/**
 * TeamStrip — horizontal row of avatar circles for a project's members.
 *
 * Rendered on ProjectDetailPage above the tab bar (similar to modern project
 * collaboration tools). Shows up to 6 overlapping avatar circles with the
 * member's initials when no avatar URL is available; a tooltip on hover
 * surfaces the full name + role. After 6 members an aggregate "+N more"
 * chip is rendered which opens a modal listing every member. The trailing
 * "+" button opens an Add Member modal that uses the existing
 * `UserSearchInput` to find users plus a role selector
 * (estimator / viewer / project_manager).
 *
 * Data flow: backed by GET/POST/DELETE /api/v1/projects/{id}/members/.
 * Add/remove mutations invalidate the ['project-members', projectId] query
 * key so the strip auto-refreshes.
 */

import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, X, Trash2, UserPlus } from 'lucide-react';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { UserSearchInput } from '@/shared/ui/UserSearchInput';

// ── Types ──────────────────────────────────────────────────────────────────

export interface ProjectMember {
  user_id: string;
  email: string;
  full_name: string;
  role: string;
  is_owner: boolean;
  created_at?: string | null;
}

/**
 * Roles surfaced in the Add-Member modal. The backend accepts a wider
 * whitelist (see AddProjectMemberRequest); these are the user-facing labels.
 */
const ROLE_CHOICES: readonly string[] = [
  'estimator',
  'viewer',
  'project_manager',
] as const;

const MAX_VISIBLE_AVATARS = 6;

// ── Helpers ────────────────────────────────────────────────────────────────

/**
 * Pick up to two letters as initials. Falls back to the email prefix
 * when full_name is empty so we never render a blank circle.
 */
export function getInitials(member: Pick<ProjectMember, 'full_name' | 'email'>): string {
  const source = member.full_name?.trim() || member.email?.split('@')[0] || '';
  if (!source) return '?';
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length === 1) {
    return parts[0]!.slice(0, 2).toUpperCase();
  }
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

/**
 * Deterministic hue for the avatar background — same user always gets the
 * same colour. Hashing the email is stable across renders / sessions and
 * makes the strip visually distinguishable at a glance.
 */
function colourForUser(member: Pick<ProjectMember, 'user_id' | 'email'>): string {
  const seed = member.user_id || member.email || '';
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  }
  const hue = Math.abs(hash) % 360;
  // Saturation + lightness tuned to read on both light and dark themes.
  return `hsl(${hue} 55% 45%)`;
}

// ── Avatar primitive ───────────────────────────────────────────────────────

interface AvatarProps {
  member: ProjectMember;
  size?: number;
  className?: string;
}

function Avatar({ member, size = 32, className = '' }: AvatarProps) {
  return (
    <div
      role="img"
      aria-label={`${member.full_name || member.email} (${member.role})`}
      title={`${member.full_name || member.email} - ${member.role}`}
      className={`inline-flex items-center justify-center rounded-full border-2 border-white text-white font-semibold select-none ${className}`}
      style={{
        width: size,
        height: size,
        backgroundColor: colourForUser(member),
        fontSize: Math.max(10, Math.floor(size / 2.6)),
      }}
      data-testid="team-strip-avatar"
    >
      {getInitials(member)}
    </div>
  );
}

// ── Member list modal ──────────────────────────────────────────────────────

interface MemberListModalProps {
  members: ProjectMember[];
  onClose: () => void;
  onRemove: (userId: string) => void;
  canRemove: boolean;
}

function MemberListModal({
  members,
  onClose,
  onRemove,
  canRemove,
}: MemberListModalProps) {
  const { t } = useTranslation();
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('projects.team.modal_members_title', {
        defaultValue: 'Project members',
      })}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="bg-surface-primary rounded-xl shadow-xl w-full max-w-md max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border-light px-4 py-3">
          <h2 className="text-base font-semibold text-content-primary">
            {t('projects.team.modal_members_title', {
              defaultValue: 'Project members',
            })}
          </h2>
          <button
            onClick={onClose}
            className="text-content-tertiary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={18} />
          </button>
        </div>
        <ul className="overflow-y-auto divide-y divide-border-light">
          {members.map((m) => (
            <li
              key={m.user_id}
              className="flex items-center gap-3 px-4 py-2.5"
              data-testid="team-strip-member-row"
            >
              <Avatar member={m} size={32} />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-content-primary truncate">
                  {m.full_name || m.email}
                </div>
                <div className="text-xs text-content-tertiary truncate">
                  {m.email} · {m.role}
                  {m.is_owner ? (
                    <span className="ml-1 text-oe-blue">
                      ·{' '}
                      {t('projects.team.owner', { defaultValue: 'Owner' })}
                    </span>
                  ) : null}
                </div>
              </div>
              {canRemove && !m.is_owner && (
                <button
                  onClick={() => onRemove(m.user_id)}
                  className="text-content-tertiary hover:text-semantic-error transition-colors"
                  aria-label={t('projects.team.remove_member', {
                    defaultValue: 'Remove member',
                  })}
                  data-testid="team-strip-remove-btn"
                >
                  <Trash2 size={16} />
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ── Add member modal ───────────────────────────────────────────────────────

interface AddMemberModalProps {
  onClose: () => void;
  onSubmit: (userId: string, role: string) => void;
  isSubmitting: boolean;
  errorMessage?: string;
}

function AddMemberModal({
  onClose,
  onSubmit,
  isSubmitting,
  errorMessage,
}: AddMemberModalProps) {
  const { t } = useTranslation();
  const [userId, setUserId] = useState<string>('');
  const [displayName, setDisplayName] = useState<string>('');
  const [role, setRole] = useState<string>('estimator');

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!userId) return;
      onSubmit(userId, role);
    },
    [userId, role, onSubmit],
  );

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('projects.team.modal_add_title', {
        defaultValue: 'Add member',
      })}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
      data-testid="team-strip-add-modal"
    >
      <form
        className="bg-surface-primary rounded-xl shadow-xl w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
      >
        <div className="flex items-center justify-between border-b border-border-light px-4 py-3">
          <h2 className="text-base font-semibold text-content-primary">
            {t('projects.team.modal_add_title', {
              defaultValue: 'Add member',
            })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-content-tertiary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={18} />
          </button>
        </div>
        <div className="px-4 py-4 space-y-4">
          <div>
            <label className="block text-xs font-medium text-content-secondary mb-1.5">
              {t('projects.team.user_label', { defaultValue: 'User' })}
            </label>
            <UserSearchInput
              value={userId}
              displayValue={displayName}
              onChange={(id, name) => {
                setUserId(id);
                setDisplayName(name);
              }}
            />
          </div>
          <div>
            <label
              htmlFor="team-strip-role-select"
              className="block text-xs font-medium text-content-secondary mb-1.5"
            >
              {t('projects.team.role_label', { defaultValue: 'Role' })}
            </label>
            <select
              id="team-strip-role-select"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            >
              {ROLE_CHOICES.map((r) => (
                <option key={r} value={r}>
                  {t(`projects.team.role.${r}`, {
                    defaultValue:
                      r === 'project_manager'
                        ? 'Project manager'
                        : r.charAt(0).toUpperCase() + r.slice(1),
                  })}
                </option>
              ))}
            </select>
          </div>
          {errorMessage ? (
            <p
              className="text-xs text-semantic-error"
              role="alert"
              data-testid="team-strip-add-error"
            >
              {errorMessage}
            </p>
          ) : null}
        </div>
        <div className="border-t border-border-light px-4 py-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-lg text-content-secondary hover:bg-surface-secondary"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="submit"
            disabled={!userId || isSubmitting}
            className="px-3 py-1.5 text-sm rounded-lg bg-oe-blue text-white disabled:opacity-50 hover:bg-oe-blue/90"
            data-testid="team-strip-add-submit"
          >
            {isSubmitting
              ? t('common.adding', { defaultValue: 'Adding...' })
              : t('projects.team.add_member', { defaultValue: 'Add member' })}
          </button>
        </div>
      </form>
    </div>
  );
}

// ── Public component ───────────────────────────────────────────────────────

export interface TeamStripProps {
  projectId: string;
  /** When false, hide the add / remove controls (read-only mode for viewers). */
  canManage?: boolean;
  /** Optional pre-fetched members — bypasses the network query in tests. */
  initialMembers?: ProjectMember[];
}

export function TeamStrip({
  projectId,
  canManage = true,
  initialMembers,
}: TeamStripProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [listOpen, setListOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [addError, setAddError] = useState<string | undefined>();

  const { data: members = [], isLoading } = useQuery<ProjectMember[]>({
    queryKey: ['project-members', projectId],
    queryFn: () =>
      apiGet<ProjectMember[]>(`/v1/projects/${projectId}/members/`),
    enabled: !!projectId && initialMembers === undefined,
    initialData: initialMembers,
    staleTime: 30_000,
  });

  const addMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      apiPost<ProjectMember>(`/v1/projects/${projectId}/members/`, {
        user_id: userId,
        role,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['project-members', projectId],
      });
      setAddOpen(false);
      setAddError(undefined);
    },
    onError: (err: unknown) => {
      // ApiError carries the parsed JSON body; surface backend.detail.
      const detail =
        (err as { body?: { detail?: string } })?.body?.detail ??
        (err instanceof Error ? err.message : 'Failed to add member');
      setAddError(detail);
    },
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) =>
      apiDelete(`/v1/projects/${projectId}/members/${userId}/`),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['project-members', projectId],
      });
    },
  });

  const visible = useMemo(
    () => members.slice(0, MAX_VISIBLE_AVATARS),
    [members],
  );
  const overflowCount = Math.max(0, members.length - MAX_VISIBLE_AVATARS);

  // Empty + loading rendering paths kept compact so the strip never grows
  // taller than the tab bar that follows it.
  if (!projectId) return null;

  return (
    <>
      <div
        className="flex items-center gap-2"
        data-testid="team-strip"
        aria-label={t('projects.team.strip_label', {
          defaultValue: 'Project team',
        })}
      >
        <div className="flex -space-x-2">
          {isLoading && members.length === 0 ? (
            <div
              className="h-8 w-8 rounded-full bg-surface-secondary animate-pulse"
              aria-hidden="true"
            />
          ) : visible.length === 0 ? (
            <span
              className="text-xs text-content-tertiary italic"
              data-testid="team-strip-empty"
            >
              {t('projects.team.empty', {
                defaultValue: 'No members yet',
              })}
            </span>
          ) : (
            visible.map((m) => <Avatar key={m.user_id} member={m} />)
          )}
        </div>
        {overflowCount > 0 && (
          <button
            type="button"
            onClick={() => setListOpen(true)}
            className="inline-flex items-center justify-center h-8 px-2 rounded-full bg-surface-secondary text-xs font-semibold text-content-secondary border-2 border-white hover:bg-surface-tertiary transition-colors -ml-2"
            data-testid="team-strip-more"
            aria-label={t('projects.team.more_count', {
              count: overflowCount,
              defaultValue: '+{{count}} more',
            })}
          >
            +{overflowCount}{' '}
            {t('projects.team.more', { defaultValue: 'more' })}
          </button>
        )}
        {/* Render the manage shortcut even when the strip is empty so the
            owner can always invite the first member. */}
        {canManage && (
          <>
            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className="ml-1 inline-flex items-center justify-center h-8 w-8 rounded-full border border-dashed border-border text-content-tertiary hover:text-oe-blue hover:border-oe-blue transition-colors"
              data-testid="team-strip-add-button"
              aria-label={t('projects.team.add_member', {
                defaultValue: 'Add member',
              })}
              title={t('projects.team.add_member', {
                defaultValue: 'Add member',
              })}
            >
              <Plus size={16} />
            </button>
            {members.length > 0 && (
              <button
                type="button"
                onClick={() => setListOpen(true)}
                className="text-xs text-content-tertiary hover:text-content-primary inline-flex items-center gap-1"
                data-testid="team-strip-manage"
              >
                <UserPlus size={12} />
                {t('projects.team.manage', { defaultValue: 'Manage' })}
              </button>
            )}
          </>
        )}
      </div>

      {listOpen && (
        <MemberListModal
          members={members}
          onClose={() => setListOpen(false)}
          canRemove={canManage}
          onRemove={(userId) => removeMutation.mutate(userId)}
        />
      )}
      {addOpen && (
        <AddMemberModal
          onClose={() => {
            setAddOpen(false);
            setAddError(undefined);
          }}
          isSubmitting={addMutation.isPending}
          errorMessage={addError}
          onSubmit={(userId, role) => addMutation.mutate({ userId, role })}
        />
      )}
    </>
  );
}
