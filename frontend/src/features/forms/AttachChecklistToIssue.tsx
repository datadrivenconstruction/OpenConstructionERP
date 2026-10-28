// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// AttachChecklistToIssue - attach and run a checklist against a tracked site
// issue (a punch item, a BCF topic, ...). Given an issue reference (type + id)
// it lets the user pick a template from the library and run it with
// ChecklistRunnerCompact. The run's submission carries the issue link in its
// metadata (issueType / issueId), so the checklists attached to an issue are
// discoverable by reading them back - which this component also does, listing
// what is already attached above the picker.
//
// Self-contained inside the forms module; a host (punch list, BCF) mounts it
// wherever an issue is shown.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ClipboardList, Search, ChevronRight, Loader2, Layers, Link2, X } from 'lucide-react';
import clsx from 'clsx';
import { Badge, EmptyState } from '@/shared/ui';
import {
  fetchTemplates,
  fetchSubmissions,
  fetchSubmission,
  type TemplateSummary,
  type TemplateCategory,
  type SubmissionDetail,
  type FormResult,
} from './api';
import { CATEGORY_LABELS } from './fieldTypes';
import {
  ChecklistRunnerCompact,
  type ChecklistIssueContext,
  type ChecklistRunResult,
} from './ChecklistRunnerCompact';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const CATEGORY_BADGE: Record<TemplateCategory, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  safety: 'error',
  quality: 'blue',
  handover: 'success',
  inspection: 'warning',
  commissioning: 'neutral',
  custom: 'neutral',
};

/* -- Discovery ------------------------------------------------------------- */

/**
 * List the checklist submissions attached to a given issue.
 *
 * The link lives in each submission's metadata (issueType / issueId). The list
 * endpoint returns summaries without metadata, so this resolves each summary to
 * its detail and filters client-side. That is an N+1 over the project's
 * submissions - fine at current volumes; a server-side metadata filter would be
 * the way to scale it. Bounded by the project's submission count.
 */
export async function fetchIssueChecklists(
  projectId: string,
  issueType: string,
  issueId: string,
): Promise<SubmissionDetail[]> {
  if (!projectId || !issueId) return [];
  const summaries = await fetchSubmissions({ projectId });
  if (summaries.length === 0) return [];
  const details = await Promise.all(summaries.map((s) => fetchSubmission(s.id).catch(() => null)));
  return details.filter((d): d is SubmissionDetail => {
    if (!d) return false;
    const m = (d.metadata ?? {}) as { issueType?: unknown; issueId?: unknown };
    return m.issueType === issueType && m.issueId === issueId;
  });
}

/* -- Component ------------------------------------------------------------- */

export interface AttachChecklistToIssueProps {
  /** Project the issue and its checklists belong to. */
  projectId: string;
  /** The kind of tracked issue, e.g. `'punch'` or `'bcf_topic'`. */
  issueType: string;
  /** The id of the issue to attach checklists to. */
  issueId: string;
  /** Optional human label for the issue, prefilled onto raised sub-issues. */
  issueTitle?: string;
  /** Restrict the template picker to a single category. */
  category?: TemplateCategory;
  /** Fired after a freshly-run checklist is completed and attached. */
  onAttached?: (result: ChecklistRunResult) => void;
  /** Optional close affordance for the host. */
  onClose?: () => void;
  className?: string;
}

type Selection =
  | { mode: 'new'; templateId: string }
  | { mode: 'open'; submission: SubmissionDetail }
  | null;

export function AttachChecklistToIssue({
  projectId,
  issueType,
  issueId,
  issueTitle,
  category,
  onAttached,
  onClose,
  className,
}: AttachChecklistToIssueProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const [search, setSearch] = useState('');
  const [selection, setSelection] = useState<Selection>(null);

  const issueContext: ChecklistIssueContext = { issueType, issueId, issueTitle };

  const attachedKey = ['forms', 'issue-checklists', projectId, issueType, issueId];

  const { data: attached = [], isLoading: attachedLoading } = useQuery({
    queryKey: attachedKey,
    queryFn: () => fetchIssueChecklists(projectId, issueType, issueId),
    enabled: !!projectId && !!issueId && selection === null,
  });

  const {
    data: templates = [],
    isLoading: templatesLoading,
  } = useQuery({
    queryKey: ['forms', 'templates', projectId, category ?? '', search],
    queryFn: () => fetchTemplates({ projectId, category: category ?? '', q: search }),
    enabled: !!projectId && selection === null,
  });

  const refreshAttached = () => {
    qc.invalidateQueries({ queryKey: attachedKey });
    qc.invalidateQueries({ queryKey: ['forms', 'submissions'] });
  };

  /* -- Running a checklist ------------------------------------------------- */

  if (selection?.mode === 'new') {
    return (
      <div className={className}>
        <ChecklistRunnerCompact
          key={selection.templateId}
          projectId={projectId}
          template={selection.templateId}
          issueContext={issueContext}
          onCancel={() => setSelection(null)}
          onComplete={(result) => {
            refreshAttached();
            onAttached?.(result);
            setSelection(null);
          }}
        />
      </div>
    );
  }

  if (selection?.mode === 'open') {
    const sub = selection.submission;
    return (
      <div className={className}>
        <ChecklistRunnerCompact
          key={sub.id}
          projectId={projectId}
          template={{ id: sub.template_id ?? sub.id }}
          submissionId={sub.id}
          issueContext={issueContext}
          onCancel={() => setSelection(null)}
        />
      </div>
    );
  }

  /* -- Picker -------------------------------------------------------------- */

  return (
    <div className={clsx('flex flex-col gap-3', className)}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5 text-sm font-semibold text-content-primary">
          <Link2 size={15} className="shrink-0 text-oe-blue" />
          <span className="truncate">{t('forms.attach_checklist', { defaultValue: 'Attach a checklist' })}</span>
        </div>
        {onClose && (
          <button
            type="button"
            aria-label={t('common.close', { defaultValue: 'Close' })}
            onClick={onClose}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={15} />
          </button>
        )}
      </div>

      {/* Already attached */}
      {attachedLoading ? (
        <div className="flex items-center gap-2 text-xs text-content-tertiary">
          <Loader2 size={13} className="animate-spin" />
          {t('forms.loading_attached', { defaultValue: 'Checking attached checklists...' })}
        </div>
      ) : attached.length > 0 ? (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-content-tertiary">
            {t('forms.attached_checklists', { defaultValue: 'Attached checklists' })}
          </p>
          <div className="overflow-hidden rounded-lg border border-border">
            {attached.map((sub, i) => (
              <AttachedRow
                key={sub.id}
                submission={sub}
                first={i === 0}
                onOpen={() => setSelection({ mode: 'open', submission: sub })}
              />
            ))}
          </div>
        </div>
      ) : null}

      {/* Template picker */}
      <div className="relative">
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
        <input
          className={clsx(inputCls, 'pl-9')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('forms.search_templates', { defaultValue: 'Search templates' })}
        />
      </div>

      {templatesLoading ? (
        <div className="flex items-center justify-center py-6 text-content-tertiary">
          <Loader2 size={18} className="animate-spin" />
        </div>
      ) : templates.length === 0 ? (
        <EmptyState
          icon={<ClipboardList size={26} strokeWidth={1.5} />}
          title={t('forms.no_templates', { defaultValue: 'No templates yet' })}
          description={t('forms.no_templates_pick_desc', {
            defaultValue: 'Create a checklist template in the Forms workspace, then attach it here.',
          })}
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          {templates.map((tpl, i) => (
            <TemplateRow
              key={tpl.id}
              tpl={tpl}
              first={i === 0}
              onPick={() => setSelection({ mode: 'new', templateId: tpl.id })}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* -- Rows ------------------------------------------------------------------ */

function TemplateRow({ tpl, first, onPick }: { tpl: TemplateSummary; first: boolean; onPick: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onPick}
      className={clsx(
        'flex w-full items-center gap-3 bg-surface-primary px-3 py-2.5 text-left hover:bg-surface-secondary',
        !first && 'border-t border-border-light',
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-content-primary">{tpl.name}</div>
        <div className="mt-0.5 flex items-center gap-1.5 text-xs text-content-tertiary">
          <Layers size={12} />
          {t('forms.n_fields', { defaultValue: '{{count}} fields', count: tpl.field_count })}
          <span>·</span>
          <span>v{tpl.version}</span>
        </div>
      </div>
      <Badge variant={CATEGORY_BADGE[tpl.category]} size="sm">
        {CATEGORY_LABELS[tpl.category]}
      </Badge>
      <ChevronRight size={16} className="shrink-0 text-content-tertiary" />
    </button>
  );
}

function AttachedRow({
  submission,
  first,
  onOpen,
}: {
  submission: SubmissionDetail;
  first: boolean;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={clsx(
        'flex w-full items-center gap-3 bg-surface-primary px-3 py-2 text-left hover:bg-surface-secondary',
        !first && 'border-t border-border-light',
      )}
    >
      <ClipboardList size={15} className="shrink-0 text-content-tertiary" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-content-primary">{submission.template_name}</div>
        <div className="truncate text-xs text-content-tertiary">{submission.submission_number}</div>
      </div>
      <AttachedResultBadge status={submission.status} result={submission.result} />
    </button>
  );
}

function AttachedResultBadge({ status, result }: { status: SubmissionDetail['status']; result: FormResult }) {
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
