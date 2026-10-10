// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Clause template library: the catalogue, and the authoring screen behind it.
 *
 * The catalogue has two halves that are stored completely differently. The
 * built-in standard forms are constants the platform ships and nobody can
 * edit; a tenant's own paper is rows, versioned, where publishing freezes a
 * version and the next edit opens N+1. The API unions them into one shape and
 * marks each entry with `source` and `editable`, so this screen never has to
 * infer which half a row came from — it reads those two fields.
 *
 * The one rule worth stating here: a published version is never edited in
 * place, because a contract may already name it. "Edit" on published paper
 * opens the next version, and that is why the button says so.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  BookOpen,
  Plus,
  GitFork,
  Lock,
  PenLine,
  Trash2,
  ArrowUp,
  ArrowDown,
  CheckCircle2,
  Archive,
  Loader2,
  History,
  Save,
} from 'lucide-react';
import { Badge, Button, EmptyState, SkeletonTable } from '@/shared/ui';
import {
  WideModal,
  WideModalSection,
  WideModalField,
} from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { matchesSearch } from '@/shared/lib/highlightMatch';
import {
  listClauseTemplates,
  getClauseTemplate,
  listClauseTemplateVersions,
  createClauseTemplate,
  forkClauseTemplate,
  setClauseTemplateClauses,
  publishClauseTemplate,
  openNextClauseTemplateVersion,
  archiveClauseTemplateVersion,
  type ClauseTemplate,
  type ClauseRiskLevel,
  type RetentionReleaseEvent,
  type TemplateClause,
  type TemplateStatus,
} from './api';
import { retentionEventLabel } from './RetentionReleasePanel';

const inputCls =
  'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue';

const RISK_LEVELS: ClauseRiskLevel[] = ['none', 'low', 'medium', 'high'];

const RISK_VARIANT: Record<ClauseRiskLevel, 'neutral' | 'blue' | 'warning' | 'error'> = {
  none: 'neutral',
  low: 'blue',
  medium: 'warning',
  high: 'error',
};

const STATUS_VARIANT: Record<TemplateStatus, 'neutral' | 'success' | 'warning'> = {
  draft: 'warning',
  published: 'success',
  archived: 'neutral',
};

// The canonical events the server stores. It reads the older names
// (practical completion, final account, handover) and answers with these.
const RETENTION_EVENTS: RetentionReleaseEvent[] = [
  'substantial_completion',
  'final_completion',
  'defects_period_end',
];

/** The catalogue query is shared with the empty-state chips on the register. */
export const TEMPLATE_CATALOGUE_KEY = ['contracts', 'clause-templates'];

function statusLabel(
  t: ReturnType<typeof useTranslation>['t'],
  status: TemplateStatus,
): string {
  if (status === 'draft') return t('contracts.tpl_status_draft', { defaultValue: 'Draft' });
  if (status === 'published')
    return t('contracts.tpl_status_published', { defaultValue: 'Published' });
  return t('contracts.tpl_status_archived', { defaultValue: 'Archived' });
}

function riskLabel(
  t: ReturnType<typeof useTranslation>['t'],
  risk: ClauseRiskLevel,
): string {
  if (risk === 'low') return t('contracts.tpl_risk_low', { defaultValue: 'Low' });
  if (risk === 'medium') return t('contracts.tpl_risk_medium', { defaultValue: 'Medium' });
  if (risk === 'high') return t('contracts.tpl_risk_high', { defaultValue: 'High' });
  return t('contracts.tpl_risk_none', { defaultValue: 'Not flagged' });
}

/* ─── Library (catalogue + detail) ─── */

export function ContractTemplatesPanel({ search }: { search: string }) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [forkOf, setForkOf] = useState<ClauseTemplate | null>(null);

  const catalogueQ = useQuery({
    queryKey: TEMPLATE_CATALOGUE_KEY,
    queryFn: listClauseTemplates,
  });

  const rows = useMemo(() => {
    const all = catalogueQ.data ?? [];
    if (!search.trim()) return all;
    return all.filter((row) => matchesSearch(search, row.code, row.name, row.family));
  }, [catalogueQ.data, search]);

  if (catalogueQ.isLoading) {
    return (
      <div className="p-4">
        <SkeletonTable rows={6} columns={4} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-0 lg:flex-row" data-testid="contracts-template-library">
      {/* Catalogue */}
      <div className="lg:w-[380px] lg:shrink-0 lg:border-r lg:border-border-light">
        <div className="flex items-center justify-between gap-2 border-b border-border-light px-4 py-2.5">
          <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
            <BookOpen size={13} />
            {t('contracts.tpl_catalogue', { defaultValue: 'Clause templates' })}
          </span>
          <Button
            size="sm"
            variant="secondary"
            icon={<Plus size={13} />}
            onClick={() => setCreateOpen(true)}
          >
            {t('contracts.tpl_new', { defaultValue: 'New template' })}
          </Button>
        </div>

        {rows.length === 0 ? (
          <div className="px-4 py-6 text-sm text-content-tertiary">
            {t('contracts.tpl_no_match', {
              defaultValue: 'No template matches that search.',
            })}
          </div>
        ) : (
          <ul className="max-h-[560px] overflow-y-auto">
            {rows.map((row) => (
              <li key={row.code}>
                <button
                  type="button"
                  onClick={() => setSelected(row.code)}
                  className={clsx(
                    'w-full border-b border-border-light px-4 py-2.5 text-left transition-colors',
                    selected === row.code
                      ? 'bg-oe-blue-subtle'
                      : 'hover:bg-surface-secondary',
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-content-primary">
                      {row.name}
                    </span>
                    {row.source === 'builtin' ? (
                      <Lock size={11} className="shrink-0 text-content-quaternary" />
                    ) : (
                      <Badge size="sm" variant={STATUS_VARIANT[row.status]}>
                        {statusLabel(t, row.status)}
                      </Badge>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-2xs text-content-tertiary">
                    <span className="font-mono">{row.code}</span>
                    {row.family && <span className="uppercase">{row.family}</span>}
                    {/* Version 0 is what a built-in reports: it is a constant,
                        not a version, so the number is not shown for it. */}
                    {row.version > 0 && <span>v{row.version}</span>}
                    <span>
                      {t('contracts.tpl_clause_count', {
                        defaultValue: '{{count}} clauses',
                        count: row.clause_count,
                      })}
                    </span>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Detail */}
      <div className="min-w-0 flex-1">
        {selected ? (
          <TemplateDetail key={selected} code={selected} onFork={(row) => setForkOf(row)} />
        ) : (
          <div className="px-6 py-12">
            <EmptyState
              icon={<BookOpen size={22} />}
              title={t('contracts.tpl_pick_title', { defaultValue: 'Pick a template' })}
              description={t('contracts.tpl_pick_desc', {
                defaultValue:
                  'Standard forms ship read-only. Fork one to get an editable copy under your own code, or write a template from scratch. A contract records the exact version it was drawn from.',
              })}
            />
          </div>
        )}
      </div>

      {createOpen && (
        <NewTemplateModal
          onClose={() => setCreateOpen(false)}
          onCreated={(code) => {
            setCreateOpen(false);
            setSelected(code);
          }}
        />
      )}

      {forkOf && (
        <ForkTemplateModal
          source={forkOf}
          onClose={() => setForkOf(null)}
          onForked={(code) => {
            setForkOf(null);
            setSelected(code);
          }}
        />
      )}
    </div>
  );
}

/* ─── Detail ─── */

/**
 * Mounted with `key={code}`, so switching template resets the local clause
 * edits with the component rather than leaving one template's unsaved rows
 * sitting on another's screen.
 */
function TemplateDetail({
  code,
  onFork,
}: {
  code: string;
  onFork: (row: ClauseTemplate) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [version, setVersion] = useState<number | undefined>(undefined);
  const [draftClauses, setDraftClauses] = useState<TemplateClause[] | null>(null);

  const detailQ = useQuery({
    queryKey: ['contracts', 'clause-template', code, version ?? 'current'],
    queryFn: () => getClauseTemplate(code, version),
  });
  const versionsQ = useQuery({
    queryKey: ['contracts', 'clause-template-versions', code],
    queryFn: () => listClauseTemplateVersions(code),
  });

  const detail = detailQ.data;
  // Local edits win while they exist; discarding them falls back to the
  // server's answer rather than to a second copy of it.
  const clauses = draftClauses ?? detail?.clauses ?? [];
  const dirty = draftClauses !== null;

  const refresh = () => {
    qc.invalidateQueries({ queryKey: TEMPLATE_CATALOGUE_KEY });
    qc.invalidateQueries({ queryKey: ['contracts', 'clause-template', code] });
    qc.invalidateQueries({ queryKey: ['contracts', 'clause-template-versions', code] });
  };

  const run = useMutation({
    mutationFn: async (action: 'save' | 'publish' | 'next' | 'archive') => {
      const v = detail?.version ?? 0;
      if (action === 'save') return setClauseTemplateClauses(code, v, clauses);
      if (action === 'publish') return publishClauseTemplate(code, v);
      if (action === 'next') return openNextClauseTemplateVersion(code);
      return archiveClauseTemplateVersion(code, v);
    },
    onSuccess: (result, action) => {
      setDraftClauses(null);
      // Opening the next version has to move the screen onto it, otherwise the
      // user edits the version they just froze and wonders why nothing sticks.
      setVersion(action === 'next' ? result.version : undefined);
      refresh();
      addToast({
        type: 'success',
        title:
          action === 'save'
            ? t('contracts.tpl_saved', { defaultValue: 'Clauses saved' })
            : action === 'publish'
              ? t('contracts.tpl_published', { defaultValue: 'Version published' })
              : action === 'next'
                ? t('contracts.tpl_next_opened', {
                    defaultValue: 'Version {{version}} opened as a draft',
                    version: result.version,
                  })
                : t('contracts.tpl_archived', { defaultValue: 'Version archived' }),
      });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (detailQ.isLoading) {
    return (
      <div className="p-4">
        <SkeletonTable rows={6} columns={3} />
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="px-6 py-10 text-sm text-content-tertiary">
        {t('contracts.tpl_load_failed', {
          defaultValue: 'This template could not be loaded.',
        })}
      </div>
    );
  }

  const builtin = detail.source === 'builtin';
  const editable = detail.editable;
  const versions = versionsQ.data ?? [];

  // Both of these rebuild the list rather than assigning into a copy by index.
  // Under noUncheckedIndexedAccess a read like next[i] is possibly undefined, so
  // an index assignment widens the element type and the array stops being a
  // TemplateClause[]. Mapping and splicing keep the element type intact.
  const update = (index: number, patch: Partial<TemplateClause>) => {
    setDraftClauses(clauses.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  };
  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= clauses.length) return;
    const next = [...clauses];
    const [moved] = next.splice(index, 1);
    if (!moved) return;
    next.splice(target, 0, moved);
    setDraftClauses(next.map((c, i) => ({ ...c, sort_order: i })));
  };
  const remove = (index: number) => {
    setDraftClauses(
      clauses.filter((_, i) => i !== index).map((c, i) => ({ ...c, sort_order: i })),
    );
  };
  const add = () => {
    setDraftClauses([
      ...clauses,
      {
        number: '',
        title: '',
        body: '',
        sort_order: clauses.length,
        risk_level: 'none',
        risk_note: '',
        is_optional: false,
      },
    ]);
  };

  return (
    <div className="flex min-w-0 flex-col">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border-light px-5 py-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-base font-semibold text-content-primary">
              {detail.name}
            </h3>
            {builtin ? (
              <Badge size="sm" variant="blue">
                {t('contracts.tpl_standard_form', { defaultValue: 'Standard form' })}
              </Badge>
            ) : (
              <Badge size="sm" variant={STATUS_VARIANT[detail.status]}>
                {statusLabel(t, detail.status)}
              </Badge>
            )}
          </div>
          <p className="mt-0.5 flex flex-wrap items-center gap-2 text-2xs text-content-tertiary">
            <span className="font-mono">{detail.code}</span>
            {detail.version > 0 && <span>v{detail.version}</span>}
            {detail.family && <span className="uppercase">{detail.family}</span>}
            {detail.derived_from_builtin && (
              <span>
                {t('contracts.tpl_forked_from', {
                  defaultValue: 'forked from {{code}}',
                  code: detail.derived_from_builtin,
                })}
              </span>
            )}
          </p>
          {detail.description && (
            <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-content-secondary">
              {detail.description}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {builtin && (
            <Button
              size="sm"
              variant="secondary"
              icon={<GitFork size={13} />}
              onClick={() => onFork(detail)}
            >
              {t('contracts.tpl_fork', { defaultValue: 'Fork into my paper' })}
            </Button>
          )}
          {!builtin && editable && (
            <>
              <Button
                size="sm"
                variant="secondary"
                icon={run.isPending ? <Loader2 size={13} /> : <Save size={13} />}
                disabled={!dirty || run.isPending}
                onClick={() => run.mutate('save')}
              >
                {t('contracts.tpl_save_clauses', { defaultValue: 'Save clauses' })}
              </Button>
              <Button
                size="sm"
                variant="primary"
                icon={<CheckCircle2 size={13} />}
                disabled={dirty || run.isPending || clauses.length === 0}
                onClick={() => run.mutate('publish')}
              >
                {t('contracts.tpl_publish', { defaultValue: 'Publish' })}
              </Button>
            </>
          )}
          {!builtin && !editable && detail.status === 'published' && (
            <>
              <Button
                size="sm"
                variant="secondary"
                icon={<PenLine size={13} />}
                disabled={run.isPending}
                onClick={() => run.mutate('next')}
              >
                {t('contracts.tpl_open_next', {
                  defaultValue: 'Edit as version {{version}}',
                  version: detail.version + 1,
                })}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                icon={<Archive size={13} />}
                disabled={run.isPending}
                onClick={() => run.mutate('archive')}
              >
                {t('contracts.tpl_archive', { defaultValue: 'Retire' })}
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Why the paper is read-only, said once, where the pencil would be */}
      {!builtin && !editable && detail.status === 'published' && (
        <p className="border-b border-border-light bg-surface-secondary px-5 py-2 text-2xs text-content-tertiary">
          {t('contracts.tpl_frozen_hint', {
            defaultValue:
              'A published version is frozen because a contract may already name it. Editing opens the next version and leaves this one saying what it says.',
          })}
        </p>
      )}
      {builtin && (
        <p className="border-b border-border-light bg-surface-secondary px-5 py-2 text-2xs text-content-tertiary">
          {t('contracts.tpl_builtin_hint', {
            defaultValue:
              'Standard forms ship with the platform and carry clause numbers and headings, not contract language. Fork one to write your own wording under your own code.',
          })}
        </p>
      )}

      {/* Version history */}
      {versions.length > 1 && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-border-light px-5 py-2 text-2xs">
          <History size={12} className="text-content-tertiary" aria-hidden />
          <span className="text-content-tertiary">
            {t('contracts.tpl_versions', { defaultValue: 'Versions:' })}
          </span>
          {versions.map((row) => (
            <button
              key={row.version}
              type="button"
              onClick={() => {
                setDraftClauses(null);
                setVersion(row.version);
              }}
              className={clsx(
                'rounded-md px-1.5 py-0.5 font-medium ring-1 ring-inset transition-colors',
                row.version === detail.version
                  ? 'bg-oe-blue-subtle text-oe-blue-text ring-oe-blue/30'
                  : 'bg-surface-secondary text-content-secondary ring-border-light hover:text-content-primary',
              )}
            >
              v{row.version} · {statusLabel(t, row.status)}
            </button>
          ))}
        </div>
      )}

      {/* Clauses */}
      <div className="min-w-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
            <tr>
              <th className="w-24 px-3 py-2 text-left">
                {t('contracts.tpl_col_number', { defaultValue: 'No.' })}
              </th>
              <th className="px-3 py-2 text-left">
                {t('contracts.tpl_col_title', { defaultValue: 'Clause' })}
              </th>
              <th className="w-32 px-3 py-2 text-left">
                {t('contracts.tpl_col_risk', { defaultValue: 'Risk' })}
              </th>
              {editable && <th className="w-24 px-3 py-2" />}
            </tr>
          </thead>
          <tbody>
            {clauses.length === 0 && (
              <tr>
                <td
                  colSpan={editable ? 4 : 3}
                  className="px-3 py-6 text-center text-xs text-content-tertiary"
                >
                  {t('contracts.tpl_no_clauses', {
                    defaultValue: 'No clauses yet. A version with no clauses cannot be published.',
                  })}
                </td>
              </tr>
            )}
            {clauses.map((clause, index) => (
              <tr key={clause.id ?? `row-${index}`} className="border-t border-border-light align-top">
                <td className="px-3 py-2">
                  {editable ? (
                    <input
                      value={clause.number}
                      onChange={(e) => update(index, { number: e.target.value })}
                      className={clsx(inputCls, 'px-2 py-1 font-mono text-xs')}
                      placeholder="14.3"
                      aria-label={t('contracts.tpl_col_number', { defaultValue: 'No.' })}
                    />
                  ) : (
                    <span className="font-mono text-xs text-content-secondary">
                      {clause.number}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  {editable ? (
                    <div className="flex flex-col gap-1.5">
                      <input
                        value={clause.title}
                        onChange={(e) => update(index, { title: e.target.value })}
                        className={clsx(inputCls, 'px-2 py-1 text-xs font-medium')}
                        placeholder={t('contracts.tpl_col_title', { defaultValue: 'Clause' })}
                        aria-label={t('contracts.tpl_col_title', { defaultValue: 'Clause' })}
                      />
                      <textarea
                        value={clause.body}
                        onChange={(e) => update(index, { body: e.target.value })}
                        rows={2}
                        className={clsx(inputCls, 'px-2 py-1 text-xs')}
                        placeholder={t('contracts.tpl_body_placeholder', {
                          defaultValue: 'Clause wording',
                        })}
                        aria-label={t('contracts.tpl_body_placeholder', {
                          defaultValue: 'Clause wording',
                        })}
                      />
                      <label className="flex items-center gap-1.5 text-2xs text-content-tertiary">
                        <input
                          type="checkbox"
                          checked={clause.is_optional}
                          onChange={(e) => update(index, { is_optional: e.target.checked })}
                        />
                        {t('contracts.tpl_optional', { defaultValue: 'Optional clause' })}
                      </label>
                    </div>
                  ) : (
                    <div>
                      <span className="font-medium text-content-primary">
                        {clause.title || '—'}
                      </span>
                      {clause.body && (
                        <p className="mt-0.5 whitespace-pre-line text-xs leading-relaxed text-content-secondary">
                          {clause.body}
                        </p>
                      )}
                      {clause.is_optional && (
                        <span className="mt-1 inline-block text-2xs text-content-tertiary">
                          {t('contracts.tpl_optional', { defaultValue: 'Optional clause' })}
                        </span>
                      )}
                    </div>
                  )}
                </td>
                <td className="px-3 py-2">
                  {editable ? (
                    <select
                      value={clause.risk_level}
                      onChange={(e) =>
                        update(index, { risk_level: e.target.value as ClauseRiskLevel })
                      }
                      className={clsx(inputCls, 'px-2 py-1 text-xs')}
                      aria-label={t('contracts.tpl_col_risk', { defaultValue: 'Risk' })}
                    >
                      {RISK_LEVELS.map((level) => (
                        <option key={level} value={level}>
                          {riskLabel(t, level)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <Badge size="sm" variant={RISK_VARIANT[clause.risk_level]}>
                      {riskLabel(t, clause.risk_level)}
                    </Badge>
                  )}
                </td>
                {editable && (
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-0.5">
                      <IconAction
                        label={t('common.move_up', { defaultValue: 'Move up' })}
                        onClick={() => move(index, -1)}
                        disabled={index === 0}
                      >
                        <ArrowUp size={13} />
                      </IconAction>
                      <IconAction
                        label={t('common.move_down', { defaultValue: 'Move down' })}
                        onClick={() => move(index, 1)}
                        disabled={index === clauses.length - 1}
                      >
                        <ArrowDown size={13} />
                      </IconAction>
                      <IconAction
                        label={t('common.delete', { defaultValue: 'Delete' })}
                        onClick={() => remove(index)}
                      >
                        <Trash2 size={13} />
                      </IconAction>
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editable && (
        <div className="flex items-center justify-between gap-2 border-t border-border-light px-5 py-2.5">
          <Button size="sm" variant="ghost" icon={<Plus size={13} />} onClick={add}>
            {t('contracts.tpl_add_clause', { defaultValue: 'Add clause' })}
          </Button>
          {dirty && (
            <span className="text-2xs text-content-tertiary">
              {t('contracts.tpl_unsaved', {
                defaultValue: 'Unsaved changes. Save before publishing.',
              })}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function IconAction({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="rounded-md p-1 text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary disabled:cursor-not-allowed disabled:opacity-40"
    >
      {children}
    </button>
  );
}

/* ─── New template ─── */

function NewTemplateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (code: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({
    code: '',
    name: '',
    family: '',
    description: '',
    retention_release_event: 'substantial_completion' as RetentionReleaseEvent,
  });
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!form.code.trim() || !form.name.trim()) {
      addToast({
        type: 'error',
        title: t('contracts.tpl_code_name_required', {
          defaultValue: 'A template needs a code and a name.',
        }),
      });
      return;
    }
    setBusy(true);
    try {
      const created = await createClauseTemplate({
        code: form.code.trim(),
        name: form.name.trim(),
        family: form.family.trim(),
        description: form.description,
        retention_release_event: form.retention_release_event,
      });
      qc.invalidateQueries({ queryKey: TEMPLATE_CATALOGUE_KEY });
      addToast({
        type: 'success',
        title: t('contracts.tpl_created', { defaultValue: 'Template created as a draft' }),
      });
      onCreated(created.code);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      title={t('contracts.tpl_new', { defaultValue: 'New template' })}
      subtitle={t('contracts.tpl_new_sub', {
        defaultValue: 'Starts at version 1, in draft. Add the clauses next, then publish.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <Plus size={14} />}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection
        title={t('contracts.section_basic', { defaultValue: 'Basic info' })}
        columns={2}
      >
        <WideModalField label={t('contracts.code', { defaultValue: 'Code' })} required>
          <input
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            className={inputCls}
            placeholder="own_subcontract_2026"
          />
        </WideModalField>
        <WideModalField label={t('contracts.tpl_name', { defaultValue: 'Name' })} required>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('contracts.tpl_family', { defaultValue: 'Family' })}
          hint={t('contracts.tpl_family_hint', {
            defaultValue: 'Free text used to group the catalogue, not a fixed list.',
          })}
        >
          <input
            value={form.family}
            onChange={(e) => setForm({ ...form, family: e.target.value })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('contracts.retention_release', { defaultValue: 'Retention release' })}
        >
          <select
            value={form.retention_release_event}
            onChange={(e) =>
              setForm({
                ...form,
                retention_release_event: e.target.value as RetentionReleaseEvent,
              })
            }
            className={inputCls}
          >
            {RETENTION_EVENTS.map((event) => (
              <option key={event} value={event}>
                {retentionEventLabel(t, event)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField
          label={t('contracts.tpl_description', { defaultValue: 'Description' })}
          span={2}
        >
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            rows={3}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ─── Fork ─── */

function ForkTemplateModal({
  source,
  onClose,
  onForked,
}: {
  source: ClauseTemplate;
  onClose: () => void;
  onForked: (code: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [newCode, setNewCode] = useState(`${source.code}_own`);
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!newCode.trim()) return;
    setBusy(true);
    try {
      const forked = await forkClauseTemplate(source.code, {
        new_code: newCode.trim(),
        new_name: newName.trim() || null,
      });
      qc.invalidateQueries({ queryKey: TEMPLATE_CATALOGUE_KEY });
      addToast({
        type: 'success',
        title: t('contracts.tpl_forked', { defaultValue: 'Editable copy created' }),
      });
      onForked(forked.code);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="md"
      title={t('contracts.tpl_fork', { defaultValue: 'Fork into my paper' })}
      subtitle={t('contracts.tpl_fork_sub', {
        defaultValue:
          'Copies the clause numbers and headings of {{name}} under a new code. The wording starts empty, because the standard form ships headings rather than contract language.',
        name: source.name,
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            icon={busy ? <Loader2 size={14} /> : <GitFork size={14} />}
          >
            {t('contracts.tpl_fork_action', { defaultValue: 'Create copy' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField label={t('contracts.tpl_new_code', { defaultValue: 'New code' })} required>
          <input
            value={newCode}
            onChange={(e) => setNewCode(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('contracts.tpl_new_name', { defaultValue: 'New name' })}
          hint={t('contracts.tpl_new_name_hint', {
            defaultValue: 'Left empty, the name of the standard form is carried over.',
          })}
        >
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className={inputCls}
            placeholder={source.name}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
