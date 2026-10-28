// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pillar 1: Acceptance criteria + inspections (the reference-quality section).
//
// Fully implements the first pillar's workflow:
//   * list acceptance criteria and inspections for the active project,
//   * create an inspection (optionally bound to a criterion + a model element),
//   * record a pass / fail / conditional result, where a fail or conditional
//     auto-raises a non-conformance report (the linkage is surfaced as a chip),
//   * show the resolved Universal Element Reference (UER) link per inspection.
//
// The other four pillar sections mirror this structure (toolbar + table +
// create/action modals + react-query mutations + toasts).

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  X,
  ClipboardCheck,
  ListChecks,
  CheckCircle2,
  XCircle,
  AlertCircle,
  AlertOctagon,
} from 'lucide-react';
import { Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  listCriteria,
  listInspections,
  createInspection,
  recordInspectionResult,
  type AcceptanceCriterion,
  type Inspection,
  type InspectionType,
  type PartyRole,
  type ResultDecision,
} from '../api';
import {
  ElementLinks,
  SectionToolbar,
  inputCls,
  labelCls,
  textareaCls,
} from './shared';
import { useSingleFlight } from '@/shared/hooks/useSingleFlight';

const INSPECTION_TYPES: InspectionType[] = ['mir', 'wir', 'ir', 'hidden_works', 'acceptance'];
const PARTY_ROLES: PartyRole[] = ['qc', 'qa', 'tpi', 'ahj'];

const INSPECTION_TYPE_LABEL: Record<InspectionType, string> = {
  mir: 'Material Inspection (MIR)',
  wir: 'Work Inspection (WIR)',
  ir: 'Inspection Request (IR)',
  hidden_works: 'Hidden Works',
  acceptance: 'Acceptance',
};

const STATUS_VARIANTS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  scheduled: 'blue',
  in_progress: 'blue',
  passed: 'success',
  failed: 'error',
  closed: 'neutral',
  void: 'neutral',
};

interface SectionProps {
  projectId: string;
}

export function AcceptanceInspectionsSection({ projectId }: SectionProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [showCreate, setShowCreate] = useState(false);
  const [resultTarget, setResultTarget] = useState<Inspection | null>(null);

  const criteriaQuery = useQuery({
    queryKey: ['cc', 'criteria', projectId],
    queryFn: () => listCriteria(projectId),
    enabled: !!projectId,
  });

  const inspectionsQuery = useQuery({
    queryKey: ['cc', 'inspections', projectId],
    queryFn: () => listInspections(projectId),
    enabled: !!projectId,
  });

  const criteria = useMemo(() => criteriaQuery.data ?? [], [criteriaQuery.data]);
  const inspections = inspectionsQuery.data ?? [];

  const criterionById = useMemo(() => {
    const map = new Map<string, AcceptanceCriterion>();
    criteria.forEach((c) => map.set(c.id, c));
    return map;
  }, [criteria]);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['cc', 'inspections', projectId] });
  };

  const createMutationOnce = useSingleFlight();
  const createMutation = useMutation({
    mutationFn: createInspection,
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('construction_control.inspection.created_title', {
          defaultValue: 'Inspection created',
        }),
        message: t('construction_control.inspection.created_msg', {
          defaultValue: 'The inspection has been added to this project.',
        }),
      });
      setShowCreate(false);
      invalidate();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Something went wrong' }),
        message: (e as Error).message,
      }),
  });

  const resultMutation = useMutation({
    mutationFn: ({ id, result, notes }: { id: string; result: ResultDecision; notes: string }) =>
      recordInspectionResult(id, { result, notes: notes || null }),
    onSuccess: (updated) => {
      const raisedNcr = !!updated.raised_ncr_id;
      addToast({
        type: raisedNcr ? 'warning' : 'success',
        title: raisedNcr
          ? t('construction_control.inspection.result_ncr_title', {
              defaultValue: 'Result recorded - NCR raised',
            })
          : t('construction_control.inspection.result_title', {
              defaultValue: 'Result recorded',
            }),
        message: raisedNcr
          ? t('construction_control.inspection.result_ncr_msg', {
              defaultValue: 'A non-conformance report was raised automatically and linked.',
            })
          : t('construction_control.inspection.result_pass_msg', {
              defaultValue: 'The inspection passed.',
            }),
      });
      setResultTarget(null);
      invalidate();
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Something went wrong' }),
        message: (e as Error).message,
      }),
  });

  return (
    <div className="space-y-8">
      {/* ── Inspections ──────────────────────────────────────────────────── */}
      <section className="space-y-3">
        <SectionToolbar
          title={t('construction_control.inspections_heading', { defaultValue: 'Inspections' })}
          count={inspections.length}
        >
          <Button
            variant="primary"
            size="sm"
            icon={<Plus className="h-4 w-4" />}
            onClick={() => setShowCreate(true)}
          >
            {t('construction_control.inspection.new', { defaultValue: 'New inspection' })}
          </Button>
        </SectionToolbar>

        {inspectionsQuery.isLoading ? (
          <SkeletonTable rows={4} columns={6} />
        ) : inspectionsQuery.isError ? (
          <Card>
            <div className="p-6 text-sm text-semantic-error">
              {t('construction_control.load_error', {
                defaultValue: 'Could not load inspections. Please try again.',
              })}
            </div>
          </Card>
        ) : inspections.length === 0 ? (
          <EmptyState
            icon={<ClipboardCheck size={26} strokeWidth={1.5} />}
            title={t('construction_control.inspection.empty_title', {
              defaultValue: 'No inspections yet',
            })}
            description={t('construction_control.inspection.empty_desc', {
              defaultValue:
                'Raise an MIR, WIR, IR or hidden-works inspection. A failed result automatically opens a non-conformance report.',
            })}
            action={{
              label: t('construction_control.inspection.new', { defaultValue: 'New inspection' }),
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
                      {t('construction_control.col.type', { defaultValue: 'Type' })}
                    </th>
                    <th className="px-4 py-2.5 font-medium">
                      {t('construction_control.col.status', { defaultValue: 'Status' })}
                    </th>
                    <th className="px-4 py-2.5 font-medium">
                      {t('construction_control.col.criterion', { defaultValue: 'Criterion' })}
                    </th>
                    <th className="px-4 py-2.5 text-right font-medium">
                      {t('construction_control.col.actions', { defaultValue: 'Actions' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {inspections.map((insp) => {
                    const criterion = insp.criterion_id
                      ? criterionById.get(insp.criterion_id)
                      : undefined;
                    const canRecord = ['draft', 'scheduled', 'in_progress'].includes(insp.status);
                    return (
                      <tr
                        key={insp.id}
                        className="border-b border-border-light/60 last:border-b-0 align-top"
                        data-testid={`cc-inspection-row-${insp.id}`}
                      >
                        <td className="px-4 py-3 font-mono text-xs text-content-secondary whitespace-nowrap">
                          {insp.inspection_number}
                        </td>
                        <td className="px-4 py-3">
                          <div className="font-medium text-content-primary">{insp.title}</div>
                          {insp.location_description && (
                            <div className="text-xs text-content-tertiary">
                              {insp.location_description}
                            </div>
                          )}
                          <div className="mt-1">
                            <ElementLinks elements={insp.elements} />
                          </div>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-content-secondary">
                          {t(`construction_control.inspection_type.${insp.inspection_type}`, {
                            defaultValue: INSPECTION_TYPE_LABEL[insp.inspection_type],
                          })}
                          <span className="ml-1 uppercase text-2xs text-content-tertiary">
                            {insp.party_role}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <StatusPill status={insp.status} />
                          {insp.result && (
                            <div className="mt-1 text-2xs text-content-tertiary">
                              {t(`construction_control.result.${insp.result}`, {
                                defaultValue: insp.result,
                              })}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3 text-content-secondary">
                          {criterion ? (
                            <span title={criterion.title}>
                              {criterion.code}
                            </span>
                          ) : (
                            <span className="text-content-tertiary">
                              {t('construction_control.none', { defaultValue: '-' })}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-2">
                            {insp.raised_ncr_id && (
                              <span className="inline-flex items-center gap-1 rounded-md bg-semantic-error-bg px-2 py-0.5 text-2xs font-medium text-semantic-error">
                                <AlertOctagon className="h-3 w-3" />
                                {t('construction_control.ncr_linked', { defaultValue: 'NCR' })}
                              </span>
                            )}
                            {canRecord && (
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={() => setResultTarget(insp)}
                              >
                                {t('construction_control.inspection.record', {
                                  defaultValue: 'Record result',
                                })}
                              </Button>
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
      </section>

      {/* ── Acceptance criteria ──────────────────────────────────────────── */}
      <section className="space-y-3">
        <SectionToolbar
          title={t('construction_control.criteria_heading', {
            defaultValue: 'Acceptance criteria',
          })}
          count={criteria.length}
        />
        {criteriaQuery.isLoading ? (
          <SkeletonTable rows={3} columns={4} />
        ) : criteria.length === 0 ? (
          <EmptyState
            icon={<ListChecks size={26} strokeWidth={1.5} />}
            title={t('construction_control.criteria.empty_title', {
              defaultValue: 'No acceptance criteria yet',
            })}
            description={t('construction_control.criteria.empty_desc', {
              defaultValue:
                'Acceptance criteria define the measurable bounds an inspection or as-built record is judged against.',
            })}
          />
        ) : (
          <Card>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
                    <th className="px-4 py-2.5 font-medium">
                      {t('construction_control.col.code', { defaultValue: 'Code' })}
                    </th>
                    <th className="px-4 py-2.5 font-medium">
                      {t('construction_control.col.title', { defaultValue: 'Title' })}
                    </th>
                    <th className="px-4 py-2.5 font-medium">
                      {t('construction_control.col.rule', { defaultValue: 'Rule' })}
                    </th>
                    <th className="px-4 py-2.5 font-medium">
                      {t('construction_control.col.tolerance', { defaultValue: 'Tolerance' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {criteria.map((c) => (
                    <tr
                      key={c.id}
                      className="border-b border-border-light/60 last:border-b-0"
                      data-testid={`cc-criterion-row-${c.id}`}
                    >
                      <td className="px-4 py-3 font-mono text-xs text-content-secondary whitespace-nowrap">
                        {c.code}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-content-primary">{c.title}</div>
                        {c.standard_ref && (
                          <div className="text-xs text-content-tertiary">{c.standard_ref}</div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-content-secondary">{c.acceptance_rule}</td>
                      <td className="px-4 py-3 text-content-secondary">
                        {formatTolerance(c)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </section>

      {showCreate && (
        <CreateInspectionModal
          projectId={projectId}
          criteria={criteria}
          isPending={createMutation.isPending}
          onClose={() => setShowCreate(false)}
          onSubmit={(payload) => createMutationOnce(() => createMutation.mutateAsync(payload))}
        />
      )}

      {resultTarget && (
        <RecordResultModal
          inspection={resultTarget}
          isPending={resultMutation.isPending}
          onClose={() => setResultTarget(null)}
          onSubmit={(result, notes) =>
            resultMutation.mutate({ id: resultTarget.id, result, notes })
          }
        />
      )}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const variant = STATUS_VARIANTS[status] ?? 'neutral';
  const cls: Record<string, string> = {
    neutral: 'bg-surface-secondary text-content-secondary',
    blue: 'bg-oe-blue-subtle text-oe-blue-text',
    success: 'bg-semantic-success-bg text-semantic-success',
    warning: 'bg-semantic-warning-bg text-[#b45309]',
    error: 'bg-semantic-error-bg text-semantic-error',
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-medium ${cls[variant]}`}
    >
      {status.replace(/_/g, ' ')}
    </span>
  );
}

function formatTolerance(c: AcceptanceCriterion): string {
  const parts: string[] = [];
  if (c.nominal_value) parts.push(`nominal ${c.nominal_value}`);
  if (c.tolerance_lower) parts.push(`>= ${c.tolerance_lower}`);
  if (c.tolerance_upper) parts.push(`<= ${c.tolerance_upper}`);
  const tol = parts.join(' / ');
  return c.unit ? `${tol}${tol ? ' ' : ''}${c.unit}`.trim() : tol || '-';
}

// ── Create-inspection modal ─────────────────────────────────────────────────

interface CreateForm {
  inspection_type: InspectionType;
  party_role: PartyRole;
  title: string;
  description: string;
  location_description: string;
  criterion_id: string;
  scheduled_at: string;
}

const EMPTY_CREATE: CreateForm = {
  inspection_type: 'wir',
  party_role: 'qc',
  title: '',
  description: '',
  location_description: '',
  criterion_id: '',
  scheduled_at: '',
};

function CreateInspectionModal({
  projectId,
  criteria,
  isPending,
  onClose,
  onSubmit,
}: {
  projectId: string;
  criteria: AcceptanceCriterion[];
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    project_id: string;
    inspection_type: InspectionType;
    party_role: PartyRole;
    title: string;
    description?: string | null;
    location_description?: string | null;
    criterion_id?: string | null;
    scheduled_at?: string | null;
  }) => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<CreateForm>(EMPTY_CREATE);
  const [touched, setTouched] = useState(false);
  const canSubmit = form.title.trim().length > 0;

  const set = <K extends keyof CreateForm>(key: K, value: CreateForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    onSubmit({
      project_id: projectId,
      inspection_type: form.inspection_type,
      party_role: form.party_role,
      title: form.title.trim(),
      description: form.description.trim() || null,
      location_description: form.location_description.trim() || null,
      criterion_id: form.criterion_id || null,
      scheduled_at: form.scheduled_at || null,
    });
  };

  return (
    <ModalShell
      title={t('construction_control.inspection.new', { defaultValue: 'New inspection' })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-insp-type" className={labelCls}>
              {t('construction_control.col.type', { defaultValue: 'Type' })}
            </label>
            <select
              id="cc-insp-type"
              value={form.inspection_type}
              onChange={(e) => set('inspection_type', e.target.value as InspectionType)}
              className={inputCls}
            >
              {INSPECTION_TYPES.map((tType) => (
                <option key={tType} value={tType}>
                  {INSPECTION_TYPE_LABEL[tType]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cc-insp-role" className={labelCls}>
              {t('construction_control.field.party_role', { defaultValue: 'Party role' })}
            </label>
            <select
              id="cc-insp-role"
              value={form.party_role}
              onChange={(e) => set('party_role', e.target.value as PartyRole)}
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
          <label htmlFor="cc-insp-title" className={labelCls}>
            {t('construction_control.col.title', { defaultValue: 'Title' })}
          </label>
          <input
            id="cc-insp-title"
            value={form.title}
            onChange={(e) => set('title', e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.inspection.title_ph', {
              defaultValue: 'e.g. Rebar inspection - Level 2 slab',
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

        <div>
          <label htmlFor="cc-insp-location" className={labelCls}>
            {t('construction_control.field.location', { defaultValue: 'Location' })}
          </label>
          <input
            id="cc-insp-location"
            value={form.location_description}
            onChange={(e) => set('location_description', e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.field.location_ph', {
              defaultValue: 'e.g. Building A, Level 2, Grid C4',
            })}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-insp-criterion" className={labelCls}>
              {t('construction_control.field.criterion', {
                defaultValue: 'Acceptance criterion (optional)',
              })}
            </label>
            <select
              id="cc-insp-criterion"
              value={form.criterion_id}
              onChange={(e) => set('criterion_id', e.target.value)}
              className={inputCls}
            >
              <option value="">
                {t('construction_control.field.no_criterion', { defaultValue: 'No criterion' })}
              </option>
              {criteria.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} - {c.title}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cc-insp-scheduled" className={labelCls}>
              {t('construction_control.field.scheduled_at', { defaultValue: 'Scheduled date' })}
            </label>
            <input
              id="cc-insp-scheduled"
              type="date"
              value={form.scheduled_at}
              onChange={(e) => set('scheduled_at', e.target.value)}
              className={inputCls}
            />
          </div>
        </div>

        <div>
          <label htmlFor="cc-insp-desc" className={labelCls}>
            {t('construction_control.field.description', { defaultValue: 'Description' })}
          </label>
          <textarea
            id="cc-insp-desc"
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('construction_control.field.description_ph', {
              defaultValue: 'What is being inspected and against which scope...',
            })}
          />
        </div>
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
          {t('construction_control.inspection.create', { defaultValue: 'Create inspection' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Record-result modal ─────────────────────────────────────────────────────

const RESULT_OPTIONS: { value: ResultDecision; icon: typeof CheckCircle2; tone: string }[] = [
  { value: 'pass', icon: CheckCircle2, tone: 'text-semantic-success border-semantic-success/40' },
  { value: 'fail', icon: XCircle, tone: 'text-semantic-error border-semantic-error/40' },
  {
    value: 'conditional',
    icon: AlertCircle,
    tone: 'text-[#b45309] border-amber-400/50',
  },
];

function RecordResultModal({
  inspection,
  isPending,
  onClose,
  onSubmit,
}: {
  inspection: Inspection;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (result: ResultDecision, notes: string) => void;
}) {
  const { t } = useTranslation();
  const [result, setResult] = useState<ResultDecision>('pass');
  const [notes, setNotes] = useState('');

  return (
    <ModalShell
      title={t('construction_control.inspection.record_for', {
        defaultValue: 'Record result for {{number}}',
        number: inspection.inspection_number,
      })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <p className="text-sm text-content-secondary">{inspection.title}</p>
        <div>
          <span className={labelCls}>
            {t('construction_control.field.outcome', { defaultValue: 'Outcome' })}
          </span>
          <div className="grid grid-cols-3 gap-2">
            {RESULT_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              const selected = result === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setResult(opt.value)}
                  data-testid={`cc-result-${opt.value}`}
                  className={`flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-3 text-center transition-all ${
                    selected
                      ? `${opt.tone} ring-2 ring-oe-blue/20`
                      : 'border-border bg-surface-primary text-content-tertiary hover:bg-surface-secondary'
                  }`}
                >
                  <Icon className="h-5 w-5" />
                  <span className="text-xs font-medium">
                    {t(`construction_control.result.${opt.value}`, { defaultValue: opt.value })}
                  </span>
                </button>
              );
            })}
          </div>
          {result !== 'pass' && (
            <p className="mt-2 flex items-start gap-1.5 text-xs text-content-tertiary">
              <AlertOctagon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-semantic-error" />
              {t('construction_control.inspection.ncr_hint', {
                defaultValue:
                  'A non-conformance report will be raised automatically and linked to this inspection.',
              })}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="cc-result-notes" className={labelCls}>
            {t('construction_control.field.notes', { defaultValue: 'Notes' })}
          </label>
          <textarea
            id="cc-result-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('construction_control.inspection.notes_ph', {
              defaultValue: 'Observations, measured values, follow-up actions...',
            })}
          />
        </div>
      </div>

      <ModalFooter>
        <Button variant="ghost" onClick={onClose} disabled={isPending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button
          variant="primary"
          onClick={() => onSubmit(result, notes)}
          loading={isPending}
          disabled={isPending}
        >
          {t('construction_control.inspection.save_result', { defaultValue: 'Save result' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Modal primitives (shared local helpers) ──────────────────────────────────

export function ModalShell({
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

export function ModalFooter({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-end gap-3 border-t border-border-light px-6 py-4">
      {children}
    </div>
  );
}
