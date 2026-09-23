// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import React, { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import {
  Route,
  Sparkles,
  Save,
  Pencil,
  Trash2,
  ShieldCheck,
  CheckCircle2,
  ListChecks,
  ChevronRight,
  Landmark,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  DismissibleInfo,
  RecoveryCard,
  SkeletonTable,
  ConfirmDialog,
  WideModal,
  WideModalSection,
  WideModalField,
  ModuleGuideButton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useToastStore } from '@/stores/useToastStore';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import {
  fetchProjectRouteMeta,
  fetchRouteAssessments,
  classifyRoute,
  createRouteAssessment,
  updateRouteAssessment,
  confirmRouteAssessment,
  deleteRouteAssessment,
  type CodeLabel,
  type WorkType,
  type RouteOption,
  type RouteCriteria,
  type RouteAssessment,
  type ClassifyResult,
} from './api';
import { projectRouteGuide } from './projectRouteGuide';
import { getIntlLocale } from '@/shared/lib/formatters';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

/** Generic classifier criteria the built-in decision tree understands. Any
 *  regional pack may extend this dict server-side; the UI only renders these
 *  well-known toggles. */
const CRITERIA_TOGGLES: { key: keyof RouteCriteria; labelKey: string; labelDefault: string }[] = [
  { key: 'affects_structure', labelKey: 'project_route.criteria_affects_structure', labelDefault: 'Affects the load-bearing structure' },
  { key: 'changes_use', labelKey: 'project_route.criteria_changes_use', labelDefault: 'Changes the use class' },
  { key: 'within_permitted_limits', labelKey: 'project_route.criteria_within_permitted_limits', labelDefault: 'Stays within permitted-development limits' },
  { key: 'heritage_protected', labelKey: 'project_route.criteria_heritage_protected', labelDefault: 'Heritage-protected site or building' },
];

const ROUTE_BADGE: Record<RouteOption, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  full_permit: 'warning',
  notification: 'blue',
  permitted_development: 'success',
  exempt: 'success',
  expertise_required: 'error',
  undetermined: 'neutral',
};

const prettyCode = (code: string): string =>
  code.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

function labelFor(list: CodeLabel[], code: string): string {
  return list.find((c) => c.code === code)?.label ?? prettyCode(code);
}

function confidencePct(confidence: number): number {
  return Math.round(Math.max(0, Math.min(1, confidence)) * 100);
}

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── Classifier form (create / edit assessment) ───────────────────────── */

interface ClassifierFormData {
  work_type: WorkType;
  criteria: RouteCriteria;
}

function ClassifierModal({
  onClose,
  onSubmit,
  isPending,
  initialData,
  isEdit,
  workTypes,
  routeOptions,
}: {
  onClose: () => void;
  onSubmit: (data: ClassifierFormData) => void;
  isPending: boolean;
  initialData?: ClassifierFormData | null;
  isEdit?: boolean;
  workTypes: CodeLabel[];
  routeOptions: CodeLabel[];
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<ClassifierFormData>(
    initialData ?? { work_type: workTypes[0]?.code as WorkType ?? 'new_build', criteria: {} },
  );
  const [preview, setPreview] = useState<ClassifyResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const setCriterion = (key: keyof RouteCriteria, value: boolean) =>
    setForm((prev) => ({ ...prev, criteria: { ...prev.criteria, [key]: value } }));

  const runPreview = useCallback(async () => {
    setPreviewing(true);
    setPreviewError(null);
    try {
      const result = await classifyRoute({ work_type: form.work_type, criteria: form.criteria });
      setPreview(result);
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e));
    } finally {
      setPreviewing(false);
    }
  }, [form.work_type, form.criteria]);

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="lg"
      title={
        isEdit
          ? t('project_route.edit_assessment', { defaultValue: 'Edit Assessment' })
          : t('project_route.new_assessment', { defaultValue: 'Classify Work Type' })
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={() => onSubmit(form)} disabled={isPending}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Save size={16} className="mr-1.5 shrink-0" />
            )}
            <span>
              {isEdit
                ? t('project_route.save_assessment', { defaultValue: 'Save Changes' })
                : t('project_route.create_assessment', { defaultValue: 'Save Assessment' })}
            </span>
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('project_route.section_work_type', { defaultValue: 'Work type' })}
        columns={1}
      >
        <WideModalField
          label={t('project_route.field_work_type', { defaultValue: 'Type of work' })}
          required
          htmlFor="route-work-type"
        >
          <select
            id="route-work-type"
            value={form.work_type}
            onChange={(e) => setForm((prev) => ({ ...prev, work_type: e.target.value as WorkType }))}
            className={inputCls}
          >
            {workTypes.map((w) => (
              <option key={w.code} value={w.code}>
                {w.label}
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('project_route.section_criteria', { defaultValue: 'Criteria' })}
        description={t('project_route.section_criteria_desc', {
          defaultValue: 'Answer what applies. Leave a toggle off if it does not apply or is unknown.',
        })}
        columns={2}
      >
        {CRITERIA_TOGGLES.map((c) => (
          <label
            key={c.key}
            className="flex items-center gap-2 rounded-lg border border-border px-3 py-2.5 text-sm cursor-pointer hover:bg-surface-secondary/50"
          >
            <input
              type="checkbox"
              checked={Boolean(form.criteria[c.key])}
              onChange={(e) => setCriterion(c.key, e.target.checked)}
              className="shrink-0 accent-oe-blue"
            />
            <span>{t(c.labelKey, { defaultValue: c.labelDefault })}</span>
          </label>
        ))}
        <WideModalField
          label={t('project_route.field_scale', { defaultValue: 'Scale' })}
          htmlFor="route-scale"
        >
          <select
            id="route-scale"
            value={typeof form.criteria.scale === 'string' ? form.criteria.scale : ''}
            onChange={(e) =>
              setForm((prev) => ({
                ...prev,
                criteria: { ...prev.criteria, scale: (e.target.value || undefined) as 'minor' | 'major' | undefined },
              }))
            }
            className={inputCls}
          >
            <option value="">{t('project_route.scale_unknown', { defaultValue: 'Unspecified' })}</option>
            <option value="minor">{t('project_route.scale_minor', { defaultValue: 'Minor' })}</option>
            <option value="major">{t('project_route.scale_major', { defaultValue: 'Major' })}</option>
          </select>
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('project_route.section_preview', { defaultValue: 'Preview' })}
        columns={1}
      >
        <Button variant="secondary" size="sm" onClick={() => void runPreview()} disabled={previewing}>
          {previewing ? (
            <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent mr-2 shrink-0" />
          ) : (
            <Sparkles size={14} className="mr-1.5 shrink-0" />
          )}
          {t('project_route.run_preview', { defaultValue: 'Preview suggested route' })}
        </Button>

        {previewError && (
          <p className="mt-2 text-sm text-semantic-error">{previewError}</p>
        )}

        {preview && (
          <div className="mt-3 rounded-lg border border-border-light bg-surface-secondary/40 p-3 space-y-1.5">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge variant={ROUTE_BADGE[preview.determined_route]} size="sm">
                {labelFor(routeOptions, preview.determined_route)}
              </Badge>
              <span className="text-xs text-content-tertiary">
                {t('project_route.confidence', {
                  defaultValue: 'Confidence {{pct}}%',
                  pct: confidencePct(preview.confidence),
                })}
              </span>
            </div>
            <p className="text-xs text-content-secondary leading-relaxed">{preview.rationale}</p>
          </div>
        )}
      </WideModalSection>
    </WideModal>
  );
}

/* ── Assessment row ───────────────────────────────────────────────────── */

const AssessmentRow = React.memo(function AssessmentRow({
  item,
  workTypes,
  routeOptions,
  onEdit,
  onDelete,
  onConfirm,
  confirmPending,
}: {
  item: RouteAssessment;
  workTypes: CodeLabel[];
  routeOptions: CodeLabel[];
  onEdit: (item: RouteAssessment) => void;
  onDelete: (item: RouteAssessment) => void;
  onConfirm: (item: RouteAssessment) => void;
  confirmPending: boolean;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b border-border-light last:border-b-0">
      <div
        className={clsx(
          'flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-surface-secondary/50 transition-colors',
          expanded && 'bg-surface-secondary/30',
        )}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setExpanded((prev) => !prev);
          }
        }}
      >
        <ChevronRight
          size={14}
          className={clsx('text-content-tertiary transition-transform shrink-0', expanded && 'rotate-90')}
        />
        <span className="text-sm text-content-primary flex-1 min-w-0 truncate">
          {labelFor(workTypes, item.work_type)}
        </span>
        <Badge variant={ROUTE_BADGE[item.determined_route]} size="sm" className="shrink-0">
          {labelFor(routeOptions, item.determined_route)}
        </Badge>
        <span className="text-xs text-content-tertiary w-24 shrink-0 hidden sm:block tabular-nums">
          {t('project_route.confidence', {
            defaultValue: 'Confidence {{pct}}%',
            pct: confidencePct(item.confidence),
          })}
        </span>
        <Badge
          variant={item.status === 'confirmed' ? 'success' : 'neutral'}
          size="sm"
          className="shrink-0"
        >
          {item.status === 'confirmed' ? (
            <CheckCircle2 size={11} className="mr-1" />
          ) : null}
          {item.status === 'confirmed'
            ? t('project_route.status_confirmed', { defaultValue: 'Confirmed' })
            : t('project_route.status_draft', { defaultValue: 'Draft' })}
        </Badge>
      </div>

      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          <div className="rounded-lg bg-surface-secondary p-3">
            <p className="text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide">
              {t('project_route.label_rationale', { defaultValue: 'Rationale' })}
            </p>
            <p className="text-sm text-content-primary whitespace-pre-wrap">
              {item.rationale || t('project_route.no_rationale', { defaultValue: 'No rationale recorded.' })}
            </p>
          </div>

          {item.classified_at && (
            <p className="text-xs text-content-tertiary">
              {t('project_route.classified_at', {
                defaultValue: 'Classified {{date}}',
                date: new Date(item.classified_at).toLocaleString(getIntlLocale()),
              })}
            </p>
          )}

          {item.status === 'confirmed' &&
            (item.determined_route === 'full_permit' ||
              item.determined_route === 'notification' ||
              item.determined_route === 'expertise_required') && (
              <Link
                to="/authority-submissions"
                onClick={(e) => e.stopPropagation()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-oe-blue/30 bg-oe-blue/5 px-2.5 py-1.5 text-xs font-medium text-oe-blue hover:bg-oe-blue/10 hover:underline"
                title={t('project_route.open_authority_submissions_hint', {
                  defaultValue: 'This route needs a submission to an approving authority.',
                })}
              >
                <Landmark size={12} className="shrink-0" />
                {t('project_route.open_authority_submissions', {
                  defaultValue: 'Start an authority submission',
                })}
              </Link>
            )}

          <div className="flex items-center gap-2 pt-1 flex-wrap">
            {item.status !== 'confirmed' && (
              <Button
                variant="primary"
                size="sm"
                icon={<ShieldCheck size={13} />}
                disabled={confirmPending}
                onClick={(e) => {
                  e.stopPropagation();
                  onConfirm(item);
                }}
              >
                {t('project_route.confirm_route', { defaultValue: 'Confirm route' })}
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              icon={<Pencil size={13} />}
              onClick={(e) => {
                e.stopPropagation();
                onEdit(item);
              }}
            >
              {t('common.edit', { defaultValue: 'Edit' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              className="text-semantic-error hover:bg-red-50 dark:hover:bg-red-950/30"
              icon={<Trash2 size={13} />}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(item);
              }}
            >
              {t('common.delete', { defaultValue: 'Delete' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
});

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function ProjectRoutePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useActiveProjectId();

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingItem, setEditingItem] = useState<RouteAssessment | null>(null);
  const [statusFilter, setStatusFilter] = useState<'draft' | 'confirmed' | ''>('');
  const { confirm, ...confirmProps } = useConfirm();

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const { data: meta } = useQuery({
    queryKey: ['project-route-meta'],
    queryFn: () => fetchProjectRouteMeta(),
    staleTime: 5 * 60_000,
  });
  const workTypes = meta?.work_types ?? [];
  const routeOptions = meta?.route_options ?? [];

  const {
    data: items = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['project-route-assessments', projectId, statusFilter],
    queryFn: () => fetchRouteAssessments({ project_id: projectId, status: statusFilter || undefined }),
    enabled: !!projectId,
  });

  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['project-route-assessments'] });
  }, [qc]);

  const createMut = useMutation({
    mutationFn: (data: ClassifierFormData) =>
      createRouteAssessment({ project_id: projectId, work_type: data.work_type, criteria: data.criteria }),
    onSuccess: () => {
      invalidateAll();
      setShowCreateModal(false);
      addToast({ type: 'success', title: t('project_route.created', { defaultValue: 'Assessment saved' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const updateMut = useMutation({
    mutationFn: ({
      id,
      data,
      base,
    }: {
      id: string;
      data: ClassifierFormData;
      base: ClassifierFormData;
    }) => {
      // Only what the user actually edited goes back. Changing the work type
      // used to rewrite the whole criteria map as it stood when this list was
      // read, undoing anyone else's edit to it without a word. The update route
      // dumps with `exclude_unset=True`, so an omitted field is left alone.
      const patch: { work_type?: WorkType; criteria?: RouteCriteria } = {};
      if (data.work_type !== base.work_type) patch.work_type = data.work_type;
      // Compared by content, not identity: the baseline is rebuilt on every
      // save, so a reference test would resend the criteria map every time.
      if (JSON.stringify(data.criteria) !== JSON.stringify(base.criteria)) {
        patch.criteria = data.criteria;
      }
      return updateRouteAssessment(id, patch);
    },
    onSuccess: () => {
      invalidateAll();
      setEditingItem(null);
      addToast({ type: 'success', title: t('project_route.updated', { defaultValue: 'Assessment updated' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteRouteAssessment(id),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('project_route.deleted', { defaultValue: 'Assessment deleted' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const confirmMut = useMutation({
    mutationFn: (id: string) => confirmRouteAssessment(id),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('project_route.route_confirmed', { defaultValue: 'Route confirmed' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const handleCreateSubmit = useCallback(
    (formData: ClassifierFormData) => {
      if (!projectId) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: t('common.select_project_first', { defaultValue: 'Please select a project first' }),
        });
        return;
      }
      createMut.mutate(formData);
    },
    [createMut, projectId, addToast, t],
  );

  const handleEditSubmit = useCallback(
    (formData: ClassifierFormData) => {
      if (!editingItem) return;
      // Rebuild the baseline the modal was seeded from, the same expression
      // `editInitialData` uses, so the save carries only what the user edited.
      updateMut.mutate({
        id: editingItem.id,
        data: formData,
        base: { work_type: editingItem.work_type, criteria: editingItem.criteria },
      });
    },
    [updateMut, editingItem],
  );

  const handleDelete = useCallback(
    async (item: RouteAssessment) => {
      const ok = await confirm({
        title: t('project_route.confirm_delete_title', { defaultValue: 'Delete assessment?' }),
        message: t('project_route.confirm_delete_msg', {
          defaultValue: 'This permanently removes the {{work_type}} route assessment.',
          work_type: labelFor(workTypes, item.work_type),
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(item.id);
    },
    [deleteMut, confirm, t, workTypes],
  );

  const handleConfirmRoute = useCallback(
    async (item: RouteAssessment) => {
      const ok = await confirm({
        title: t('project_route.confirm_route_title', { defaultValue: 'Confirm this route?' }),
        message: t('project_route.confirm_route_msg', {
          defaultValue:
            'This locks in "{{route}}" as the route the project proceeds under. You can still edit it later, which returns it to draft.',
          route: labelFor(routeOptions, item.determined_route),
        }),
        confirmLabel: t('project_route.confirm_route', { defaultValue: 'Confirm route' }),
        variant: 'warning',
      });
      if (ok) confirmMut.mutate(item.id);
    },
    [confirmMut, confirm, t, routeOptions],
  );

  const editFormData: ClassifierFormData | null = useMemo(
    () => (editingItem ? { work_type: editingItem.work_type, criteria: editingItem.criteria } : null),
    [editingItem],
  );

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(projectId && projectName ? [{ label: projectName, to: `/projects/${projectId}` }] : []),
          { label: t('project_route.title', { defaultValue: 'Work-type Route Classifier' }) },
        ]}
      />

      <PageHeader
        srTitle={t('project_route.title', { defaultValue: 'Work-type Route Classifier' })}
        subtitle={t('project_route.subtitle', {
          defaultValue: 'Classify a work type into the delivery, permitting or approval route it needs',
        })}
        actions={
          <>
            <ModuleGuideButton content={projectRouteGuide} />
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowCreateModal(true)}
              disabled={!projectId}
              title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
              className="shrink-0 whitespace-nowrap"
              icon={<Sparkles size={14} />}
            >
              {t('project_route.new_assessment', { defaultValue: 'Classify Work Type' })}
            </Button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="project-route"
        title={t('project_route.intro_title', { defaultValue: 'Know the route before you commit' })}
      >
        {t('project_route.intro_body', {
          defaultValue:
            'Pick the type of work and answer a few criteria; the classifier suggests a delivery, permitting or approval route with a confidence score and a plain-language rationale. Save it as an assessment, then confirm it to lock in the route the project proceeds under. AI proposes, a person confirms.',
        })}
      </DismissibleInfo>

      {!projectId && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('common.select_project_hint', { defaultValue: 'Select a project from the header to get started.' })}
        </div>
      )}

      {/* Reference vocabularies from the backend */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Card padding="md">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary mb-2">
            <ListChecks size={15} className="text-oe-blue" />
            {t('project_route.work_types_title', { defaultValue: 'Work types' })}
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {workTypes.length === 0 ? (
              <p className="text-xs text-content-tertiary">
                {t('common.loading', { defaultValue: 'Loading…' })}
              </p>
            ) : (
              workTypes.map((w) => (
                <Badge key={w.code} variant="neutral" size="sm">
                  {w.label}
                </Badge>
              ))
            )}
          </div>
        </Card>
        <Card padding="md">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary mb-2">
            <Route size={15} className="text-oe-blue" />
            {t('project_route.route_options_title', { defaultValue: 'Route options' })}
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {routeOptions.length === 0 ? (
              <p className="text-xs text-content-tertiary">
                {t('common.loading', { defaultValue: 'Loading…' })}
              </p>
            ) : (
              routeOptions.map((r) => (
                <Badge key={r.code} variant={ROUTE_BADGE[r.code as RouteOption] ?? 'neutral'} size="sm">
                  {r.label}
                </Badge>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Status filter */}
      <div className="flex items-center gap-3">
        <div className="relative">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'draft' | 'confirmed' | '')}
            aria-label={t('project_route.filter_all_status', { defaultValue: 'All Statuses' })}
            className="h-10 rounded-lg border border-border bg-surface-primary ps-3 pe-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-44"
          >
            <option value="">{t('project_route.filter_all_status', { defaultValue: 'All Statuses' })}</option>
            <option value="draft">{t('project_route.status_draft', { defaultValue: 'Draft' })}</option>
            <option value="confirmed">{t('project_route.status_confirmed', { defaultValue: 'Confirmed' })}</option>
          </select>
        </div>
      </div>

      {/* Assessments list */}
      <div>
        {isLoading ? (
          <SkeletonTable rows={4} columns={4} />
        ) : isError ? (
          <RecoveryCard error={error} onRetry={() => refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Route size={28} strokeWidth={1.5} />}
            title={t('project_route.no_entries', { defaultValue: 'No route assessments yet' })}
            description={t('project_route.no_entries_hint', {
              defaultValue: 'Classify your first work type to get a suggested route.',
            })}
            action={
              projectId
                ? {
                    label: t('project_route.new_assessment', { defaultValue: 'Classify Work Type' }),
                    onClick: () => setShowCreateModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('project_route.showing_count', { defaultValue: '{{count}} assessments', count: items.length })}
            </p>
            <Card padding="none" className="overflow-x-auto">
              {items.map((item) => (
                <AssessmentRow
                  key={item.id}
                  item={item}
                  workTypes={workTypes}
                  routeOptions={routeOptions}
                  onEdit={setEditingItem}
                  onDelete={handleDelete}
                  onConfirm={handleConfirmRoute}
                  confirmPending={confirmMut.isPending}
                />
              ))}
            </Card>
          </>
        )}
      </div>

      {showCreateModal && (
        <ClassifierModal
          workTypes={workTypes}
          routeOptions={routeOptions}
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
        />
      )}

      {editingItem && (
        <ClassifierModal
          isEdit
          workTypes={workTypes}
          routeOptions={routeOptions}
          initialData={editFormData}
          onClose={() => setEditingItem(null)}
          onSubmit={handleEditSubmit}
          isPending={updateMut.isPending}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
