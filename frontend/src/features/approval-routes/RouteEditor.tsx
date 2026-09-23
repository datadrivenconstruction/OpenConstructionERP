// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RouteEditor — modal form for creating or editing an approval route
// template. The route is a sequence of steps; each step pins an approver
// (role OR user, mutually exclusive), a decision mode, and an optional
// SLA.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Plus,
  Trash2,
  UserCog,
  ShieldCheck,
} from 'lucide-react';
import clsx from 'clsx';

import { Button, WideModal, WideModalSection } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { apiGet } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { approvalRoutesKeys, createRoute, getMeta, updateRoute } from './api';
import { kindLabel } from './labels';
import type {
  ApprovalRoute,
  ApprovalRouteCreatePayload,
  ApprovalRouteUpdatePayload,
  RouteStepMode,
  RouteStepPayload,
} from './types';

interface UserResult {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

interface ProjectResult {
  id: string;
  name: string;
}

/** Curated list — these mirror the role enum on the backend. Free text
 *  ``custom_*`` is still accepted at the API level for power users. */
const KNOWN_ROLES = [
  'admin',
  'manager',
  'estimator',
  'engineer',
  'foreman',
  'client',
  'subcontractor',
];

// Fallback whitelist used only until the /meta query resolves — kept in
// sync with backend models.TARGET_KINDS. The live list comes from the
// backend so the two can never drift.
const FALLBACK_TARGET_KINDS = [
  'markup',
  'submittal',
  'change_order',
  'rfi',
  'contract',
  'variation',
  'invoice',
  'purchase_order',
];

const MODE_OPTIONS: RouteStepMode[] = ['all', 'any', 'majority'];

/** Modes available for a role-pinned step. The engine cannot expand a
 *  role to its members, so ``all`` / ``majority`` would silently degrade
 *  to "first approval wins"; only ``any`` is enforceable for role steps.
 *  User-pinned steps are inherently single-approver so any mode behaves
 *  identically. */
const ROLE_STEP_MODES: RouteStepMode[] = ['any'];

export interface RouteEditorProps {
  open: boolean;
  onClose: () => void;
  /** Route to edit; pass ``null`` to create. */
  route: ApprovalRoute | null;
  /** Pre-fill the project_id when creating from a project-scoped page.
   *  Leave null for global routes. */
  defaultProjectId?: string | null;
  /** Pre-fill the target_kind when opened from a kind-filtered list. */
  defaultTargetKind?: string | null;
}

interface DraftStep {
  /** Stable local id so React reorders cleanly while editing. */
  localId: string;
  approver_role: string;
  approver_user_id: string;
  mode: RouteStepMode;
  sla_hours: string;
}

function newLocalId(): string {
  // Cryptographically random ids are overkill here; Date+counter is fine.
  return `step-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function toDraft(step: { approver_role: string | null; approver_user_id: string | null; mode: RouteStepMode; sla_hours: number | null }): DraftStep {
  return {
    localId: newLocalId(),
    approver_role: step.approver_role ?? '',
    approver_user_id: step.approver_user_id ?? '',
    mode: step.mode,
    sla_hours: step.sla_hours != null ? String(step.sla_hours) : '',
  };
}

/** Draft rows as the API wants them. Lives at module scope so an edit can run
 *  it a second time over the route as it was loaded and get the baseline to
 *  diff the step list against. */
function toStepPayloads(steps: DraftStep[]): RouteStepPayload[] {
  // 1-based dense ordinals — the backend rejects 0-based or gapped lists.
  return steps.map((s, idx) => {
    const isRoleStep = !s.approver_user_id.trim();
    // Role steps can only enforce ``any`` (the engine can't expand a
    // role to its members), so coerce any stale ``all``/``majority``.
    const mode: RouteStepMode = isRoleStep ? 'any' : s.mode;
    return {
      ordinal: idx + 1,
      approver_role: s.approver_role.trim() || null,
      approver_user_id: s.approver_user_id.trim() || null,
      mode,
      sla_hours: s.sla_hours ? parseInt(s.sla_hours, 10) : null,
    };
  });
}

function emptyDraftStep(): DraftStep {
  return {
    localId: newLocalId(),
    approver_role: 'manager',
    approver_user_id: '',
    mode: 'all',
    sla_hours: '',
  };
}

export function RouteEditor({
  open,
  onClose,
  route,
  defaultProjectId,
  defaultTargetKind,
}: RouteEditorProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const isEdit = route != null;

  const [name, setName] = useState('');
  const [projectId, setProjectId] = useState<string>('');
  const [targetKind, setTargetKind] = useState<string>('markup');
  const [isActive, setIsActive] = useState(true);
  const [steps, setSteps] = useState<DraftStep[]>([]);

  // Re-seed form whenever the modal opens or the route prop changes.
  useEffect(() => {
    if (!open) return;
    if (route) {
      setName(route.name);
      setProjectId(route.project_id ?? '');
      setTargetKind(route.target_kind);
      setIsActive(route.is_active);
      setSteps(
        [...route.steps]
          .sort((a, b) => a.ordinal - b.ordinal)
          .map(toDraft),
      );
    } else {
      setName('');
      setProjectId(defaultProjectId ?? '');
      setTargetKind(defaultTargetKind ?? 'markup');
      setIsActive(true);
      setSteps([emptyDraftStep()]);
    }
  }, [open, route, defaultProjectId, defaultTargetKind]);

  // Target kinds from the backend whitelist (single source of truth).
  const { data: meta } = useQuery({
    queryKey: approvalRoutesKeys.meta(),
    queryFn: () => getMeta(),
    staleTime: 10 * 60_000,
    enabled: open,
  });
  const targetKinds = meta?.target_kinds ?? FALLBACK_TARGET_KINDS;

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<ProjectResult[]>(),
    staleTime: 5 * 60_000,
    enabled: open,
  });
  const { data: users = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: () =>
      apiGet<UserResult[]>('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
    enabled: open,
  });

  const createMut = useMutation({
    mutationFn: (payload: ApprovalRouteCreatePayload) => createRoute(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['approval-routes'] });
      addToast({
        type: 'success',
        title: t('approvalRoutes.toast_route_created', {
          defaultValue: 'Route created',
        }),
      });
      onClose();
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const updateMut = useMutation({
    mutationFn: (vars: { id: string; payload: ApprovalRouteUpdatePayload }) =>
      updateRoute(vars.id, vars.payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['approval-routes'] });
      addToast({
        type: 'success',
        title: t('approvalRoutes.toast_route_updated', {
          defaultValue: 'Route updated',
        }),
      });
      onClose();
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const busy = createMut.isPending || updateMut.isPending;

  /* ── Step row manipulation ─────────────────────────────────────── */

  const addStep = () => setSteps((p) => [...p, emptyDraftStep()]);
  const removeStep = (idx: number) =>
    setSteps((p) => p.filter((_, i) => i !== idx));
  const moveStep = (idx: number, delta: -1 | 1) =>
    setSteps((p) => {
      const next = [...p];
      const targetIdx = idx + delta;
      if (targetIdx < 0 || targetIdx >= next.length) return next;
      const a = next[idx];
      const b = next[targetIdx];
      if (!a || !b) return next;
      next[idx] = b;
      next[targetIdx] = a;
      return next;
    });
  const updateStep = <K extends keyof DraftStep>(
    idx: number,
    key: K,
    value: DraftStep[K],
  ) =>
    setSteps((p) =>
      p.map((s, i) => {
        if (i !== idx) return s;
        const next = { ...s, [key]: value };
        // Enforce mutex: setting a role clears the user pin and vice versa.
        if (key === 'approver_role' && value) {
          next.approver_user_id = '';
        }
        if (key === 'approver_user_id' && value) {
          next.approver_role = '';
        }
        return next;
      }),
    );

  /* ── Validation ─────────────────────────────────────────────────── */

  const validationError = useMemo(() => {
    if (!name.trim()) {
      return t('approvalRoutes.error_name_required', {
        defaultValue: 'Route name is required.',
      });
    }
    if (!targetKind.trim()) {
      return t('approvalRoutes.error_target_kind_required', {
        defaultValue: 'Target kind is required.',
      });
    }
    if (steps.length === 0) {
      return t('approvalRoutes.error_steps_required', {
        defaultValue: 'At least one step is required.',
      });
    }
    for (let i = 0; i < steps.length; i++) {
      const s = steps[i]!;
      if (!s.approver_role.trim() && !s.approver_user_id.trim()) {
        return t('approvalRoutes.error_step_approver_required', {
          defaultValue: 'Step {{n}}: pick an approver role or user.',
          n: i + 1,
        });
      }
      if (s.sla_hours && !/^\d+$/.test(s.sla_hours)) {
        return t('approvalRoutes.error_sla_integer', {
          defaultValue: 'Step {{n}}: SLA must be a whole number of hours.',
          n: i + 1,
        });
      }
    }
    return null;
  }, [name, targetKind, steps, t]);

  const handleSubmit = () => {
    if (validationError) {
      addToast({
        type: 'error',
        title: t('common.invalid_form', { defaultValue: 'Invalid form' }),
        message: validationError,
      });
      return;
    }
    const stepPayloads = toStepPayloads(steps);
    if (isEdit && route) {
      // target_kind and project_id are immutable on the backend, so the patch
      // could only ever carry name / is_active / steps - and of those, only
      // the ones the user actually moved. Flipping a route inactive used to
      // resend its whole step list as this editor had loaded it, so an
      // approver a colleague had just added was silently dropped. The update
      // route dumps with `exclude_unset=True`. The step baseline runs the same
      // transform over the route as it arrived, and the lists are compared by
      // content because a fresh array is built on every save.
      const payload: ApprovalRouteUpdatePayload = {};
      if (name !== route.name) payload.name = name.trim();
      if (isActive !== route.is_active) payload.is_active = isActive;
      const baseSteps = toStepPayloads(
        [...route.steps].sort((a, b) => a.ordinal - b.ordinal).map(toDraft),
      );
      if (JSON.stringify(stepPayloads) !== JSON.stringify(baseSteps)) {
        payload.steps = stepPayloads;
      }
      updateMut.mutate({ id: route.id, payload });
    } else {
      const payload: ApprovalRouteCreatePayload = {
        project_id: projectId || null,
        target_kind: targetKind.trim(),
        name: name.trim(),
        is_active: isActive,
        steps: stepPayloads,
      };
      createMut.mutate(payload);
    }
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="xl"
      title={
        isEdit
          ? t('approvalRoutes.edit_route', { defaultValue: 'Edit approval route' })
          : t('approvalRoutes.newRoute', { defaultValue: 'New approval route' })
      }
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="md"
            onClick={handleSubmit}
            loading={busy}
            disabled={busy || validationError != null}
          >
            {isEdit
              ? t('common.save', { defaultValue: 'Save' })
              : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('approvalRoutes.section_basics', { defaultValue: 'Basics' })}
      >
        <div className="sm:col-span-2">
          <label className="block text-xs font-medium text-content-secondary mb-1">
            {t('approvalRoutes.name', { defaultValue: 'Name' })}
            <span className="text-semantic-error ml-0.5">*</span>
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('approvalRoutes.name_placeholder', {
              defaultValue: 'e.g. Submittals - Standard 2-step review',
            })}
            className="h-9 w-full rounded-md border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            autoFocus
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-content-secondary mb-1">
            {t('approvalRoutes.target_kind', { defaultValue: 'Target kind' })}
            <span className="text-semantic-error ml-0.5">*</span>
          </label>
          <select
            value={targetKind}
            onChange={(e) => setTargetKind(e.target.value)}
            disabled={isEdit}
            className="h-9 w-full rounded-md border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {targetKinds.map((k) => (
              <option key={k} value={k}>
                {kindLabel(t, k)}
              </option>
            ))}
            {!targetKinds.includes(targetKind) && (
              <option value={targetKind}>{kindLabel(t, targetKind)}</option>
            )}
          </select>
          {isEdit && (
            <p className="mt-0.5 text-2xs text-content-tertiary">
              {t('approvalRoutes.target_kind_locked', {
                defaultValue: 'Target kind cannot be changed after creation.',
              })}
            </p>
          )}
        </div>

        <div>
          <label className="block text-xs font-medium text-content-secondary mb-1">
            {t('approvalRoutes.project', { defaultValue: 'Project (optional)' })}
          </label>
          <select
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            disabled={isEdit}
            className="h-9 w-full rounded-md border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
          >
            <option value="">
              {t('approvalRoutes.global_route', {
                defaultValue: 'Global (all projects)',
              })}
            </option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {isEdit && (
            <p className="mt-0.5 text-2xs text-content-tertiary">
              {t('approvalRoutes.project_locked', {
                defaultValue: 'Scope cannot be changed after creation.',
              })}
            </p>
          )}
        </div>

        <label className="sm:col-span-2 inline-flex items-center gap-2 text-sm text-content-secondary">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(e) => setIsActive(e.target.checked)}
            className="h-4 w-4 rounded border-border accent-oe-blue"
          />
          {t('approvalRoutes.is_active', {
            defaultValue: 'Active - available for new approvals',
          })}
        </label>
      </WideModalSection>

      <WideModalSection
        title={t('approvalRoutes.steps', { defaultValue: 'Steps' })}
        description={t('approvalRoutes.steps_help', {
          defaultValue:
            'Each step is decided sequentially. Pin a role OR a user (not both). Mode controls how many of the assigned approvers must approve.',
        })}
      >
        <div className="sm:col-span-2 space-y-2">
          {steps.map((step, idx) => (
            <StepEditorRow
              key={step.localId}
              step={step}
              index={idx}
              total={steps.length}
              users={users}
              onChange={(key, val) => updateStep(idx, key, val)}
              onRemove={() => removeStep(idx)}
              onMoveUp={() => moveStep(idx, -1)}
              onMoveDown={() => moveStep(idx, 1)}
            />
          ))}
          <Button
            variant="ghost"
            size="sm"
            onClick={addStep}
            icon={<Plus size={14} />}
            data-testid="route-editor-add-step"
          >
            {t('approvalRoutes.add_step', { defaultValue: 'Add step' })}
          </Button>
        </div>

        {validationError && (
          <p className="sm:col-span-2 text-xs text-semantic-error">
            {validationError}
          </p>
        )}
      </WideModalSection>
    </WideModal>
  );
}

/* ── Step row ────────────────────────────────────────────────────────── */

interface StepEditorRowProps {
  step: DraftStep;
  index: number;
  total: number;
  users: UserResult[];
  onChange: <K extends keyof DraftStep>(key: K, value: DraftStep[K]) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}

function StepEditorRow({
  step,
  index,
  total,
  users,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
}: StepEditorRowProps) {
  const { t } = useTranslation();
  const userMode = Boolean(step.approver_user_id);
  // Role steps can only enforce ``any`` (the engine can't expand roles);
  // user-pinned steps are single-approver so every mode is equivalent —
  // we still expose the full list there for forward compatibility.
  const availableModes = userMode ? MODE_OPTIONS : ROLE_STEP_MODES;
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-semibold text-content-tertiary uppercase tracking-wide tabular-nums">
          {t('approvalRoutes.step_n', {
            defaultValue: 'Step {{n}}',
            n: index + 1,
          })}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={onMoveUp}
            disabled={index === 0}
            className={clsx(
              'p-1 rounded-md transition-colors',
              index === 0
                ? 'text-content-tertiary/40 cursor-not-allowed'
                : 'text-content-tertiary hover:bg-surface-secondary',
            )}
            aria-label={t('approvalRoutes.move_up', { defaultValue: 'Move up' })}
          >
            <ArrowUp size={13} />
          </button>
          <button
            onClick={onMoveDown}
            disabled={index === total - 1}
            className={clsx(
              'p-1 rounded-md transition-colors',
              index === total - 1
                ? 'text-content-tertiary/40 cursor-not-allowed'
                : 'text-content-tertiary hover:bg-surface-secondary',
            )}
            aria-label={t('approvalRoutes.move_down', {
              defaultValue: 'Move down',
            })}
          >
            <ArrowDown size={13} />
          </button>
          <button
            onClick={onRemove}
            disabled={total === 1}
            className={clsx(
              'p-1 rounded-md transition-colors',
              total === 1
                ? 'text-content-tertiary/40 cursor-not-allowed'
                : 'text-semantic-error/70 hover:bg-surface-secondary hover:text-semantic-error',
            )}
            aria-label={t('common.delete', { defaultValue: 'Delete' })}
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-12 gap-2">
        {/* Approver toggle (role vs user, mutex) */}
        <div className="sm:col-span-5">
          <label className="block text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-1">
            {t('approvalRoutes.approver', { defaultValue: 'Approver' })}
          </label>
          <div className="flex items-center gap-1 mb-1.5">
            <button
              type="button"
              onClick={() => {
                onChange('approver_user_id', '');
                if (!step.approver_role) onChange('approver_role', 'manager');
              }}
              className={clsx(
                'flex-1 inline-flex items-center justify-center gap-1 h-7 rounded-md border text-2xs font-medium transition-colors',
                !userMode
                  ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                  : 'border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary',
              )}
            >
              <ShieldCheck size={11} />
              {t('approvalRoutes.by_role', { defaultValue: 'Role' })}
            </button>
            <button
              type="button"
              onClick={() => {
                onChange('approver_role', '');
                if (!step.approver_user_id && users[0]) {
                  onChange('approver_user_id', users[0].id);
                }
              }}
              className={clsx(
                'flex-1 inline-flex items-center justify-center gap-1 h-7 rounded-md border text-2xs font-medium transition-colors',
                userMode
                  ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                  : 'border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary',
              )}
            >
              <UserCog size={11} />
              {t('approvalRoutes.by_user', { defaultValue: 'User' })}
            </button>
          </div>
          {userMode ? (
            <select
              value={step.approver_user_id}
              onChange={(e) => onChange('approver_user_id', e.target.value)}
              className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer"
            >
              <option value="">
                {t('approvalRoutes.pick_user', { defaultValue: 'Pick user…' })}
              </option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name || u.email}
                </option>
              ))}
            </select>
          ) : (
            <select
              value={step.approver_role}
              onChange={(e) => onChange('approver_role', e.target.value)}
              className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer"
            >
              <option value="">
                {t('approvalRoutes.pick_role', { defaultValue: 'Pick role…' })}
              </option>
              {KNOWN_ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
              {step.approver_role && !KNOWN_ROLES.includes(step.approver_role) && (
                <option value={step.approver_role}>{step.approver_role}</option>
              )}
            </select>
          )}
        </div>

        {/* Mode */}
        <div className="sm:col-span-4">
          <label className="block text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-1">
            {t('approvalRoutes.mode', { defaultValue: 'Mode' })}
          </label>
          <select
            value={availableModes.includes(step.mode) ? step.mode : availableModes[0]}
            onChange={(e) => onChange('mode', e.target.value as RouteStepMode)}
            disabled={availableModes.length <= 1}
            className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {availableModes.map((m) => (
              <option key={m} value={m}>
                {t(`approvalRoutes.mode_${m}`, {
                  defaultValue:
                    m === 'all'
                      ? 'All approvers'
                      : m === 'any'
                        ? 'Any approver'
                        : 'Majority',
                })}
              </option>
            ))}
          </select>
          {!userMode && (
            <p className="mt-1 flex items-start gap-1 rounded-md border border-amber-300/60 bg-amber-50/60 px-1.5 py-1 text-2xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-400">
              <AlertTriangle size={11} className="mt-0.5 shrink-0" />
              <span>
                {t('approvalRoutes.mode_role_warning', {
                  defaultValue:
                    'Role steps clear on the first approval. To require all or a majority, pin specific users instead of a role.',
                })}
              </span>
            </p>
          )}
        </div>

        {/* SLA */}
        <div className="sm:col-span-3">
          <label className="block text-2xs font-medium text-content-tertiary uppercase tracking-wide mb-1">
            {t('approvalRoutes.sla_hours', { defaultValue: 'SLA (hours)' })}
          </label>
          <input
            type="number"
            min={1}
            value={step.sla_hours}
            onChange={(e) => onChange('sla_hours', e.target.value)}
            placeholder="—"
            className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue tabular-nums"
          />
        </div>
      </div>
    </div>
  );
}
