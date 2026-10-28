// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pillar 4: Handover / acceptance packages (regime-aware taking-over /
// substantial / practical completion).
//
// A handover package turns the project's accumulated control evidence into an
// acceptance dossier and governs issuing the acceptance certificate behind a
// completion gate. This section is the full interactive workflow:
//
//   * list the project's handover packages (master), and select one to inspect,
//   * create a package, choosing the completion regime (FIDIC taking-over /
//     US substantial / UK practical) and completion type,
//   * read the live completion gate for the selected package (open NCRs +
//     unreleased blocking hold gates, and whether the certificate can issue),
//   * assemble the evidence manifest (passed inspections, attested as-builts,
//     accepted materials, passing lab tests),
//   * override a blocked gate with a justification - which raises a documented
//     non-conformance report so issuing over a snag list stays auditable,
//   * issue the acceptance certificate under e-signature (only when the gate is
//     clear or overridden),
//   * revoke an issued certificate.
//
// The completion gate is clear only when there are no open NCRs and no
// unreleased blocking hold gates, unless a manager overrides it.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Plus,
  X,
  PackageCheck,
  Boxes,
  ShieldCheck,
  ShieldAlert,
  Stamp,
  Undo2,
  AlertOctagon,
  CheckCircle2,
  CircleSlash,
} from 'lucide-react';
import { Button, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  listHandoverPackages,
  createHandoverPackage,
  getHandoverGates,
  assembleHandoverPackage,
  overrideHandoverGate,
  issueHandoverCertificate,
  revokeHandoverPackage,
  type HandoverPackage,
  type HandoverGateReport,
  type HandoverCreatePayload,
  type CompletionRegime,
  type CompletionType,
} from '../api';
import { SectionToolbar, StatusBadge, ElementLinks, inputCls, labelCls, textareaCls } from './shared';
import { fmtList } from '@/shared/lib/formatters';
import { useSingleFlight } from '@/shared/hooks/useSingleFlight';

const HANDOVER_STATUS_VARIANTS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  draft: 'neutral',
  assembling: 'blue',
  ready: 'blue',
  issued: 'success',
  revoked: 'error',
};

const GATING_STATE_VARIANTS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  blocked: 'error',
  clear: 'success',
  overridden: 'warning',
};

const COMPLETION_REGIMES: CompletionRegime[] = ['taking_over', 'substantial', 'practical'];
const COMPLETION_TYPES: CompletionType[] = ['whole', 'sectional', 'partial'];

// Regime label = the market acceptance milestone it maps to.
const REGIME_LABEL: Record<CompletionRegime, string> = {
  taking_over: 'Taking-over (FIDIC)',
  substantial: 'Substantial completion (US)',
  practical: 'Practical completion (UK)',
};

const COMPLETION_TYPE_LABEL: Record<CompletionType, string> = {
  whole: 'Whole of the works',
  sectional: 'Sectional completion',
  partial: 'Partial possession',
};

// An issued or revoked package is immutable - mirrors _HANDOVER_LOCKED_STATUSES.
const LOCKED_STATUSES = ['issued', 'revoked'];

interface SectionProps {
  projectId: string;
}

export function HandoverSection({ projectId }: SectionProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [showCreate, setShowCreate] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showOverride, setShowOverride] = useState(false);
  const [showIssue, setShowIssue] = useState(false);

  const packagesQuery = useQuery({
    queryKey: ['cc', 'handover', projectId],
    queryFn: () => listHandoverPackages(projectId),
    enabled: !!projectId,
  });

  const packages = useMemo(() => packagesQuery.data ?? [], [packagesQuery.data]);

  // Keep a sensible selection: default to the first package, and drop a
  // selection that no longer exists (e.g. after a refetch).
  useEffect(() => {
    const first = packages[0];
    if (!first) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!selectedId || !packages.some((p) => p.id === selectedId)) {
      setSelectedId(first.id);
    }
  }, [packages, selectedId]);

  const selected = packages.find((p) => p.id === selectedId) ?? null;

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['cc', 'handover', projectId] });
    if (selectedId) void qc.invalidateQueries({ queryKey: ['cc', 'handover-gates', selectedId] });
  };

  const errorToast = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('common.error', { defaultValue: 'Something went wrong' }),
      message: (e as Error).message,
    });

  const createMutationOnce = useSingleFlight();
  const createMutation = useMutation({
    mutationFn: createHandoverPackage,
    onSuccess: (pkg) => {
      addToast({
        type: 'success',
        title: t('construction_control.handover.created_title', {
          defaultValue: 'Handover package created',
        }),
        message: t('construction_control.handover.created_msg', {
          defaultValue: 'The handover package has been added to this project.',
        }),
      });
      setShowCreate(false);
      setSelectedId(pkg.id);
      invalidate();
    },
    onError: errorToast,
  });

  const assembleMutation = useMutation({
    mutationFn: (packageId: string) => assembleHandoverPackage(packageId),
    onSuccess: (pkg) => {
      addToast({
        type: 'success',
        title: t('construction_control.handover.assembled_title', {
          defaultValue: 'Evidence manifest assembled',
        }),
        message: t('construction_control.handover.assembled_msg', {
          defaultValue: 'Completeness is now {{pct}}%. The completion gate has been recomputed.',
          pct: pkg.completeness_pct,
        }),
      });
      invalidate();
    },
    onError: errorToast,
  });

  const overrideMutation = useMutation({
    mutationFn: ({ packageId, reason }: { packageId: string; reason: string }) =>
      overrideHandoverGate(packageId, { reason }),
    onSuccess: () => {
      addToast({
        type: 'warning',
        title: t('construction_control.handover.overridden_title', {
          defaultValue: 'Gate overridden - NCR raised',
        }),
        message: t('construction_control.handover.overridden_msg', {
          defaultValue:
            'The completion gate was overridden and a documented non-conformance report was raised for the outstanding items.',
        }),
      });
      setShowOverride(false);
      invalidate();
    },
    onError: errorToast,
  });

  const issueMutation = useMutation({
    mutationFn: ({ packageId, certificateNo, notes }: { packageId: string; certificateNo: string; notes: string }) =>
      issueHandoverCertificate(packageId, {
        certificate_no: certificateNo.trim() || null,
        notes: notes.trim() || null,
      }),
    onSuccess: (pkg) => {
      addToast({
        type: 'success',
        title: t('construction_control.handover.issued_title', {
          defaultValue: 'Acceptance certificate issued',
        }),
        message: t('construction_control.handover.issued_msg', {
          defaultValue: 'Certificate {{no}} was issued under e-signature.',
          no: pkg.certificate_no ?? '',
        }),
      });
      setShowIssue(false);
      invalidate();
    },
    onError: errorToast,
  });

  const revokeMutation = useMutation({
    mutationFn: (packageId: string) => revokeHandoverPackage(packageId),
    onSuccess: () => {
      addToast({
        type: 'warning',
        title: t('construction_control.handover.revoked_title', {
          defaultValue: 'Certificate revoked',
        }),
        message: t('construction_control.handover.revoked_msg', {
          defaultValue: 'The acceptance certificate has been revoked.',
        }),
      });
      invalidate();
    },
    onError: errorToast,
  });

  return (
    <div className="space-y-3">
      <SectionToolbar
        title={t('construction_control.handover_heading', {
          defaultValue: 'Handover packages',
        })}
        count={packages.length}
      >
        <Button
          variant="primary"
          size="sm"
          icon={<Plus className="h-4 w-4" />}
          onClick={() => setShowCreate(true)}
        >
          {t('construction_control.handover.new', { defaultValue: 'New package' })}
        </Button>
      </SectionToolbar>

      {packagesQuery.isLoading ? (
        <SkeletonTable rows={4} columns={5} />
      ) : packagesQuery.isError ? (
        <Card>
          <div className="p-6 text-sm text-semantic-error">
            {t('construction_control.handover.load_error', {
              defaultValue: 'Could not load handover packages. Please try again.',
            })}
          </div>
        </Card>
      ) : packages.length === 0 ? (
        <EmptyState
          icon={<PackageCheck size={26} strokeWidth={1.5} />}
          title={t('construction_control.handover.empty_title', {
            defaultValue: 'No handover packages yet',
          })}
          description={t('construction_control.handover.empty_desc', {
            defaultValue:
              'A handover package assembles the acceptance evidence and gates the acceptance certificate behind open NCRs and unreleased hold points.',
          })}
          action={{
            label: t('construction_control.handover.new', { defaultValue: 'New package' }),
            onClick: () => setShowCreate(true),
          }}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
          {/* ── Packages list (master) ───────────────────────────────────── */}
          <div className="lg:col-span-3">
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
                      <th className="px-4 py-2.5 font-medium whitespace-nowrap">
                        {t('construction_control.col.completeness', { defaultValue: 'Completeness' })}
                      </th>
                      <th className="px-4 py-2.5 font-medium">
                        {t('construction_control.col.gate', { defaultValue: 'Gate' })}
                      </th>
                      <th className="px-4 py-2.5 font-medium">
                        {t('construction_control.col.status', { defaultValue: 'Status' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {packages.map((p) => {
                      const isSel = p.id === selectedId;
                      return (
                        <tr
                          key={p.id}
                          onClick={() => setSelectedId(p.id)}
                          data-testid={`cc-handover-row-${p.id}`}
                          aria-selected={isSel}
                          className={`cursor-pointer border-b border-border-light/60 last:border-b-0 align-top transition-colors ${
                            isSel ? 'bg-oe-blue-subtle/60' : 'hover:bg-surface-secondary'
                          }`}
                        >
                          <td className="px-4 py-3 font-mono text-xs text-content-secondary whitespace-nowrap">
                            {p.package_number}
                          </td>
                          <td className="px-4 py-3">
                            <div className="font-medium text-content-primary">{p.title}</div>
                            <div className="text-xs text-content-tertiary">
                              {t(`construction_control.regime.${p.completion_regime}`, {
                                defaultValue: REGIME_LABEL[p.completion_regime],
                              })}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-content-secondary whitespace-nowrap">
                            {p.completeness_pct}%
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex flex-col gap-1">
                              <StatusBadge status={p.gating_state} variants={GATING_STATE_VARIANTS} />
                              {(p.open_ncr_count > 0 || p.unreleased_hold_count > 0) && (
                                <span className="text-2xs text-content-tertiary">
                                  {t('construction_control.handover.blockers', {
                                    defaultValue: '{{ncr}} NCR, {{holds}} holds',
                                    ncr: p.open_ncr_count,
                                    holds: p.unreleased_hold_count,
                                  })}
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <StatusBadge status={p.status} variants={HANDOVER_STATUS_VARIANTS} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>

          {/* ── Selected package detail + actions ────────────────────────── */}
          <div className="lg:col-span-2">
            {selected ? (
              <PackageDetail
                key={selected.id}
                pkg={selected}
                onAssemble={() => assembleMutation.mutate(selected.id)}
                onOverride={() => setShowOverride(true)}
                onIssue={() => setShowIssue(true)}
                onRevoke={() => revokeMutation.mutate(selected.id)}
                assembling={assembleMutation.isPending}
                revoking={revokeMutation.isPending}
              />
            ) : (
              <Card>
                <div className="p-6 text-sm text-content-tertiary">
                  {t('construction_control.handover.select_hint', {
                    defaultValue: 'Select a package to see its completion gate and actions.',
                  })}
                </div>
              </Card>
            )}
          </div>
        </div>
      )}

      {showCreate && (
        <CreatePackageModal
          projectId={projectId}
          isPending={createMutation.isPending}
          onClose={() => setShowCreate(false)}
          onSubmit={(payload) => createMutationOnce(() => createMutation.mutateAsync(payload))}
        />
      )}

      {showOverride && selected && (
        <OverrideGateModal
          pkg={selected}
          isPending={overrideMutation.isPending}
          onClose={() => setShowOverride(false)}
          onSubmit={(reason) => overrideMutation.mutate({ packageId: selected.id, reason })}
        />
      )}

      {showIssue && selected && (
        <IssueCertificateModal
          pkg={selected}
          isPending={issueMutation.isPending}
          onClose={() => setShowIssue(false)}
          onSubmit={(certificateNo, notes) =>
            issueMutation.mutate({ packageId: selected.id, certificateNo, notes })
          }
        />
      )}
    </div>
  );
}

// ── Selected-package detail (gate report + action buttons) ───────────────────

function PackageDetail({
  pkg,
  onAssemble,
  onOverride,
  onIssue,
  onRevoke,
  assembling,
  revoking,
}: {
  pkg: HandoverPackage;
  onAssemble: () => void;
  onOverride: () => void;
  onIssue: () => void;
  onRevoke: () => void;
  assembling: boolean;
  revoking: boolean;
}) {
  const { t } = useTranslation();

  const gatesQuery = useQuery({
    queryKey: ['cc', 'handover-gates', pkg.id],
    queryFn: () => getHandoverGates(pkg.id),
  });
  const gate = gatesQuery.data;

  const isLocked = LOCKED_STATUSES.includes(pkg.status);
  // The gate report is authoritative when present; the package row is the fallback.
  const canIssue = gate ? gate.can_issue : pkg.gating_state === 'clear' || pkg.gating_state === 'overridden';
  const gatingState = gate?.gating_state ?? pkg.gating_state;
  const canOverride = !isLocked && gatingState !== 'clear' && gatingState !== 'overridden';

  return (
    <Card>
      <div className="space-y-4 p-5">
        <div>
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-base font-semibold text-content-primary">{pkg.title}</h3>
            <StatusBadge status={pkg.status} variants={HANDOVER_STATUS_VARIANTS} />
          </div>
          <p className="mt-0.5 font-mono text-xs text-content-tertiary">{pkg.package_number}</p>
          <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-content-secondary">
            <span>
              {t(`construction_control.regime.${pkg.completion_regime}`, {
                defaultValue: REGIME_LABEL[pkg.completion_regime],
              })}
            </span>
            <span aria-hidden className="h-1 w-1 rounded-full bg-content-tertiary" />
            <span>
              {t(`construction_control.completion_type.${pkg.completion_type}`, {
                defaultValue: COMPLETION_TYPE_LABEL[pkg.completion_type],
              })}
            </span>
          </p>
          {pkg.section_ref && (
            <p className="mt-0.5 text-xs text-content-tertiary">
              {t('construction_control.field.section_ref', { defaultValue: 'Section' })}: {pkg.section_ref}
            </p>
          )}
          {pkg.elements.length > 0 && (
            <div className="mt-2">
              <ElementLinks elements={pkg.elements} />
            </div>
          )}
        </div>

        {/* ── Completion gate report ─────────────────────────────────────── */}
        <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('construction_control.handover.gate_report', { defaultValue: 'Completion gate' })}
            </span>
            <StatusBadge status={gatingState} variants={GATING_STATE_VARIANTS} />
          </div>

          {gatesQuery.isLoading ? (
            <p className="text-xs text-content-tertiary">
              {t('construction_control.handover.gate_loading', { defaultValue: 'Checking the gate...' })}
            </p>
          ) : gatesQuery.isError ? (
            <p className="text-xs text-semantic-error">
              {t('construction_control.handover.gate_error', {
                defaultValue: 'Could not load the completion gate.',
              })}
            </p>
          ) : (
            <GateBody gate={gate} pkg={pkg} canIssue={canIssue} />
          )}
        </div>

        {/* ── Actions ────────────────────────────────────────────────────── */}
        <div className="flex flex-wrap gap-2" data-testid="cc-handover-actions">
          {!isLocked && (
            <Button
              variant="secondary"
              size="sm"
              icon={<Boxes className="h-4 w-4" />}
              onClick={onAssemble}
              loading={assembling}
              disabled={assembling}
              data-testid="cc-handover-assemble"
            >
              {t('construction_control.handover.assemble', { defaultValue: 'Assemble manifest' })}
            </Button>
          )}

          {canOverride && (
            <Button
              variant="secondary"
              size="sm"
              icon={<ShieldAlert className="h-4 w-4" />}
              onClick={onOverride}
              data-testid="cc-handover-override"
            >
              {t('construction_control.handover.override', { defaultValue: 'Override gate' })}
            </Button>
          )}

          {!isLocked && (
            <Button
              variant="primary"
              size="sm"
              icon={<Stamp className="h-4 w-4" />}
              onClick={onIssue}
              disabled={!canIssue}
              title={
                canIssue
                  ? undefined
                  : t('construction_control.handover.issue_blocked_hint', {
                      defaultValue: 'Clear or override the completion gate before issuing.',
                    })
              }
              data-testid="cc-handover-issue"
            >
              {t('construction_control.handover.issue', { defaultValue: 'Issue certificate' })}
            </Button>
          )}

          {pkg.status === 'issued' && (
            <Button
              variant="ghost"
              size="sm"
              icon={<Undo2 className="h-4 w-4" />}
              onClick={onRevoke}
              loading={revoking}
              disabled={revoking}
              data-testid="cc-handover-revoke"
            >
              {t('construction_control.handover.revoke', { defaultValue: 'Revoke' })}
            </Button>
          )}
        </div>

        {pkg.status === 'issued' && pkg.certificate_no && (
          <div className="flex items-start gap-2 rounded-lg border border-semantic-success/30 bg-semantic-success-bg/50 p-3 text-xs text-content-secondary">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-semantic-success" />
            <div>
              <div className="font-medium text-content-primary">
                {t('construction_control.handover.certificate_issued', {
                  defaultValue: 'Certificate {{no}} issued',
                  no: pkg.certificate_no,
                })}
              </div>
              {pkg.issue_signature_sha256 && (
                <div className="mt-0.5 font-mono text-2xs text-content-tertiary break-all">
                  {t('construction_control.handover.esign_ref', { defaultValue: 'E-signature' })}:{' '}
                  {pkg.issue_signature_sha256.slice(0, 16)}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

function GateBody({
  gate,
  pkg,
  canIssue,
}: {
  gate: HandoverGateReport | undefined;
  pkg: HandoverPackage;
  canIssue: boolean;
}) {
  const { t } = useTranslation();
  const openNcr = gate?.open_ncr_count ?? pkg.open_ncr_count;
  const holds = gate?.unreleased_hold_count ?? pkg.unreleased_hold_count;
  const completeness = gate?.completeness_pct ?? pkg.completeness_pct;
  const blockingNumbers = gate?.blocking_gate_numbers ?? [];

  return (
    <div className="space-y-2 text-xs">
      <GateRow
        ok={openNcr === 0}
        label={t('construction_control.handover.open_ncrs', {
          defaultValue: 'Open NCRs',
        })}
        value={String(openNcr)}
      />
      <GateRow
        ok={holds === 0}
        label={t('construction_control.handover.unreleased_holds', {
          defaultValue: 'Unreleased hold gates',
        })}
        value={String(holds)}
      />
      {blockingNumbers.length > 0 && (
        <p className="pl-6 text-2xs text-content-tertiary">
          {t('construction_control.handover.blocking_gates', {
            defaultValue: 'Blocking: {{gates}}',
            gates: fmtList(blockingNumbers),
          })}
        </p>
      )}
      <div className="flex items-center justify-between pt-1 text-content-secondary">
        <span>{t('construction_control.col.completeness', { defaultValue: 'Completeness' })}</span>
        <span className="font-medium">{completeness}%</span>
      </div>

      <div
        className={`mt-1 flex items-center gap-1.5 rounded-md px-2 py-1.5 ${
          canIssue ? 'bg-semantic-success-bg text-semantic-success' : 'bg-semantic-warning-bg text-[#b45309]'
        }`}
      >
        {canIssue ? <CheckCircle2 className="h-3.5 w-3.5" /> : <CircleSlash className="h-3.5 w-3.5" />}
        <span className="font-medium">
          {canIssue
            ? t('construction_control.handover.can_issue', { defaultValue: 'Ready to issue' })
            : t('construction_control.handover.cannot_issue', {
                defaultValue: 'Blocked - clear or override the gate to issue',
              })}
        </span>
      </div>
    </div>
  );
}

function GateRow({ ok, label, value }: { ok: boolean; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="flex items-center gap-2 text-content-secondary">
        {ok ? (
          <CheckCircle2 className="h-4 w-4 text-semantic-success" />
        ) : (
          <AlertOctagon className="h-4 w-4 text-semantic-error" />
        )}
        {label}
      </span>
      <span className={`font-medium ${ok ? 'text-content-secondary' : 'text-semantic-error'}`}>{value}</span>
    </div>
  );
}

// ── Create-package modal ─────────────────────────────────────────────────────

interface CreateForm {
  title: string;
  completion_regime: CompletionRegime;
  completion_type: CompletionType;
  section_ref: string;
}

const EMPTY_CREATE: CreateForm = {
  title: '',
  completion_regime: 'taking_over',
  completion_type: 'whole',
  section_ref: '',
};

function CreatePackageModal({
  projectId,
  isPending,
  onClose,
  onSubmit,
}: {
  projectId: string;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (payload: HandoverCreatePayload) => void;
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
      title: form.title.trim(),
      completion_regime: form.completion_regime,
      completion_type: form.completion_type,
      section_ref: form.section_ref.trim() || null,
    });
  };

  return (
    <ModalShell
      title={t('construction_control.handover.new', { defaultValue: 'New package' })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <div>
          <label htmlFor="cc-ho-title" className={labelCls}>
            {t('construction_control.col.title', { defaultValue: 'Title' })}
          </label>
          <input
            id="cc-ho-title"
            value={form.title}
            onChange={(e) => set('title', e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.handover.title_ph', {
              defaultValue: 'e.g. Taking-over - Building A',
            })}
          />
          {touched && !canSubmit && (
            <p className="mt-1 text-xs text-semantic-error">
              {t('construction_control.field.title_required', { defaultValue: 'A title is required.' })}
            </p>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="cc-ho-regime" className={labelCls}>
              {t('construction_control.field.completion_regime', {
                defaultValue: 'Completion regime',
              })}
            </label>
            <select
              id="cc-ho-regime"
              value={form.completion_regime}
              onChange={(e) => set('completion_regime', e.target.value as CompletionRegime)}
              className={inputCls}
            >
              {COMPLETION_REGIMES.map((r) => (
                <option key={r} value={r}>
                  {t(`construction_control.regime.${r}`, { defaultValue: REGIME_LABEL[r] })}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="cc-ho-type" className={labelCls}>
              {t('construction_control.field.completion_type', { defaultValue: 'Completion type' })}
            </label>
            <select
              id="cc-ho-type"
              value={form.completion_type}
              onChange={(e) => set('completion_type', e.target.value as CompletionType)}
              className={inputCls}
            >
              {COMPLETION_TYPES.map((ct) => (
                <option key={ct} value={ct}>
                  {t(`construction_control.completion_type.${ct}`, {
                    defaultValue: COMPLETION_TYPE_LABEL[ct],
                  })}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label htmlFor="cc-ho-section" className={labelCls}>
            {t('construction_control.field.section_ref_optional', {
              defaultValue: 'Section reference (optional)',
            })}
          </label>
          <input
            id="cc-ho-section"
            value={form.section_ref}
            onChange={(e) => set('section_ref', e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.field.section_ref_ph', {
              defaultValue: 'e.g. Section 2 - East wing',
            })}
          />
          <p className="mt-1 text-xs text-content-tertiary">
            {t('construction_control.handover.section_hint', {
              defaultValue: 'Used for sectional or partial completion of part of the works.',
            })}
          </p>
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
          {t('construction_control.handover.create', { defaultValue: 'Create package' })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Override-gate modal (raises a documented NCR) ────────────────────────────

function OverrideGateModal({
  pkg,
  isPending,
  onClose,
  onSubmit,
}: {
  pkg: HandoverPackage;
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
      title={t('construction_control.handover.override_title', {
        defaultValue: 'Override completion gate',
      })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <div className="flex items-start gap-2 rounded-lg border border-amber-400/50 bg-semantic-warning-bg/60 p-3 text-xs text-[#b45309]">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            {t('construction_control.handover.override_warning', {
              defaultValue:
                'Overriding lets the certificate issue over outstanding items (a snag list). This raises a documented non-conformance report capturing the open blockers, so the decision stays auditable.',
            })}
          </div>
        </div>

        <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3 text-xs text-content-secondary">
          {t('construction_control.handover.override_outstanding', {
            defaultValue: 'Outstanding now: {{ncr}} open NCR(s), {{holds}} unreleased hold gate(s).',
            ncr: pkg.open_ncr_count,
            holds: pkg.unreleased_hold_count,
          })}
        </div>

        <div>
          <label htmlFor="cc-ho-override-reason" className={labelCls}>
            {t('construction_control.field.justification', { defaultValue: 'Justification' })}
          </label>
          <textarea
            id="cc-ho-override-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={4}
            className={textareaCls}
            placeholder={t('construction_control.handover.override_reason_ph', {
              defaultValue: 'Why the works can be taken over despite the outstanding items...',
            })}
          />
          {touched && !canSubmit && (
            <p className="mt-1 text-xs text-semantic-error">
              {t('construction_control.handover.override_reason_required', {
                defaultValue: 'A justification is required to override the gate.',
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
          variant="primary"
          onClick={handleSubmit}
          loading={isPending}
          disabled={isPending || !canSubmit}
          icon={<ShieldAlert className="h-4 w-4" />}
        >
          {t('construction_control.handover.override_confirm', {
            defaultValue: 'Override and raise NCR',
          })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Issue-certificate modal (e-signed) ───────────────────────────────────────

function IssueCertificateModal({
  pkg,
  isPending,
  onClose,
  onSubmit,
}: {
  pkg: HandoverPackage;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (certificateNo: string, notes: string) => void;
}) {
  const { t } = useTranslation();
  const [certificateNo, setCertificateNo] = useState(pkg.certificate_no ?? '');
  const [notes, setNotes] = useState('');

  return (
    <ModalShell
      title={t('construction_control.handover.issue_title', {
        defaultValue: 'Issue acceptance certificate',
      })}
      onClose={onClose}
    >
      <div className="space-y-4 px-6 py-4">
        <div className="flex items-start gap-2 rounded-lg border border-semantic-success/30 bg-semantic-success-bg/50 p-3 text-xs text-content-secondary">
          <Stamp className="mt-0.5 h-4 w-4 shrink-0 text-semantic-success" />
          <div>
            {t('construction_control.handover.issue_intro', {
              defaultValue:
                'Issuing records an e-signature (signer, time, IP and a SHA-256 over a snapshot of the package) and locks the package. The gate is re-checked at issue.',
            })}
          </div>
        </div>

        <div>
          <label htmlFor="cc-ho-cert-no" className={labelCls}>
            {t('construction_control.field.certificate_no', {
              defaultValue: 'Certificate number (optional)',
            })}
          </label>
          <input
            id="cc-ho-cert-no"
            value={certificateNo}
            onChange={(e) => setCertificateNo(e.target.value)}
            className={inputCls}
            placeholder={t('construction_control.handover.cert_no_ph', {
              defaultValue: 'Leave blank to auto-number',
            })}
          />
        </div>

        <div>
          <label htmlFor="cc-ho-issue-notes" className={labelCls}>
            {t('construction_control.field.notes', { defaultValue: 'Notes' })}
          </label>
          <textarea
            id="cc-ho-issue-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className={textareaCls}
            placeholder={t('construction_control.handover.issue_notes_ph', {
              defaultValue: 'Any conditions noted on the certificate...',
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
          onClick={() => onSubmit(certificateNo, notes)}
          loading={isPending}
          disabled={isPending}
          icon={<Stamp className="h-4 w-4" />}
        >
          {t('construction_control.handover.issue_confirm', {
            defaultValue: 'Sign and issue',
          })}
        </Button>
      </ModalFooter>
    </ModalShell>
  );
}

// ── Modal primitives (local, inlined per file-ownership rule) ────────────────

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

export default HandoverSection;
