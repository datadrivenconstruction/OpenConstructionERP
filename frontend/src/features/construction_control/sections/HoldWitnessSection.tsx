// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pillar 5: Hold / witness / surveillance / review gating.
//
// Gates block downstream work until an authorised party releases them. This
// section lists the gates for the active project and drives the full workflow:
//   * create a gate (kind, the required party role, an optional linked element /
//     activity / handover package / inspection, and whether it blocks progress),
//   * release a gate - the asserted party role must satisfy the required role
//     (qc < qa < tpi < ahj); only a higher-or-equal role may release,
//   * waive a gate - witness / surveillance / review gates only; a hold gate can
//     never be waived, it must be released,
//   * a can-proceed check against an attached entity that surfaces whether work
//     may proceed or which gate numbers are blocking it.
// Each action is offered only when it is valid for the gate's state.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  X,
  ShieldAlert,
  Lock,
  Unlock,
  Ban,
  CheckCircle2,
  XCircle,
  ShieldCheck,
} from 'lucide-react';
import { Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  listGates,
  createGate,
  releaseGate,
  waiveGate,
  gateCanProceed,
  type HoldGate,
  type PointType,
  type PartyRole,
  type GateAttachedKind,
  type GateCreatePayload,
  type GateProceedResponse,
} from '../api';
import { SectionToolbar, StatusBadge, inputCls, labelCls, textareaCls } from './shared';
import { fmtList } from '@/shared/lib/formatters';
import { useSingleFlight } from '@/shared/hooks/useSingleFlight';

const POINT_TYPES: PointType[] = ['hold', 'witness', 'surveillance', 'review'];
const PARTY_ROLES: PartyRole[] = ['qc', 'qa', 'tpi', 'ahj'];
const ATTACHED_KINDS: GateAttachedKind[] = ['activity', 'handover_package', 'inspection'];

// Mirrors the backend rule: a hold gate can only be released, never waived.
const WAIVABLE_POINT_TYPES: ReadonlySet<PointType> = new Set<PointType>([
  'witness',
  'surveillance',
  'review',
]);

// Party-role hierarchy rank used to pre-select a release role that satisfies the
// gate's requirement (qc < qa < tpi < ahj). The server is the source of truth and
// re-checks this; this only keeps the form from defaulting to an invalid role.
const PARTY_ROLE_RANK: Record<PartyRole, number> = { qc: 0, qa: 1, tpi: 2, ahj: 3 };

const GATE_STATUS_VARIANTS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  pending: 'warning',
  released: 'success',
  waived: 'blue',
  void: 'neutral',
};

const POINT_TYPE_VARIANTS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  hold: 'error',
  witness: 'blue',
  surveillance: 'neutral',
  review: 'neutral',
};

const POINT_TYPE_LABEL: Record<PointType, string> = {
  hold: 'Hold',
  witness: 'Witness',
  surveillance: 'Surveillance',
  review: 'Review',
};

interface SectionProps {
  projectId: string;
}

export function HoldWitnessSection({ projectId }: SectionProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showCreate, setShowCreate] = useState(false);
  const [releaseTarget, setReleaseTarget] = useState<HoldGate | null>(null);
  const [waiveTarget, setWaiveTarget] = useState<HoldGate | null>(null);
  const [showProceed, setShowProceed] = useState(false);

  const gatesQuery = useQuery({
    queryKey: ['cc', 'gates', projectId],
    queryFn: () => listGates(projectId),
    enabled: !!projectId,
  });

  const gates = useMemo(() => gatesQuery.data ?? [], [gatesQuery.data]);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['cc', 'gates', projectId] });
  };

  const toastError = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('common.error', { defaultValue: 'Something went wrong' }),
      message: (e as Error).message,
    });

  const createMutationOnce = useSingleFlight();
  const createMutation = useMutation({
    mutationFn: createGate,
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('construction_control.gate.created_title', { defaultValue: 'Gate created' }),
        message: t('construction_control.gate.created_msg', {
          defaultValue: 'The hold / witness point has been added to this project.',
        }),
      });
      setShowCreate(false);
      invalidate();
    },
    onError: toastError,
  });

  const releaseMutation = useMutation({
    mutationFn: ({
      id,
      party_role,
      justification,
    }: {
      id: string;
      party_role: PartyRole;
      justification: string;
    }) => releaseGate(id, { party_role, justification: justification || null }),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('construction_control.gate.released_title', { defaultValue: 'Gate released' }),
        message: t('construction_control.gate.released_msg', {
          defaultValue: 'The gate was released and downstream work may now proceed.',
        }),
      });
      setReleaseTarget(null);
      invalidate();
    },
    onError: toastError,
  });

  const waiveMutation = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => waiveGate(id, { reason }),
    onSuccess: () => {
      addToast({
        type: 'warning',
        title: t('construction_control.gate.waived_title', { defaultValue: 'Gate waived' }),
        message: t('construction_control.gate.waived_msg', {
          defaultValue: 'The gate was waived with a recorded reason.',
        }),
      });
      setWaiveTarget(null);
      invalidate();
    },
    onError: toastError,
  });

  return (
    <div className="space-y-3">
      <SectionToolbar
        title={t('construction_control.gates_heading', { defaultValue: 'Hold / witness points' })}
        count={gates.length}
      >
        <Button
          variant="secondary"
          size="sm"
          icon={<ShieldCheck className="h-4 w-4" />}
          onClick={() => setShowProceed(true)}
        >
          {t('construction_control.gate.check_proceed', { defaultValue: 'Can-proceed check' })}
        </Button>
        <Button
          variant="primary"
          size="sm"
          icon={<Plus className="h-4 w-4" />}
          onClick={() => setShowCreate(true)}
        >
          {t('construction_control.gate.new', { defaultValue: 'New gate' })}
        </Button>
      </SectionToolbar>

      {gatesQuery.isLoading ? (
        <SkeletonTable rows={4} columns={6} />
      ) : gatesQuery.isError ? (
        <Card>
          <div className="p-6 text-sm text-semantic-error">
            {t('construction_control.gate.load_error', {
              defaultValue: 'Could not load hold / witness points. Please try again.',
            })}
          </div>
        </Card>
      ) : gates.length === 0 ? (
        <EmptyState
          icon={<ShieldAlert size={26} strokeWidth={1.5} />}
          title={t('construction_control.gate.empty_title', {
            defaultValue: 'No hold or witness points yet',
          })}
          description={t('construction_control.gate.empty_desc', {
            defaultValue:
              'Hold points stop progress until an authorised party releases them; witness, surveillance and review points can also be waived.',
          })}
          action={{
            label: t('construction_control.gate.new', { defaultValue: 'New gate' }),
            onClick: () => setShowCreate(true),
          }}
        />
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
                  <th className="px-4 py-2.5 font-medium">
                    {t('construction_control.col.number', { defaultValue: 'Number' })}
                  </th>
                  <th className="px-4 py-2.5 font-medium">
                    {t('construction_control.col.title', { defaultValue: 'Title' })}
                  </th>
                  <th className="px-4 py-2.5 font-medium">
                    {t('construction_control.col.point_type', { defaultValue: 'Type' })}
                  </th>
                  <th className="px-4 py-2.5 font-medium">
                    {t('construction_control.col.required_role', { defaultValue: 'Required role' })}
                  </th>
                  <th className="px-4 py-2.5 font-medium">
                    {t('construction_control.col.status', { defaultValue: 'Status' })}
                  </th>
                  <th className="px-4 py-2.5 text-right font-medium">
                    {t('construction_control.col.actions', { defaultValue: 'Actions' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {gates.map((gate) => {
                  const isPending = gate.status === 'pending';
                  const canWaive = isPending && WAIVABLE_POINT_TYPES.has(gate.point_type);
                  return (
                    <tr
                      key={gate.id}
                      className="border-b border-border-light/60 last:border-b-0 align-top"
                      data-testid={`cc-gate-row-${gate.id}`}
                    >
                      <td className="px-4 py-3 font-mono text-xs text-content-secondary whitespace-nowrap">
                        {gate.gate_number}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-content-primary">{gate.title}</div>
                        <div className="mt-0.5 flex items-center gap-1 text-xs text-content-tertiary">
                          {gate.blocks_progress ? (
                            <Lock className="h-3 w-3" />
                          ) : (
                            <Unlock className="h-3 w-3" />
                          )}
                          {gate.blocks_progress
                            ? t('construction_control.gate.blocks', {
                                defaultValue: 'Blocks progress',
                              })
                            : t('construction_control.gate.advisory', { defaultValue: 'Advisory' })}
                        </div>
                        {gate.attached_kind && (
                          <div className="mt-0.5 text-2xs text-content-tertiary">
                            {t(`construction_control.attached_kind.${gate.attached_kind}`, {
                              defaultValue: gate.attached_kind.replace(/_/g, ' '),
                            })}
                            {gate.attached_id ? ` - ${gate.attached_id}` : ''}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge
                          status={gate.point_type}
                          variants={POINT_TYPE_VARIANTS}
                          label={t(`construction_control.point_type.${gate.point_type}`, {
                            defaultValue: POINT_TYPE_LABEL[gate.point_type],
                          })}
                        />
                      </td>
                      <td className="px-4 py-3 uppercase text-xs text-content-secondary">
                        {gate.required_party_role}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={gate.status} variants={GATE_STATUS_VARIANTS} />
                        {gate.status === 'released' && gate.released_party_role && (
                          <div className="mt-1 text-2xs text-content-tertiary">
                            {t('construction_control.gate.released_as', {
                              defaultValue: 'as {{role}}',
                              role: gate.released_party_role.toUpperCase(),
                            })}
                          </div>
                        )}
                        {gate.status === 'waived' && gate.waived_reason && (
                          <div
                            className="mt-1 max-w-[16rem] truncate text-2xs text-content-tertiary"
                            title={gate.waived_reason}
                          >
                            {gate.waived_reason}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-2">
                          {isPending && (
                            <Button
                              variant="secondary"
                              size="sm"
                              icon={<Unlock className="h-3.5 w-3.5" />}
                              onClick={() => setReleaseTarget(gate)}
                            >
                              {t('construction_control.gate.release', { defaultValue: 'Release' })}
                            </Button>
                          )}
                          {canWaive && (
                            <Button
                              variant="ghost"
                              size="sm"
                              icon={<Ban className="h-3.5 w-3.5" />}
                              onClick={() => setWaiveTarget(gate)}
                            >
                              {t('construction_control.gate.waive', { defaultValue: 'Waive' })}
                            </Button>
                          )}
                          {!isPending && (
                            <span className="text-2xs text-content-tertiary">
                              {t('construction_control.gate.no_actions', {
                                defaultValue: 'No actions',
                              })}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {showCreate && (
        <CreateGateModal
          projectId={projectId}
          isPending={createMutation.isPending}
          onClose={() => setShowCreate(false)}
          onSubmit={(payload) => createMutationOnce(() => createMutation.mutateAsync(payload))}
        />
      )}

      {releaseTarget && (
        <ReleaseGateModal
          gate={releaseTarget}
          isPending={releaseMutation.isPending}
          onClose={() => setReleaseTarget(null)}
          onSubmit={(party_role, justification) =>
            releaseMutation.mutate({ id: releaseTarget.id, party_role, justification })
          }
        />
      )}

      {waiveTarget && (
        <WaiveGateModal
          gate={waiveTarget}
          isPending={waiveMutation.isPending}
          onClose={() => setWaiveTarget(null)}
          onSubmit={(reason) => waiveMutation.mutate({ id: waiveTarget.id, reason })}
        />
      )}

      {showProceed && (
        <CanProceedModal projectId={projectId} onClose={() => setShowProceed(false)} />
      )}
    </div>
  );
}

// ── Modal primitives (local helpers) ─────────────────────────────────────────

function ModalShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-border bg-surface-elevated shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <h3 className="text-lg font-semibold text-content-primary">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function ModalFooter({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-end gap-3 border-t border-border-light px-6 py-4">
      {children}
    </div>
  );
}

// ── Create-gate modal ────────────────────────────────────────────────────────

interface CreateForm {
  point_type: PointType;
  title: string;
  description: string;
  required_party_role: PartyRole;
  attached_kind: '' | GateAttachedKind;
  attached_id: string;
  blocks_progress_override: boolean;
}

const EMPTY_CREATE: CreateForm = {
  point_type: 'hold',
  title: '',
  description: '',
  required_party_role: 'qa',
  attached_kind: '',
  attached_id: '',
  blocks_progress_override: false,
};

function CreateGateModal({
  projectId,
  isPending,
  onClose,
  onSubmit,
}: {
  projectId: string;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: GateCreatePayload) => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<CreateForm>(EMPTY_CREATE);
  const [touched, setTouched] = useState(false);
  const canSubmit = form.title.trim().length > 0;

  // A hold blocks by default; the other kinds are advisory unless the user opts in.
  const blocksByDefault = form.point_type === 'hold';

  const set = <K extends keyof CreateForm>(key: K, value: CreateForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    // Only send blocks_progress when the user overrode the non-hold default; leaving it
    // null lets the server derive it from the point type (hold blocks, others advisory).
    const blocks_progress =
      !blocksByDefault && form.blocks_progress_override ? true : null;
    onSubmit({
      project_id: projectId,
      point_type: form.point_type,
      title: form.title.trim(),
      description: form.description.trim() || null,
      required_party_role: form.required_party_role,
      attached_kind: form.attached_kind || null,
      attached_id: form.attached_kind && form.attached_id.trim() ? form.attached_id.trim() : null,
      blocks_progress,
    });
  };

  return (
    <ModalShell
      title={t('construction_control.gate.new', { defaultValue: 'New gate' })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-gate-type" className={labelCls}>
              {t('construction_control.col.point_type', { defaultValue: 'Type' })}
            </label>
            <select
              id="cc-gate-type"
              value={form.point_type}
              onChange={(e) => set('point_type', e.target.value as PointType)}
              className={inputCls}
            >
              {POINT_TYPES.map((pt) => (
                <option key={pt} value={pt}>
                  {POINT_TYPE_LABEL[pt]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cc-gate-role" className={labelCls}>
              {t('construction_control.field.required_role', { defaultValue: 'Required role' })}
            </label>
            <select
              id="cc-gate-role"
              value={form.required_party_role}
              onChange={(e) => set('required_party_role', e.target.value as PartyRole)}
              className={inputCls}
            >
              {PARTY_ROLES.map((r) => (
                <option key={r} value={r}>
                  {r.toUpperCase()}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label htmlFor="cc-gate-title" className={labelCls}>
            {t('construction_control.col.title', { defaultValue: 'Title' })}
          </label>
          <input
            id="cc-gate-title"
            value={form.title}
            onChange={(e) => set('title', e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.gate.title_ph', {
              defaultValue: 'e.g. Hold - rebar witness before pour, Level 2 slab',
            })}
          />
          {touched && !canSubmit && (
            <p className="mt-1 text-xs text-semantic-error">
              {t('construction_control.field.title_required', {
                defaultValue: 'A title is required.',
              })}
            </p>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-gate-attached-kind" className={labelCls}>
              {t('construction_control.field.attached_kind', {
                defaultValue: 'Applies to (optional)',
              })}
            </label>
            <select
              id="cc-gate-attached-kind"
              value={form.attached_kind}
              onChange={(e) => set('attached_kind', e.target.value as '' | GateAttachedKind)}
              className={inputCls}
            >
              <option value="">
                {t('construction_control.field.attached_none', { defaultValue: 'Not attached' })}
              </option>
              {ATTACHED_KINDS.map((k) => (
                <option key={k} value={k}>
                  {t(`construction_control.attached_kind.${k}`, {
                    defaultValue: k.replace(/_/g, ' '),
                  })}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cc-gate-attached-id" className={labelCls}>
              {t('construction_control.field.attached_id', { defaultValue: 'Attached entity id' })}
            </label>
            <input
              id="cc-gate-attached-id"
              value={form.attached_id}
              onChange={(e) => set('attached_id', e.target.value)}
              disabled={!form.attached_kind}
              className={`${inputCls} disabled:cursor-not-allowed disabled:opacity-60`}
              placeholder={t('construction_control.field.attached_id_ph', {
                defaultValue: 'Activity / package / inspection id',
              })}
            />
          </div>
        </div>

        <div>
          <label htmlFor="cc-gate-desc" className={labelCls}>
            {t('construction_control.field.description', { defaultValue: 'Description' })}
          </label>
          <textarea
            id="cc-gate-desc"
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('construction_control.gate.desc_ph', {
              defaultValue: 'What must be satisfied before this gate can be released...',
            })}
          />
        </div>

        {blocksByDefault ? (
          <p className="flex items-start gap-1.5 text-xs text-content-tertiary">
            <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-semantic-error" />
            {t('construction_control.gate.hold_blocks_hint', {
              defaultValue:
                'A hold gate blocks progress until an authorised party releases it. It cannot be waived.',
            })}
          </p>
        ) : (
          <label className="flex items-center gap-2 text-sm text-content-secondary">
            <input
              type="checkbox"
              checked={form.blocks_progress_override}
              onChange={(e) => set('blocks_progress_override', e.target.checked)}
              className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
            />
            {t('construction_control.gate.blocks_override', {
              defaultValue: 'This gate should also block progress (not just advise)',
            })}
          </label>
        )}
      </div>

      <ModalFooter>
        <Button variant="ghost" onClick={onClose} disabled={isPending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={handleSubmit}
          loading={isPending}
          disabled={isPending || !canSubmit}
          icon={<Plus className="h-4 w-4" />}
        >
          {t('construction_control.gate.create', { defaultValue: 'Create gate' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Release-gate modal ───────────────────────────────────────────────────────

function ReleaseGateModal({
  gate,
  isPending,
  onClose,
  onSubmit,
}: {
  gate: HoldGate;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (partyRole: PartyRole, justification: string) => void;
}) {
  const { t } = useTranslation();
  // Default the asserted role to the gate's requirement so the form starts valid.
  const [partyRole, setPartyRole] = useState<PartyRole>(gate.required_party_role);
  const [justification, setJustification] = useState('');

  const requiredRank = PARTY_ROLE_RANK[gate.required_party_role];
  const satisfies = PARTY_ROLE_RANK[partyRole] >= requiredRank;

  return (
    <ModalShell
      title={t('construction_control.gate.release_for', {
        defaultValue: 'Release {{number}}',
        number: gate.gate_number,
      })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <p className="text-sm text-content-secondary">{gate.title}</p>
        <p className="text-xs text-content-tertiary">
          {t('construction_control.gate.requires_role', {
            defaultValue: 'Requires a party role of {{role}} or higher (qc < qa < tpi < ahj).',
            role: gate.required_party_role.toUpperCase(),
          })}
        </p>

        <div>
          <label htmlFor="cc-release-role" className={labelCls}>
            {t('construction_control.field.asserted_role', { defaultValue: 'Releasing as' })}
          </label>
          <select
            id="cc-release-role"
            value={partyRole}
            onChange={(e) => setPartyRole(e.target.value as PartyRole)}
            className={inputCls}
          >
            {PARTY_ROLES.map((r) => (
              <option key={r} value={r}>
                {r.toUpperCase()}
              </option>
            ))}
          </select>
          {!satisfies && (
            <p className="mt-1 flex items-start gap-1.5 text-xs text-semantic-error">
              <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {t('construction_control.gate.role_too_low', {
                defaultValue:
                  'A {{asserted}} role cannot release a gate that requires {{required}}.',
                asserted: partyRole.toUpperCase(),
                required: gate.required_party_role.toUpperCase(),
              })}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="cc-release-justification" className={labelCls}>
            {t('construction_control.field.justification', {
              defaultValue: 'Justification (optional)',
            })}
          </label>
          <textarea
            id="cc-release-justification"
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('construction_control.gate.justification_ph', {
              defaultValue: 'Evidence reviewed, inspection passed, conditions met...',
            })}
          />
        </div>

        <p className="flex items-start gap-1.5 text-xs text-content-tertiary">
          <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-semantic-success" />
          {t('construction_control.gate.release_sign_hint', {
            defaultValue:
              'Releasing records an e-signature (signer, time and a tamper-evident hash) and unblocks downstream work.',
          })}
        </p>
      </div>

      <ModalFooter>
        <Button variant="ghost" onClick={onClose} disabled={isPending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={() => onSubmit(partyRole, justification)}
          loading={isPending}
          disabled={isPending || !satisfies}
          icon={<Unlock className="h-4 w-4" />}
        >
          {t('construction_control.gate.release', { defaultValue: 'Release' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Waive-gate modal ─────────────────────────────────────────────────────────

function WaiveGateModal({
  gate,
  isPending,
  onClose,
  onSubmit,
}: {
  gate: HoldGate;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => void;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const canSubmit = reason.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    onSubmit(reason.trim());
  };

  return (
    <ModalShell
      title={t('construction_control.gate.waive_for', {
        defaultValue: 'Waive {{number}}',
        number: gate.gate_number,
      })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <p className="text-sm text-content-secondary">{gate.title}</p>
        <p className="flex items-start gap-1.5 text-xs text-content-tertiary">
          <Ban className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#b45309]" />
          {t('construction_control.gate.waive_hint', {
            defaultValue:
              'Waiving clears this gate without a release. A reason is required and recorded. Hold gates cannot be waived.',
          })}
        </p>

        <div>
          <label htmlFor="cc-waive-reason" className={labelCls}>
            {t('construction_control.field.reason', { defaultValue: 'Reason' })}
          </label>
          <textarea
            id="cc-waive-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('construction_control.gate.reason_ph', {
              defaultValue: 'Why this witness / surveillance / review point is being waived...',
            })}
          />
          {touched && !canSubmit && (
            <p className="mt-1 text-xs text-semantic-error">
              {t('construction_control.gate.reason_required', {
                defaultValue: 'A reason is required to waive a gate.',
              })}
            </p>
          )}
        </div>
      </div>

      <ModalFooter>
        <Button variant="ghost" onClick={onClose} disabled={isPending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="danger"
          onClick={handleSubmit}
          loading={isPending}
          disabled={isPending || !canSubmit}
          icon={<Ban className="h-4 w-4" />}
        >
          {t('construction_control.gate.waive', { defaultValue: 'Waive' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Can-proceed modal ────────────────────────────────────────────────────────

function CanProceedModal({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [kind, setKind] = useState<GateAttachedKind>('activity');
  const [entityId, setEntityId] = useState('');
  const [result, setResult] = useState<GateProceedResponse | null>(null);
  const canSubmit = entityId.trim().length > 0;

  const checkMutation = useMutation({
    mutationFn: ({ k, id }: { k: GateAttachedKind; id: string }) =>
      gateCanProceed(projectId, k, id),
    onSuccess: (res) => setResult(res),
    onError: (e: unknown) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Something went wrong' }),
        message: (e as Error).message,
      }),
  });

  const handleCheck = () => {
    if (!canSubmit) return;
    setResult(null);
    checkMutation.mutate({ k: kind, id: entityId.trim() });
  };

  return (
    <ModalShell
      title={t('construction_control.gate.proceed_title', { defaultValue: 'Can-proceed check' })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <p className="text-sm text-content-secondary">
          {t('construction_control.gate.proceed_desc', {
            defaultValue:
              'Check whether an attached entity is clear of blocking gates, or see which gates are holding it.',
          })}
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-proceed-kind" className={labelCls}>
              {t('construction_control.field.attached_kind', { defaultValue: 'Applies to' })}
            </label>
            <select
              id="cc-proceed-kind"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as GateAttachedKind);
                setResult(null);
              }}
              className={inputCls}
            >
              {ATTACHED_KINDS.map((k) => (
                <option key={k} value={k}>
                  {t(`construction_control.attached_kind.${k}`, {
                    defaultValue: k.replace(/_/g, ' '),
                  })}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cc-proceed-id" className={labelCls}>
              {t('construction_control.field.attached_id', { defaultValue: 'Attached entity id' })}
            </label>
            <input
              id="cc-proceed-id"
              value={entityId}
              onChange={(e) => {
                setEntityId(e.target.value);
                setResult(null);
              }}
              className={inputCls}
              placeholder={t('construction_control.field.attached_id_ph', {
                defaultValue: 'Activity / package / inspection id',
              })}
            />
          </div>
        </div>

        {result && (
          <div
            data-testid="cc-proceed-result"
            className={`rounded-lg border p-3 text-sm ${
              result.can_proceed
                ? 'border-semantic-success/40 bg-semantic-success-bg text-semantic-success'
                : 'border-semantic-error/40 bg-semantic-error-bg text-semantic-error'
            }`}
          >
            <div className="flex items-center gap-2 font-medium">
              {result.can_proceed ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <XCircle className="h-4 w-4" />
              )}
              {result.can_proceed
                ? t('construction_control.gate.proceed_allowed', {
                    defaultValue: 'Work may proceed - no blocking gates.',
                  })
                : t('construction_control.gate.proceed_blocked', {
                    defaultValue: 'Blocked by unreleased gate(s).',
                  })}
            </div>
            {!result.can_proceed && result.blocking_gate_numbers.length > 0 && (
              <div className="mt-1.5 font-mono text-xs">
                {fmtList(result.blocking_gate_numbers)}
              </div>
            )}
          </div>
        )}
      </div>

      <ModalFooter>
        <Button variant="ghost" onClick={onClose} disabled={checkMutation.isPending}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
        <Button
          variant="primary"
          onClick={handleCheck}
          loading={checkMutation.isPending}
          disabled={checkMutation.isPending || !canSubmit}
          icon={<ShieldCheck className="h-4 w-4" />}
        >
          {t('construction_control.gate.run_check', { defaultValue: 'Run check' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

export default HoldWitnessSection;
