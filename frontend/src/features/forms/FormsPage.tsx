// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// FormsPage - the Forms & Checklists workspace. Two tabs:
//   * Library     - browse / search / author reusable templates, then "Use" one
//   * Submissions - the forms filled into the active project, with status + PDF
//
// Project-scoped (submissions belong to a project); the library shows the
// organisation-wide templates plus any pinned to the active project.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ClipboardList,
  LibraryBig,
  Plus,
  Search,
  Copy,
  Pencil,
  Trash2,
  Download,
  FileText,
  Layers,
  ChevronRight,
  Loader2,
} from 'lucide-react';
import clsx from 'clsx';
import { Button, Card, Badge, EmptyState, TabBar, ConfirmDialog, SkeletonGrid } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  fetchTemplates,
  fetchCategories,
  fetchTemplate,
  duplicateTemplate,
  deleteTemplate,
  fetchSubmissions,
  createSubmission,
  deleteSubmission,
  downloadSubmissionPdf,
  type TemplateSummary,
  type TemplateDetail,
  type TemplateCategory,
  type SubmissionSummary,
  type SubmissionStatus,
} from './api';
import { CATEGORY_LABELS } from './fieldTypes';
import { TemplateBuilder } from './TemplateBuilder';
import { FormFiller } from './FormFiller';

type TabId = 'library' | 'submissions';

const CATEGORY_BADGE: Record<TemplateCategory, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  safety: 'error',
  quality: 'blue',
  handover: 'success',
  inspection: 'warning',
  commissioning: 'neutral',
  custom: 'neutral',
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export function FormsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const confirmState = useConfirm();
  const { confirm } = confirmState;

  const [tab, setTab] = useState<TabId>('library');

  // Library filters
  const [category, setCategory] = useState<TemplateCategory | ''>('');
  const [search, setSearch] = useState('');

  // Submission filters
  const [subStatus, setSubStatus] = useState<SubmissionStatus | ''>('');

  // Builder + filler state
  const [builderOpen, setBuilderOpen] = useState(false);
  const [builderInitial, setBuilderInitial] = useState<TemplateDetail | null>(null);
  const [fillerId, setFillerId] = useState<string | null>(null);
  const [fillerOpen, setFillerOpen] = useState(false);

  /* -- Queries ------------------------------------------------------------- */

  const { data: categories = [] } = useQuery({
    queryKey: ['forms', 'categories', projectId],
    queryFn: () => fetchCategories(projectId),
    enabled: !!projectId,
  });

  const {
    data: templates = [],
    isLoading: templatesLoading,
  } = useQuery({
    queryKey: ['forms', 'templates', projectId, category, search],
    queryFn: () => fetchTemplates({ projectId, category, q: search }),
    enabled: !!projectId && tab === 'library',
  });

  const {
    data: submissions = [],
    isLoading: submissionsLoading,
  } = useQuery({
    queryKey: ['forms', 'submissions', projectId, subStatus],
    queryFn: () => fetchSubmissions({ projectId: projectId as string, status: subStatus }),
    enabled: !!projectId && tab === 'submissions',
  });

  /* -- Mutations ----------------------------------------------------------- */

  const openEditMut = useMutation({
    mutationFn: (id: string) => fetchTemplate(id),
    onSuccess: (detail) => {
      setBuilderInitial(detail);
      setBuilderOpen(true);
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const duplicateMut = useMutation({
    mutationFn: (id: string) => duplicateTemplate(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['forms', 'templates'] });
      qc.invalidateQueries({ queryKey: ['forms', 'categories'] });
      addToast({ type: 'success', title: t('forms.template_duplicated', { defaultValue: 'Template duplicated' }) });
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const useTemplateMut = useMutation({
    mutationFn: (templateId: string) =>
      createSubmission({ project_id: projectId as string, template_id: templateId }),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['forms', 'submissions'] });
      setTab('submissions');
      setFillerId(created.id);
      setFillerOpen(true);
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const deleteTemplateMut = useMutation({
    mutationFn: (id: string) => deleteTemplate(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['forms', 'templates'] });
      qc.invalidateQueries({ queryKey: ['forms', 'categories'] });
      addToast({ type: 'success', title: t('forms.template_deleted', { defaultValue: 'Template deleted' }) });
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const deleteSubmissionMut = useMutation({
    mutationFn: (id: string) => deleteSubmission(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['forms', 'submissions'] });
      addToast({ type: 'success', title: t('forms.submission_deleted', { defaultValue: 'Submission deleted' }) });
    },
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  const exportMut = useMutation({
    mutationFn: (s: SubmissionSummary) => downloadSubmissionPdf(s.id, `${s.submission_number}.pdf`),
    onError: (e: unknown) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(e) }),
  });

  /* -- Handlers ------------------------------------------------------------ */

  const onNewTemplate = () => {
    setBuilderInitial(null);
    setBuilderOpen(true);
  };

  const onDeleteTemplate = async (tpl: TemplateSummary) => {
    const ok = await confirm({
      title: t('forms.delete_template_q', { defaultValue: 'Delete template?' }),
      message: t('forms.delete_template_msg', {
        defaultValue:
          'This removes the template from the library. Forms already submitted keep their own copy and are not affected.',
      }),
    });
    if (ok) deleteTemplateMut.mutate(tpl.id);
  };

  const onDeleteSubmission = async (s: SubmissionSummary) => {
    const ok = await confirm({
      title: t('forms.delete_submission_q', { defaultValue: 'Delete submission?' }),
      message: t('forms.delete_submission_msg', { defaultValue: 'This permanently deletes the filled form.' }),
    });
    if (ok) deleteSubmissionMut.mutate(s.id);
  };

  const tabs = useMemo(
    () => [
      {
        id: 'library' as const,
        label: t('forms.tab_library', { defaultValue: 'Library' }),
        icon: <LibraryBig size={15} />,
      },
      {
        id: 'submissions' as const,
        label: t('forms.tab_submissions', { defaultValue: 'Submissions' }),
        icon: <ClipboardList size={15} />,
      },
    ],
    [t],
  );

  return (
    <div className="space-y-5">
      <PageHeader
        srTitle={t('forms.title', { defaultValue: 'Forms & checklists' })}
        subtitle={t('forms.subtitle', {
          defaultValue:
            'Build reusable form and checklist templates, then fill them in on site and export the record.',
        })}
        actions={
          tab === 'library' ? (
            <Button icon={<Plus size={15} />} onClick={onNewTemplate}>
              {t('forms.new_template', { defaultValue: 'New template' })}
            </Button>
          ) : undefined
        }
      />

      <RequiresProject
        emptyHint={t('forms.select_project_hint', {
          defaultValue: 'Pick a project from the header to fill in and track forms.',
        })}
      >
        <TabBar tabs={tabs} activeId={tab} onChange={setTab} ariaLabel="Forms sections" idPrefix="forms" />

        {tab === 'library' ? (
          <LibraryTab
            categories={categories}
            templates={templates}
            loading={templatesLoading}
            category={category}
            onCategory={setCategory}
            search={search}
            onSearch={setSearch}
            onUse={(tpl) => useTemplateMut.mutate(tpl.id)}
            usingId={useTemplateMut.isPending ? useTemplateMut.variables ?? null : null}
            onEdit={(tpl) => openEditMut.mutate(tpl.id)}
            onDuplicate={(tpl) => duplicateMut.mutate(tpl.id)}
            onDelete={onDeleteTemplate}
            onNew={onNewTemplate}
          />
        ) : (
          <SubmissionsTab
            submissions={submissions}
            loading={submissionsLoading}
            status={subStatus}
            onStatus={setSubStatus}
            onOpen={(s) => {
              setFillerId(s.id);
              setFillerOpen(true);
            }}
            onExport={(s) => exportMut.mutate(s)}
            exportingId={exportMut.isPending ? exportMut.variables?.id ?? null : null}
            onDelete={onDeleteSubmission}
            onGoLibrary={() => setTab('library')}
          />
        )}
      </RequiresProject>

      {builderOpen && (
        <TemplateBuilder
          open={builderOpen}
          initial={builderInitial}
          projectId={projectId}
          onClose={() => setBuilderOpen(false)}
          onSaved={() => setBuilderOpen(false)}
        />
      )}

      <FormFiller
        open={fillerOpen}
        submissionId={fillerId}
        onClose={() => setFillerOpen(false)}
        onChanged={() => qc.invalidateQueries({ queryKey: ['forms', 'submissions'] })}
      />

      <ConfirmDialog
        open={confirmState.open}
        title={confirmState.title}
        message={confirmState.message}
        confirmLabel={confirmState.confirmLabel}
        cancelLabel={confirmState.cancelLabel}
        variant={confirmState.variant}
        loading={confirmState.loading}
        onConfirm={confirmState.onConfirm}
        onCancel={confirmState.onCancel}
      />
    </div>
  );
}

/* -- Library tab ----------------------------------------------------------- */

interface LibraryTabProps {
  categories: { key: TemplateCategory; label: string; template_count: number }[];
  templates: TemplateSummary[];
  loading: boolean;
  category: TemplateCategory | '';
  onCategory: (c: TemplateCategory | '') => void;
  search: string;
  onSearch: (s: string) => void;
  onUse: (tpl: TemplateSummary) => void;
  usingId: string | null;
  onEdit: (tpl: TemplateSummary) => void;
  onDuplicate: (tpl: TemplateSummary) => void;
  onDelete: (tpl: TemplateSummary) => void;
  onNew: () => void;
}

function LibraryTab({
  categories,
  templates,
  loading,
  category,
  onCategory,
  search,
  onSearch,
  onUse,
  usingId,
  onEdit,
  onDuplicate,
  onDelete,
  onNew,
}: LibraryTabProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            className={clsx(inputCls, 'pl-9')}
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            placeholder={t('forms.search_templates', { defaultValue: 'Search templates' })}
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <CategoryChip active={category === ''} label={t('forms.all', { defaultValue: 'All' })} onClick={() => onCategory('')} />
        {categories
          .filter((c) => c.template_count > 0 || c.key === category)
          .map((c) => (
            <CategoryChip
              key={c.key}
              active={category === c.key}
              label={`${CATEGORY_LABELS[c.key]} (${c.template_count})`}
              onClick={() => onCategory(category === c.key ? '' : c.key)}
            />
          ))}
      </div>

      {loading ? (
        <SkeletonGrid items={6} />
      ) : templates.length === 0 ? (
        <EmptyState
          icon={<LibraryBig size={28} strokeWidth={1.5} />}
          title={t('forms.no_templates', { defaultValue: 'No templates yet' })}
          description={t('forms.no_templates_desc', {
            defaultValue: 'Create your first reusable form or checklist template.',
          })}
          action={
            <Button icon={<Plus size={15} />} onClick={onNew}>
              {t('forms.new_template', { defaultValue: 'New template' })}
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {templates.map((tpl) => (
            <TemplateCard
              key={tpl.id}
              tpl={tpl}
              using={usingId === tpl.id}
              onUse={() => onUse(tpl)}
              onEdit={() => onEdit(tpl)}
              onDuplicate={() => onDuplicate(tpl)}
              onDelete={() => onDelete(tpl)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function TemplateCard({
  tpl,
  using,
  onUse,
  onEdit,
  onDuplicate,
  onDelete,
}: {
  tpl: TemplateSummary;
  using: boolean;
  onUse: () => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-content-primary">{tpl.name}</h3>
          {tpl.description && (
            <p className="mt-0.5 line-clamp-2 text-xs text-content-tertiary">{tpl.description}</p>
          )}
        </div>
        <Badge variant={CATEGORY_BADGE[tpl.category]} size="sm">
          {CATEGORY_LABELS[tpl.category]}
        </Badge>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-content-tertiary">
        <span className="inline-flex items-center gap-1">
          <Layers size={12} />
          {t('forms.n_fields', { defaultValue: '{{count}} fields', count: tpl.field_count })}
        </span>
        <span>·</span>
        <span>v{tpl.version}</span>
        {tpl.project_id === null && (
          <>
            <span>·</span>
            <span className="inline-flex items-center gap-1">
              <LibraryBig size={12} />
              {t('forms.global', { defaultValue: 'Library' })}
            </span>
          </>
        )}
        {tpl.is_seed && (
          <Badge variant="neutral" size="sm">
            {t('forms.starter', { defaultValue: 'Starter' })}
          </Badge>
        )}
      </div>

      <div className="mt-auto flex items-center justify-between gap-1 pt-1">
        <Button size="sm" icon={<ChevronRight size={14} />} iconPosition="right" loading={using} onClick={onUse}>
          {t('forms.use', { defaultValue: 'Use' })}
        </Button>
        <div className="flex items-center gap-0.5">
          <CardIconBtn label={t('common.edit', { defaultValue: 'Edit' })} onClick={onEdit}>
            <Pencil size={14} />
          </CardIconBtn>
          <CardIconBtn label={t('forms.duplicate', { defaultValue: 'Duplicate' })} onClick={onDuplicate}>
            <Copy size={14} />
          </CardIconBtn>
          <CardIconBtn label={t('common.delete', { defaultValue: 'Delete' })} danger onClick={onDelete}>
            <Trash2 size={14} />
          </CardIconBtn>
        </div>
      </div>
    </Card>
  );
}

/* -- Submissions tab ------------------------------------------------------- */

interface SubmissionsTabProps {
  submissions: SubmissionSummary[];
  loading: boolean;
  status: SubmissionStatus | '';
  onStatus: (s: SubmissionStatus | '') => void;
  onOpen: (s: SubmissionSummary) => void;
  onExport: (s: SubmissionSummary) => void;
  exportingId: string | null;
  onDelete: (s: SubmissionSummary) => void;
  onGoLibrary: () => void;
}

function SubmissionsTab({
  submissions,
  loading,
  status,
  onStatus,
  onOpen,
  onExport,
  exportingId,
  onDelete,
  onGoLibrary,
}: SubmissionsTabProps) {
  const { t } = useTranslation();

  const statusTabs: { id: SubmissionStatus | ''; label: string }[] = [
    { id: '', label: t('forms.all', { defaultValue: 'All' }) },
    { id: 'draft', label: t('forms.draft', { defaultValue: 'Draft' }) },
    { id: 'completed', label: t('forms.completed', { defaultValue: 'Completed' }) },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        {statusTabs.map((s) => (
          <CategoryChip key={s.id || 'all'} active={status === s.id} label={s.label} onClick={() => onStatus(s.id)} />
        ))}
      </div>

      {loading ? (
        <SkeletonGrid items={4} />
      ) : submissions.length === 0 ? (
        <EmptyState
          icon={<ClipboardList size={28} strokeWidth={1.5} />}
          title={t('forms.no_submissions', { defaultValue: 'No forms filled yet' })}
          description={t('forms.no_submissions_desc', {
            defaultValue: 'Pick a template from the library and fill it in to get started.',
          })}
          action={
            <Button icon={<LibraryBig size={15} />} onClick={onGoLibrary}>
              {t('forms.go_to_library', { defaultValue: 'Go to library' })}
            </Button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border">
          {submissions.map((s, i) => (
            <SubmissionRow
              key={s.id}
              s={s}
              first={i === 0}
              exporting={exportingId === s.id}
              onOpen={() => onOpen(s)}
              onExport={() => onExport(s)}
              onDelete={() => onDelete(s)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SubmissionRow({
  s,
  first,
  exporting,
  onOpen,
  onExport,
  onDelete,
}: {
  s: SubmissionSummary;
  first: boolean;
  exporting: boolean;
  onOpen: () => void;
  onExport: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const completed = s.status === 'completed';
  return (
    <div
      className={clsx(
        'flex items-center gap-3 bg-surface-primary px-3 py-2.5 hover:bg-surface-secondary',
        !first && 'border-t border-border-light',
      )}
    >
      <button type="button" onClick={onOpen} className="flex min-w-0 flex-1 items-center gap-3 text-left">
        <FileText size={16} className="shrink-0 text-content-tertiary" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-content-primary">{s.template_name}</span>
            <span className="shrink-0 text-xs text-content-quaternary">{s.submission_number}</span>
          </div>
          <div className="truncate text-xs text-content-tertiary">
            {[s.title, s.location].filter(Boolean).join(' · ') || CATEGORY_LABELS[s.template_category]}
            {' · '}
            <DateDisplay value={s.created_at} />
          </div>
        </div>
      </button>

      <ResultBadge status={s.status} result={s.result} />

      <div className="flex shrink-0 items-center gap-0.5">
        {completed && (
          <CardIconBtn label={t('forms.export_pdf', { defaultValue: 'Export PDF' })} onClick={onExport}>
            {exporting ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
          </CardIconBtn>
        )}
        <CardIconBtn label={t('common.delete', { defaultValue: 'Delete' })} danger onClick={onDelete}>
          <Trash2 size={14} />
        </CardIconBtn>
      </div>
    </div>
  );
}

function ResultBadge({ status, result }: { status: SubmissionStatus; result: SubmissionSummary['result'] }) {
  const { t } = useTranslation();
  if (status !== 'completed') {
    return (
      <Badge variant="warning" size="sm">
        {t('forms.draft', { defaultValue: 'Draft' })}
      </Badge>
    );
  }
  if (result === 'fail') {
    return (
      <Badge variant="error" size="sm">
        {t('forms.result_fail', { defaultValue: 'Fail' })}
      </Badge>
    );
  }
  if (result === 'pass') {
    return (
      <Badge variant="success" size="sm">
        {t('forms.result_pass', { defaultValue: 'Pass' })}
      </Badge>
    );
  }
  return (
    <Badge variant="success" size="sm">
      {t('forms.completed', { defaultValue: 'Completed' })}
    </Badge>
  );
}

/* -- Small shared bits ----------------------------------------------------- */

function CategoryChip({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'inline-flex h-8 items-center rounded-full border px-3 text-xs font-medium transition-colors',
        active
          ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
          : 'border-border text-content-secondary hover:bg-surface-secondary',
      )}
    >
      {label}
    </button>
  );
}

function CardIconBtn({
  children,
  label,
  onClick,
  danger,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={clsx(
        'inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors',
        danger
          ? 'text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error'
          : 'text-content-tertiary hover:bg-surface-secondary hover:text-content-primary',
      )}
    >
      {children}
    </button>
  );
}

export default FormsPage;
