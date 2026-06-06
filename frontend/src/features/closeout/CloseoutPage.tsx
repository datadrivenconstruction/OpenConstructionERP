import { useMemo, useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  PackageCheck,
  CheckCircle2,
  Circle,
  CircleDot,
  Sparkles,
  Download,
  Hammer,
  Trash2,
  Link2,
  ShieldCheck,
  Loader2,
  AlertTriangle,
} from 'lucide-react';
import {
  Card,
  Badge,
  Button,
  Breadcrumb,
  DismissibleInfo,
  EmptyState,
  Skeleton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  getCloseoutPackage,
  createCloseoutPackage,
  bindSlot,
  unbindSlot,
  verifySlot,
  buildPackage,
  getJob,
  suggestBindings,
  downloadPackage,
  triggerBlobDownload,
  type CloseoutSlot,
  type SlotStatus,
  type BindingSuggestion,
  type CloseoutProjectType,
} from './api';
import BindDocumentModal from './BindDocumentModal';

const PROJECT_TYPES: CloseoutProjectType[] = [
  'commercial',
  'residential',
  'infrastructure',
  'fitout',
  'custom',
];

function statusBadge(status: SlotStatus, t: (k: string, o?: Record<string, unknown>) => string) {
  if (status === 'verified') {
    return (
      <Badge variant="success" size="sm">
        {t('closeout.status.verified', { defaultValue: 'Verified' })}
      </Badge>
    );
  }
  if (status === 'bound') {
    return (
      <Badge variant="blue" size="sm">
        {t('closeout.status.bound', { defaultValue: 'Bound' })}
      </Badge>
    );
  }
  return (
    <Badge variant="neutral" size="sm">
      {t('closeout.status.empty', { defaultValue: 'Empty' })}
    </Badge>
  );
}

function StatusIcon({ status }: { status: SlotStatus }) {
  if (status === 'verified') return <CheckCircle2 className="h-4 w-4 text-semantic-success" />;
  if (status === 'bound') return <CircleDot className="h-4 w-4 text-oe-blue" />;
  return <Circle className="h-4 w-4 text-content-tertiary" />;
}

export default function CloseoutPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [bindSlotTarget, setBindSlotTarget] = useState<CloseoutSlot | null>(null);
  const [suggestions, setSuggestions] = useState<BindingSuggestion[] | null>(null);
  const [buildJobId, setBuildJobId] = useState<string | null>(null);
  const [buildProgress, setBuildProgress] = useState<number>(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const packageQuery = useQuery({
    queryKey: ['closeout-package', activeProjectId],
    queryFn: () => getCloseoutPackage(activeProjectId as string),
    enabled: !!activeProjectId,
    retry: (failureCount, error) => {
      // 404 = no package created yet; do not retry that.
      const msg = (error as Error)?.message ?? '';
      if (msg.includes('404') || msg.toLowerCase().includes('no closeout package')) return false;
      return failureCount < 2;
    },
  });

  const pkg = packageQuery.data;
  const notFound =
    packageQuery.isError &&
    ((packageQuery.error as Error)?.message ?? '').toLowerCase().includes('closeout package');

  const refetchPackage = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['closeout-package', activeProjectId] });
  }, [qc, activeProjectId]);

  const createMutation = useMutation({
    mutationFn: (projectType: CloseoutProjectType) =>
      createCloseoutPackage(activeProjectId as string, projectType),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('closeout.toast.created', { defaultValue: 'Closeout package created' }),
      });
      refetchPackage();
    },
    onError: (e) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: (e as Error).message }),
  });

  const bindMutation = useMutation({
    mutationFn: (args: {
      slotId: string;
      payload: { document_id?: string | null; external_url?: string | null; mark_verified: boolean };
    }) => bindSlot(args.slotId, args.payload),
    onSuccess: () => {
      addToast({ type: 'success', title: t('closeout.toast.bound', { defaultValue: 'Evidence bound' }) });
      setBindSlotTarget(null);
      refetchPackage();
    },
    onError: (e) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: (e as Error).message }),
  });

  const unbindMutation = useMutation({
    mutationFn: (slotId: string) => unbindSlot(slotId),
    onSuccess: () => refetchPackage(),
    onError: (e) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: (e as Error).message }),
  });

  const verifyMutation = useMutation({
    mutationFn: (args: { slotId: string; verified: boolean }) => verifySlot(args.slotId, args.verified),
    onSuccess: () => refetchPackage(),
    onError: (e) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: (e as Error).message }),
  });

  const suggestMutation = useMutation({
    mutationFn: () => suggestBindings(pkg!.id),
    onSuccess: (res) => {
      setSuggestions(res.suggestions);
      if (res.suggestions.length === 0) {
        addToast({
          type: 'info',
          title: t('closeout.toast.no_suggestions', { defaultValue: 'No matching documents found' }),
        });
      }
    },
    onError: (e) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: (e as Error).message }),
  });

  const downloadMutation = useMutation({
    mutationFn: () => downloadPackage(pkg!.id),
    onSuccess: ({ blob, filename }) => triggerBlobDownload(blob, filename),
    onError: (e) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: (e as Error).message }),
  });

  // ── Build job + polling ───────────────────────────────────────────────
  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const buildMutation = useMutation({
    mutationFn: () => buildPackage(pkg!.id),
    onSuccess: (res) => {
      setBuildJobId(res.job_id);
      setBuildProgress(res.progress_percent || 0);
      stopPolling();
      pollRef.current = setInterval(async () => {
        try {
          const job = await getJob(res.job_id);
          setBuildProgress(job.progress_percent || 0);
          if (job.status === 'success') {
            stopPolling();
            setBuildJobId(null);
            addToast({
              type: 'success',
              title: t('closeout.toast.built', { defaultValue: 'Closeout package built' }),
            });
            refetchPackage();
          } else if (job.status === 'failed' || job.status === 'cancelled') {
            stopPolling();
            setBuildJobId(null);
            addToast({
              type: 'error',
              title: t('closeout.toast.build_failed', { defaultValue: 'Build failed' }),
            });
          }
        } catch {
          // Transient poll error; keep polling.
        }
      }, 1500);
    },
    onError: (e) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: (e as Error).message }),
  });

  const confirmSuggestion = useCallback(
    async (s: BindingSuggestion) => {
      await bindMutation.mutateAsync({
        slotId: s.slot_id,
        payload: { document_id: s.document_id, mark_verified: false },
      });
      setSuggestions((prev) => (prev ? prev.filter((x) => x.slot_id !== s.slot_id) : prev));
    },
    [bindMutation],
  );

  // ── Group slots by category for the checklist table ────────────────────
  const grouped = useMemo(() => {
    const map = new Map<string, CloseoutSlot[]>();
    (pkg?.slots ?? [])
      .slice()
      .sort((a, b) => a.ordinal - b.ordinal)
      .forEach((s) => {
        const arr = map.get(s.category) ?? [];
        arr.push(s);
        map.set(s.category, arr);
      });
    return Array.from(map.entries());
  }, [pkg?.slots]);

  const categoryLabel = (cat: string) =>
    t(`closeout.category.${cat}`, {
      defaultValue: cat.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
    });

  // ── Readiness chips for the two cross-module gates (CONN-59) ────────────
  // `punch_closure` and `final_inspection_cert` are generated from the Punch
  // List and Inspections registers respectively. Surface their readiness as
  // chips that deep-link to the owning module, and a warning when a required
  // gate is not yet satisfied before a build.
  const readinessChips = useMemo(() => {
    const slots = pkg?.slots ?? [];
    const find = (key: string) => slots.find((s) => s.slot_key === key);
    const chips: {
      key: string;
      label: string;
      slot: CloseoutSlot | undefined;
      to: string;
    }[] = [];
    const punch = find('punch_closure');
    if (punch) {
      chips.push({
        key: 'punch_closure',
        label: t('closeout.chip_punch', { defaultValue: 'Punch closure' }),
        slot: punch,
        to: '/punchlist',
      });
    }
    const inspection = find('final_inspection_cert');
    if (inspection) {
      chips.push({
        key: 'final_inspection_cert',
        label: t('closeout.chip_final_inspection', { defaultValue: 'Final inspection' }),
        slot: inspection,
        to: '/inspections',
      });
    }
    return chips;
  }, [pkg?.slots, t]);

  // A required readiness gate that is still empty blocks a clean build.
  const readinessGap = readinessChips.some(
    (c) => c.slot?.is_required && c.slot.status === 'empty',
  );

  // ── Render: no project selected ────────────────────────────────────────
  if (!activeProjectId) {
    return (
      <div className="space-y-5 animate-fade-in">
        <Breadcrumb items={[{ label: t('closeout.title', { defaultValue: 'Handover & Closeout' }) }]} />
        <PageHeader srTitle={t('closeout.title', { defaultValue: 'Handover & Closeout' })} />
        <EmptyState
          icon={<PackageCheck className="h-8 w-8" />}
          title={t('closeout.no_project', { defaultValue: 'Select a project' })}
          description={t('closeout.no_project_desc', {
            defaultValue: 'Pick a project to assemble its handover and closeout package.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[{ label: t('closeout.title', { defaultValue: 'Handover & Closeout' }) }]} />
      <PageHeader
        srTitle={t('closeout.title', { defaultValue: 'Handover & Closeout' })}
        subtitle={
          packageQuery.isLoading
            ? t('common.loading', { defaultValue: 'Loading' })
            : pkg
              ? t('closeout.subtitle_count', {
                  defaultValue: '{{delivered}} of {{required}} required items complete',
                  delivered: pkg.delivered_slot_count,
                  required: pkg.required_slot_count,
                })
              : t('closeout.subtitle_empty', {
                  defaultValue: 'Assemble the digital handover package for this project',
                })
        }
        actions={
          pkg ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                icon={<Sparkles size={14} />}
                onClick={() => suggestMutation.mutate()}
                loading={suggestMutation.isPending}
              >
                {t('closeout.action.suggest', { defaultValue: 'Auto-suggest evidence' })}
              </Button>
              <Button
                variant={pkg.ready ? 'primary' : 'secondary'}
                size="sm"
                icon={buildJobId ? <Loader2 size={14} className="animate-spin" /> : <Hammer size={14} />}
                onClick={() => buildMutation.mutate()}
                loading={buildMutation.isPending}
                disabled={!!buildJobId}
              >
                {buildJobId
                  ? t('closeout.action.building', {
                      defaultValue: 'Building {{pct}}%',
                      pct: buildProgress,
                    })
                  : t('closeout.action.build', { defaultValue: 'Build package' })}
              </Button>
              {pkg.has_built_package ? (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Download size={14} />}
                  onClick={() => downloadMutation.mutate()}
                  loading={downloadMutation.isPending}
                >
                  {t('closeout.action.download', { defaultValue: 'Download package' })}
                </Button>
              ) : null}
            </>
          ) : undefined
        }
      />

      <DismissibleInfo
        storageKey="closeout"
        title={t('closeout.intro_title', {
          defaultValue: 'Every handover document in one verified package',
        })}
        links={[
          { label: t('nav.documents', { defaultValue: 'Documents' }), onClick: () => navigate('/documents') },
          { label: t('nav.punchlist', { defaultValue: 'Punch list' }), onClick: () => navigate('/punchlist') },
          { label: t('nav.inspections', { defaultValue: 'Inspections' }), onClick: () => navigate('/inspections') },
        ]}
      >
        {t('closeout.intro_body', {
          defaultValue:
            'Bind as-built drawings, O&M manuals, warranties, the COBie asset register, punch closure and final inspection certificates into a single checklist. Track completeness, close the gaps, then build one structured ZIP with a PDF cover and a machine-readable manifest to hand to the client.',
        })}
      </DismissibleInfo>

      {/* ── No package yet: offer to create from a project type ─────────── */}
      {!pkg && !packageQuery.isLoading && notFound ? (
        <Card className="p-6">
          <div className="flex flex-col items-center gap-4 text-center">
            <PackageCheck className="h-10 w-10 text-oe-blue" />
            <div>
              <h3 className="text-base font-semibold text-content-primary">
                {t('closeout.create_title', { defaultValue: 'Start a closeout package' })}
              </h3>
              <p className="mt-1 text-sm text-content-tertiary">
                {t('closeout.create_desc', {
                  defaultValue:
                    'Pick the project type to seed the right handover checklist. You can add or remove items afterwards.',
                })}
              </p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              {PROJECT_TYPES.map((pt) => (
                <Button
                  key={pt}
                  variant="secondary"
                  size="sm"
                  onClick={() => createMutation.mutate(pt)}
                  loading={createMutation.isPending && createMutation.variables === pt}
                >
                  {t(`closeout.project_type.${pt}`, {
                    defaultValue: pt.charAt(0).toUpperCase() + pt.slice(1),
                  })}
                </Button>
              ))}
            </div>
          </div>
        </Card>
      ) : null}

      {packageQuery.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : null}

      {pkg ? (
        <>
          {/* ── Completeness ring / banner ──────────────────────────────── */}
          <Card className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <div
                  className={`flex h-16 w-16 shrink-0 items-center justify-center rounded-full text-lg font-bold text-white ${
                    pkg.ready
                      ? 'bg-semantic-success'
                      : pkg.completeness_pct >= 50
                        ? 'bg-amber-500'
                        : 'bg-semantic-error'
                  }`}
                >
                  {pkg.completeness_pct}%
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    {pkg.ready ? (
                      <Badge variant="success">
                        {t('closeout.ready', { defaultValue: 'Ready for handover' })}
                      </Badge>
                    ) : (
                      <Badge variant="warning">
                        {t('closeout.not_ready', {
                          defaultValue: '{{count}} required item(s) outstanding',
                          count: pkg.gaps.length,
                        })}
                      </Badge>
                    )}
                  </div>
                  <p className="mt-1 text-sm text-content-tertiary">
                    {t('closeout.completeness_line', {
                      defaultValue: '{{delivered}} of {{required}} required items delivered',
                      delivered: pkg.delivered_slot_count,
                      required: pkg.required_slot_count,
                    })}
                  </p>
                </div>
              </div>
              {pkg.last_built_at ? (
                <p className="text-xs text-content-tertiary">
                  {t('closeout.last_built', {
                    defaultValue: 'Last built {{when}}',
                    when: pkg.last_built_at,
                  })}
                </p>
              ) : null}
            </div>

            {/* ── Cross-module readiness chips ──────────────────────────── */}
            {readinessChips.length > 0 ? (
              <div className="mt-4 border-t border-border pt-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-content-tertiary">
                    {t('closeout.readiness_label', { defaultValue: 'Readiness' })}:
                  </span>
                  {readinessChips.map((chip) => {
                    const status = chip.slot?.status ?? 'empty';
                    const ready = status === 'verified' || status === 'bound';
                    return (
                      <button
                        key={chip.key}
                        type="button"
                        onClick={() => navigate(chip.to)}
                        title={t('closeout.readiness_open_hint', {
                          defaultValue: 'Open the source module to close this gate',
                        })}
                        className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                      >
                        {ready ? (
                          <CheckCircle2 className="h-3.5 w-3.5 text-semantic-success" />
                        ) : (
                          <Circle className="h-3.5 w-3.5 text-content-tertiary" />
                        )}
                        {chip.label}
                        <Badge variant={ready ? 'success' : 'neutral'} size="sm">
                          {ready
                            ? t('closeout.readiness_ready', { defaultValue: 'Ready' })
                            : t('closeout.readiness_outstanding', { defaultValue: 'Outstanding' })}
                        </Badge>
                      </button>
                    );
                  })}
                </div>
                {readinessGap ? (
                  <p className="mt-2 flex items-center gap-1.5 text-xs text-semantic-warning">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                    {t('closeout.readiness_build_warn', {
                      defaultValue:
                        'Punch closure or the final inspection certificate is still outstanding - close these before you build the package.',
                    })}
                  </p>
                ) : null}
              </div>
            ) : null}
          </Card>

          {/* ── Gap panel ──────────────────────────────────────────────── */}
          {pkg.gaps.length > 0 ? (
            <Card className="border-semantic-error/40 bg-semantic-error/5 p-4">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-semantic-error" />
                <div>
                  <h4 className="text-sm font-semibold text-semantic-error">
                    {t('closeout.gaps_title', { defaultValue: 'Outstanding required items' })}
                  </h4>
                  <ul className="mt-1 list-disc pl-5 text-sm text-content-secondary">
                    {pkg.gaps.map((g) => (
                      <li key={g}>{g}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </Card>
          ) : null}

          {/* ── AI suggestions ─────────────────────────────────────────── */}
          {suggestions && suggestions.length > 0 ? (
            <Card className="border-oe-blue/30 bg-oe-blue/5 p-4">
              <div className="mb-2 flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-oe-blue" />
                <h4 className="text-sm font-semibold text-content-primary">
                  {t('closeout.suggestions_title', { defaultValue: 'Suggested evidence (confirm each)' })}
                </h4>
              </div>
              <div className="space-y-2">
                {suggestions.map((s) => (
                  <div
                    key={s.slot_id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface-primary px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm text-content-primary">{s.document_name}</p>
                      <p className="text-xs text-content-tertiary">{s.reason}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <Badge variant="blue" size="sm">
                        {Math.round(s.confidence * 100)}%
                      </Badge>
                      <Button size="sm" variant="primary" onClick={() => confirmSuggestion(s)}>
                        {t('closeout.confirm_suggestion', { defaultValue: 'Confirm' })}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          ) : null}

          {/* ── Checklist grouped by category ──────────────────────────── */}
          <div className="space-y-4">
            {grouped.map(([cat, slots]) => (
              <Card key={cat} className="overflow-hidden">
                <div className="border-b border-border bg-surface-secondary px-4 py-2 text-sm font-semibold text-content-primary">
                  {categoryLabel(cat)}
                </div>
                <div className="divide-y divide-border">
                  {slots.map((slot) => (
                    <div key={slot.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                      <StatusIcon status={slot.status} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium text-content-primary">
                            {slot.title}
                          </span>
                          {slot.is_required ? (
                            <Badge variant="neutral" size="sm">
                              {t('closeout.required', { defaultValue: 'Required' })}
                            </Badge>
                          ) : null}
                          {slot.source_kind === 'generated' ? (
                            <Badge variant="blue" size="sm">
                              {t('closeout.generated', { defaultValue: 'Auto-generated' })}
                            </Badge>
                          ) : null}
                        </div>
                        {slot.binding ? (
                          <p className="mt-0.5 truncate text-xs text-content-tertiary">
                            {slot.binding.document_name ||
                              slot.binding.external_url ||
                              t('closeout.evidence_bound', { defaultValue: 'Evidence bound' })}
                            {slot.binding.verified_at
                              ? ` - ${t('closeout.verified_on', {
                                  defaultValue: 'verified {{when}}',
                                  when: slot.binding.verified_at,
                                })}`
                              : ''}
                          </p>
                        ) : null}
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {statusBadge(slot.status, t)}
                        {slot.source_kind !== 'generated' ? (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              icon={<Link2 size={13} />}
                              onClick={() => setBindSlotTarget(slot)}
                            >
                              {slot.binding
                                ? t('closeout.action.rebind', { defaultValue: 'Rebind' })
                                : t('closeout.action.bind', { defaultValue: 'Bind' })}
                            </Button>
                            {slot.binding ? (
                              <Button
                                size="sm"
                                variant={slot.status === 'verified' ? 'secondary' : 'ghost'}
                                icon={<ShieldCheck size={13} />}
                                onClick={() =>
                                  verifyMutation.mutate({
                                    slotId: slot.id,
                                    verified: slot.status !== 'verified',
                                  })
                                }
                              >
                                {slot.status === 'verified'
                                  ? t('closeout.action.unverify', { defaultValue: 'Unverify' })
                                  : t('closeout.action.verify', { defaultValue: 'Verify' })}
                              </Button>
                            ) : null}
                            {slot.binding ? (
                              <Button
                                size="sm"
                                variant="ghost"
                                icon={<Trash2 size={13} />}
                                onClick={() => unbindMutation.mutate(slot.id)}
                                aria-label={t('closeout.action.unbind', { defaultValue: 'Unbind' })}
                              />
                            ) : null}
                          </>
                        ) : (
                          <span className="text-xs text-content-tertiary">
                            {t('closeout.generated_hint', {
                              defaultValue: 'Generated when you build',
                            })}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            ))}
          </div>
        </>
      ) : null}

      {bindSlotTarget ? (
        <BindDocumentModal
          open={!!bindSlotTarget}
          projectId={activeProjectId}
          slot={bindSlotTarget}
          onClose={() => setBindSlotTarget(null)}
          saving={bindMutation.isPending}
          onBind={async (payload) => {
            await bindMutation.mutateAsync({ slotId: bindSlotTarget.id, payload });
          }}
        />
      ) : null}
    </div>
  );
}
