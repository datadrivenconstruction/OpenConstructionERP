// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the design screens share: what every panel is handed, the
// colour of each state, a section heading with its one action, a plain table
// and the three states a list can be in before it has rows.

import { createContext, useContext, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button, type ButtonProps } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { getErrorMessage } from '@/shared/lib/api';

import type {
  ApprovalPointState,
  CdeState,
  CommentSeverity,
  CommentState,
  Deliverable,
  DeliverableState,
  DesignRole,
  DesignSetup,
  Drawing,
  Flag,
  PermitState,
  ReleaseState,
  ReportState,
  ReviewState,
  RoleState,
  WbsNode,
} from './api';
import type { FieldOption, FieldSpec } from './FormDialog';
import { errorText, phaseName, ui, type LabelContext, type TFn } from './labels';
import { applies } from './rules';
import type { UiKey } from './text';

/**
 * What the signed-in role may be offered. The server still refuses; this keeps
 * a viewer from being shown add, edit, delete and approve buttons that would
 * end in a refusal. `edit` is the editor level, `manage` the manager level.
 */
export const DesignAccessContext = createContext<{ canEdit: boolean; canManage: boolean }>({ canEdit: true, canManage: true });

/** A button that writes. It is absent for a role below the level the API asks for. */
export function WriteButton({ need = 'edit', ...rest }: ButtonProps & { need?: 'edit' | 'manage' }) {
  const access = useContext(DesignAccessContext);
  if (!(need === 'manage' ? access.canManage : access.canEdit)) return null;
  return <Button {...rest} />;
}

/** What the page loads once and every panel reads. */
export interface DesignContext {
  projectId: string;
  setup: DesignSetup;
  labels: LabelContext;
  roles: DesignRole[];
  wbs: WbsNode[];
  deliverables: Deliverable[];
  drawings: Drawing[];
  personName: (userId: string | null | undefined) => string | null;
  /** Refetch every list of the project after a write. */
  onChanged: () => void;
}

export function roleOptions(ctx: DesignContext): FieldOption[] {
  return ctx.roles.map((r) => ({ value: r.id, label: r.title || r.code }));
}

export function phaseOptions(ctx: DesignContext): FieldOption[] {
  return ctx.setup.phases.map((p) => ({ value: p.code, label: phaseName(ctx.labels, ctx.setup.phases, p.code) }));
}

/**
 * The phase of a record. With a phase model it is one of the model's phases
 * and `required` decides whether the form insists on it. Without one there is
 * nothing to choose from: the field is plain optional text and says why.
 */
export function phaseField(ctx: DesignContext, t: TFn, required = false): FieldSpec {
  const label = ui(t, 'design.ui.field.phase');
  if (ctx.setup.phases.length > 0) return { name: 'phase_code', label, type: 'select', required, options: phaseOptions(ctx) };
  const hint = ctx.setup.gates_in_use === false ? 'design.ui.field.phase_no_gates' : 'design.ui.field.phase_free_hint';
  return { name: 'phase_code', label, type: 'text', hint: ui(t, hint) };
}

export function wbsOptions(ctx: DesignContext): FieldOption[] {
  return ctx.wbs.filter((n) => !n.closed).map((n) => ({ value: n.id, label: n.name ? `${n.code} ${n.name}` : n.code }));
}

export function deliverableOptions(ctx: DesignContext): FieldOption[] {
  return ctx.deliverables.map((d) => ({ value: d.id, label: d.title ? `${d.code} ${d.title}` : d.code }));
}

export function roleTitle(ctx: DesignContext, roleId: string | null | undefined): string {
  if (!roleId) return '';
  const role = ctx.roles.find((r) => r.id === roleId);
  return role ? role.title || role.code : '';
}

/** The suitability codes of the CDE, offered as they are written on a drawing. */
export const SUITABILITY_CODES = ['S0', 'S1', 'S2', 'S3', 'S4', 'S6', 'S7', 'A1', 'A2', 'A3', 'A4', 'A5'] as const;

export const SUITABILITY_OPTIONS: FieldOption[] = SUITABILITY_CODES.map((code) => ({ value: code, label: code }));

export const CDE_TONE: Record<CdeState, BadgeVariant> = {
  wip: 'neutral',
  shared: 'blue',
  published: 'success',
  archived: 'neutral',
};

export const ROLE_TONE: Record<RoleState, BadgeVariant> = {
  planned: 'neutral',
  appointed: 'blue',
  active: 'success',
  released: 'neutral',
};

export const APPROVAL_TONE: Record<ApprovalPointState, BadgeVariant> = {
  open: 'neutral',
  in_review: 'purple',
  approved: 'success',
  rejected: 'error',
};

export const DELIVERABLE_TONE: Record<DeliverableState, BadgeVariant> = {
  not_started: 'neutral',
  in_progress: 'blue',
  issued_for_review: 'purple',
  accepted: 'success',
  waived: 'neutral',
};

export const RELEASE_TONE: Record<ReleaseState, BadgeVariant> = {
  draft: 'neutral',
  ready: 'blue',
  issued: 'success',
  cancelled: 'neutral',
};

export const REVIEW_TONE: Record<ReviewState, BadgeVariant> = {
  planned: 'neutral',
  open: 'blue',
  comments_closed: 'purple',
  concluded: 'success',
};

export const COMMENT_TONE: Record<CommentState, BadgeVariant> = {
  open: 'warning',
  answered: 'blue',
  closed: 'success',
  rejected: 'neutral',
};

export const SEVERITY_TONE: Record<CommentSeverity, BadgeVariant> = {
  minor: 'neutral',
  major: 'warning',
  critical: 'error',
};

export const REPORT_TONE: Record<ReportState, BadgeVariant> = {
  required: 'warning',
  commissioned: 'blue',
  in_progress: 'blue',
  submitted: 'purple',
  under_check: 'purple',
  remarks: 'warning',
  accepted: 'success',
  rejected: 'error',
  not_required: 'neutral',
};

export const PERMIT_TONE: Record<PermitState, BadgeVariant> = {
  assembling: 'neutral',
  ready: 'blue',
  submitted: 'purple',
  under_review: 'purple',
  remarks: 'warning',
  approved: 'success',
  partially_approved: 'warning',
  refused: 'error',
  withdrawn: 'neutral',
};

export function ToneBadge({ tone, children, testId }: { tone: BadgeVariant; children: ReactNode; testId?: string }) {
  return (
    <span data-testid={testId}>
      <Badge variant={tone} size="sm">
        {children}
      </Badge>
    </span>
  );
}

/**
 * A button for an action the server offers. It is left out when the action
 * does not exist for the row, and greyed out with the server's reason as its
 * tooltip when this user may not take it.
 */
export function StepButton({
  flag,
  label,
  onClick,
  busy = false,
  variant = 'ghost',
  testId,
}: {
  flag: Flag | null | undefined;
  label: string;
  onClick: () => void;
  busy?: boolean;
  variant?: 'ghost' | 'secondary';
  testId?: string;
}) {
  const { t } = useTranslation();
  if (!applies(flag)) return null;
  const reason = !flag.allowed && flag.reason ? errorText(t as TFn, flag.reason) : undefined;
  return (
    <span className="inline-flex items-center gap-1" title={reason}>
      <Button size="sm" variant={variant} disabled={busy || !flag.allowed} onClick={onClick} data-testid={testId}>
        {label}
      </Button>
      {reason && (
        <span className="text-xs text-content-tertiary" data-testid={testId ? `${testId}-reason` : undefined}>
          {reason}
        </span>
      )}
    </span>
  );
}

/**
 * The loading line or the retry notice of a small query inside a panel (a
 * comment list, a catalogue, a preview). Nothing when the query has settled.
 */
export function InlineQueryState({
  query,
  failedKey = 'design.ui.load_failed',
}: {
  query: { isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown };
  failedKey?: UiKey;
}) {
  const { t } = useTranslation();
  if (query.isLoading) {
    return (
      <p className="text-sm text-content-tertiary" role="status" data-testid="inline-loading">
        {ui(t as TFn, 'design.ui.loading')}
      </p>
    );
  }
  if (query.isError) {
    return <ErrorState compact title={ui(t as TFn, failedKey)} hint={getErrorMessage(query.error)} onRetry={() => query.refetch()} />;
  }
  return null;
}

/** One optional select fed by another module; no field when that source has nothing to offer. */
export function pickerField(name: string, label: string, options: FieldOption[] | null): FieldSpec[] {
  return options ? [{ name, label, type: 'select', options }] : [];
}

/** A section heading: what the list is, one sentence on what it is for, and its one action. */
export function PanelHeader({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-base font-semibold text-content-primary">{title}</h2>
        {hint && <p className="text-sm text-content-secondary">{hint}</p>}
      </div>
      {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
    </div>
  );
}

export function Table({ head, children, testId }: { head: string[]; children: ReactNode; testId?: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border-light">
      <table className="w-full text-sm" data-testid={testId}>
        <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
          <tr>
            {head.map((h, i) => (
              <th key={`${h}-${i}`} scope="col" className="px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light">{children}</tbody>
      </table>
    </div>
  );
}

export const CELL = 'px-3 py-2 align-top text-content-primary';
export const CELL_MUTED = 'px-3 py-2 align-top text-content-secondary';

/**
 * The states of a list before it has rows: still loading, failed, or empty.
 * Returns null when the list has rows, so a panel writes
 * `listState(...) ?? <the table>`.
 */
export function ListState({
  query,
  failedKey,
  emptyIcon,
  emptyTitle,
  emptyBody,
  emptyAction,
}: {
  query: { isLoading: boolean; isError: boolean; error: unknown; refetch: () => unknown; data?: unknown[] };
  failedKey: UiKey;
  emptyIcon: ReactNode;
  emptyTitle: string;
  emptyBody: string;
  emptyAction?: { label: string; onClick: () => void };
}) {
  const { t } = useTranslation();
  const { canEdit } = useContext(DesignAccessContext);
  if (query.isLoading) return <SkeletonTable rows={4} columns={5} />;
  if (query.isError) {
    return <ErrorState title={ui(t as TFn, failedKey)} hint={getErrorMessage(query.error)} onRetry={() => query.refetch()} />;
  }
  if ((query.data ?? []).length === 0) {
    return <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyBody} action={canEdit ? emptyAction : undefined} />;
  }
  return null;
}

/** Whether a list is still loading, failed or empty, so a panel knows not to draw its table. */
export function hasRows(query: { isLoading: boolean; isError: boolean; data?: unknown[] }): boolean {
  return !query.isLoading && !query.isError && (query.data ?? []).length > 0;
}
