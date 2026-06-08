// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ApprovalTimeline — vertical construction-management-platform-style approval-chain renderer.
 *
 * Renders one node per step with:
 *   - circular avatar (status colour: amber/green/red)
 *   - approver id snippet (full UUID truncated to first 8 chars)
 *   - decision chip (pending / approved / rejected)
 *   - decided-at timestamp + free-text comment
 *
 * If the caller passes ``onDecide`` and ``currentUserId`` matches the
 * active step's approver_user_id, the timeline also exposes an
 * "Approve" / "Reject" action row at the bottom with an optional
 * comment textarea.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CheckCircle2,
  XCircle,
  Clock,
  User as UserIcon,
} from 'lucide-react';
import { Badge, Button, Card } from '@/shared/ui';
import { getIntlLocale } from '@/shared/lib/formatters';
import type { ApprovalRow } from './api';

interface ApprovalTimelineProps {
  /** Rows already sorted by ``step_order`` (the API returns them that way). */
  rows: ApprovalRow[];
  /** Cursor pointing at the active step (1-indexed) or ``null`` when no
   *  chain is in flight. */
  currentApprovalStep: number | null;
  /** Authenticated user's id; matched against the active step's approver. */
  currentUserId: string | null;
  /** Resolved approver id -> display name. When an id is missing from the
   *  map (directory unavailable / deleted user) the timeline falls back to a
   *  short id snippet. */
  approverNames?: Record<string, string>;
  /** Caller hook for the decision call; receives the chosen decision and
   *  an optional comment. Omit to render the timeline read-only. */
  onDecide?: (decision: 'approved' | 'rejected', comments: string) => void;
  /** Disable the action buttons while a parent mutation is pending. */
  busy?: boolean;
}

function formatTs(iso: string | null): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString(getIntlLocale(), {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function shortId(id: string | null): string {
  if (!id) return '—';
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

type Tone = 'pending' | 'approved' | 'rejected' | 'inactive';

interface NodeStyle {
  badge: 'neutral' | 'success' | 'error' | 'warning' | 'blue';
  ring: string;
  icon: typeof CheckCircle2;
}

function styleFor(row: ApprovalRow, isActive: boolean): { tone: Tone; style: NodeStyle } {
  if (row.decision === 'approved') {
    return {
      tone: 'approved',
      style: {
        badge: 'success',
        ring: 'border-semantic-success bg-semantic-success/10 text-semantic-success',
        icon: CheckCircle2,
      },
    };
  }
  if (row.decision === 'rejected') {
    return {
      tone: 'rejected',
      style: {
        badge: 'error',
        ring: 'border-semantic-error bg-semantic-error/10 text-semantic-error',
        icon: XCircle,
      },
    };
  }
  if (isActive) {
    return {
      tone: 'pending',
      style: {
        badge: 'warning',
        ring: 'border-amber-500 bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
        icon: Clock,
      },
    };
  }
  return {
    tone: 'inactive',
    style: {
      badge: 'neutral',
      ring: 'border-border bg-surface-secondary text-content-tertiary',
      icon: UserIcon,
    },
  };
}

export function ApprovalTimeline({
  rows,
  currentApprovalStep,
  currentUserId,
  approverNames = {},
  onDecide,
  busy = false,
}: ApprovalTimelineProps): JSX.Element {
  const { t } = useTranslation();
  const [comment, setComment] = useState('');

  // Prefer a resolved display name; fall back to a short id snippet.
  const approverDisplay = (id: string | null): string => {
    if (!id) return '—';
    return approverNames[id] || shortId(id);
  };

  // Active row = the one at the cursor. Memoised so a re-render of the
  // comment textarea doesn't re-scan the list.
  const activeRow = useMemo(() => {
    if (currentApprovalStep == null) return null;
    return rows.find((r) => r.step_order === currentApprovalStep) ?? null;
  }, [rows, currentApprovalStep]);

  const canDecide =
    !!onDecide &&
    !!activeRow &&
    activeRow.decision === 'pending' &&
    !!currentUserId &&
    activeRow.approver_user_id === currentUserId;

  if (rows.length === 0) {
    return (
      <Card className="p-6 text-center">
        <p className="text-sm text-content-tertiary">
          {t('changeorders.approval_chain_empty', {
            defaultValue: 'No approval chain has been started for this change order yet.',
          })}
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <ol className="relative space-y-4 border-l-2 border-border pl-6">
        {rows.map((row) => {
          const isActive = currentApprovalStep === row.step_order;
          const { style } = styleFor(row, isActive);
          const Icon = style.icon;
          return (
            <li
              key={row.id}
              className={`relative pl-2 ${isActive ? 'font-medium' : ''}`}
              aria-current={isActive ? 'step' : undefined}
            >
              {/* Node bullet */}
              <span
                className={`absolute -left-[34px] top-0 flex h-7 w-7 items-center justify-center rounded-full border-2 ${style.ring}`}
                aria-hidden="true"
              >
                <Icon size={14} strokeWidth={2} />
              </span>

              <Card className="p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm">
                      <span className="font-medium text-content-primary">
                        {t('changeorders.approval_step_label', {
                          defaultValue: 'Step {{n}}',
                          n: row.step_order,
                        })}
                      </span>
                      <Badge variant={style.badge}>
                        {t(`changeorders.approval_decision_${row.decision}`, {
                          defaultValue:
                            row.decision === 'approved'
                              ? 'Approved'
                              : row.decision === 'rejected'
                              ? 'Rejected'
                              : 'Pending',
                        })}
                      </Badge>
                      {isActive && row.decision === 'pending' && (
                        <Badge variant="blue">
                          {t('changeorders.approval_active', {
                            defaultValue: 'Active',
                          })}
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-content-secondary">
                      {t('changeorders.approval_approver_label', {
                        defaultValue: 'Approver',
                      })}
                      :{' '}
                      <span className="font-medium text-content-primary">
                        {approverDisplay(row.approver_user_id)}
                      </span>
                      {row.approver_user_id &&
                        currentUserId &&
                        row.approver_user_id === currentUserId && (
                          <span className="ml-1 text-content-tertiary">
                            ({t('changeorders.approval_you', { defaultValue: 'you' })})
                          </span>
                        )}
                    </p>
                    {row.decided_at && (
                      <p className="mt-0.5 text-xs text-content-tertiary">
                        {formatTs(row.decided_at)}
                      </p>
                    )}
                    {row.comments && (
                      <p className="mt-2 whitespace-pre-wrap text-xs text-content-secondary">
                        {row.comments}
                      </p>
                    )}
                  </div>
                </div>
              </Card>
            </li>
          );
        })}
      </ol>

      {canDecide && (
        <Card className="p-4">
          <label
            htmlFor="approval-comment"
            className="block text-xs font-medium uppercase tracking-wide text-content-tertiary"
          >
            {t('changeorders.approval_comment_label', {
              defaultValue: 'Comment (optional)',
            })}
          </label>
          <textarea
            id="approval-comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
            maxLength={2000}
            disabled={busy}
            placeholder={t('changeorders.approval_comment_placeholder', {
              defaultValue: 'Add a note for the audit trail…',
            })}
            className="mt-1 w-full rounded-lg border border-border bg-surface-primary p-2 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
          <div className="mt-3 flex justify-end gap-2">
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => onDecide?.('rejected', comment)}
            >
              <XCircle size={14} className="mr-1.5" />
              {t('changeorders.approval_reject', { defaultValue: 'Reject' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={busy}
              onClick={() => onDecide?.('approved', comment)}
            >
              <CheckCircle2 size={14} className="mr-1.5" />
              {t('changeorders.approval_approve', { defaultValue: 'Approve' })}
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}
