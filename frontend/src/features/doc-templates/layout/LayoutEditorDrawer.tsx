// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Customize document": the block editor of one record document in a side
 * drawer, with a live server preview beside it.
 *
 * The firm edits a draft; the preview renders it on the record the editor was
 * opened from (or on sample data) a moment after each change. Publishing
 * checks locks and merge fields on the server and refuses errors. The scope
 * switch picks the company default or this project's override; variants are
 * named layouts of the same document, one of them the default. Undo and redo
 * cover every edit of the session (Ctrl+Z, Ctrl+Shift+Z or Ctrl+Y).
 *
 * Read-only for readers without the Document manager role and on narrow
 * screens, where the preview alone is shown.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Download, Loader2, Redo2, RotateCcw, Undo2, Upload } from 'lucide-react';

import { SideDrawer } from '@/shared/ui/SideDrawer';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import {
  deleteLayoutVariant,
  diffLayoutVersion,
  discardLayoutDraft,
  exportLayout,
  fetchLayoutPreview,
  getLayout,
  getLayoutValues,
  importLayout,
  listClauses,
  makeLayoutDefault,
  publishLayout,
  resetLayout,
  restoreLayoutVersion,
  saveLayoutDraft,
  type LayoutChange,
  type LayoutEditorData,
  type LayoutTarget,
  type LayoutTemplate,
} from './layoutApi';
import { historyOf, historyPush, historyRedo, historyUndo, variantKey, type History } from './layoutModel';
import { BrandingPanel, ContentPanel, HistoryPanel, LayoutPanel } from './LayoutPanels';
import { INPUT } from './BlockEditor';

type Tab = 'content' | 'layout' | 'branding' | 'history';
const TABS: Tab[] = ['content', 'layout', 'branding', 'history'];
const PREVIEW_DELAY_MS = 700;
const NARROW_PX = 768;

export interface LayoutEditorDrawerProps {
  open: boolean;
  onClose: () => void;
  /** Layout key, e.g. `procurement.purchase_order`. */
  layoutKey: string;
  /** The record the editor was opened from: the preview prints it. */
  recordId?: string | null;
  /** Project of that record: enables the "this project" scope. */
  projectId?: string | null;
  /** Document language picked in the export menu. */
  locale?: string;
  /** Translated document name for the title. */
  title?: string;
}

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.innerWidth < NARROW_PX);
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < NARROW_PX);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return narrow;
}

function errorText(err: unknown): string {
  if (err && typeof err === 'object' && 'detail' in err) {
    const detail = (err as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message);
  }
  return err instanceof Error ? err.message : String(err);
}

export function LayoutEditorDrawer({ open, onClose, layoutKey, recordId, projectId, locale: initialLocale, title }: LayoutEditorDrawerProps) {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const narrow = useNarrow();
  const [tab, setTab] = useState<Tab>('content');
  const [scope, setScope] = useState<'workspace' | 'project'>(projectId ? 'project' : 'workspace');
  const [variant, setVariant] = useState('standard');
  const [locale, setLocale] = useState(initialLocale || i18n.language?.split('-')[0] || 'en');
  const [history, setHistory] = useState<History<LayoutTemplate> | null>(null);
  const [savedTemplate, setSavedTemplate] = useState<LayoutTemplate | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [diff, setDiff] = useState<{ versionId: string; changes: LayoutChange[] } | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [newVariant, setNewVariant] = useState<string | null>(null);
  const { confirm, ...confirmProps } = useConfirm();

  const target: LayoutTarget = useMemo(
    () => ({ key: layoutKey, projectId: scope === 'project' ? projectId : null, variant, locale }),
    [layoutKey, scope, projectId, variant, locale],
  );
  const queryKey = ['doc-layout', layoutKey, target.projectId ?? 'workspace', variant, locale];
  const query = useQuery({ queryKey, queryFn: () => getLayout(target), enabled: open });
  const clausesQuery = useQuery({ queryKey: ['doc-layout-clauses'], queryFn: listClauses, enabled: open });
  const valuesQuery = useQuery({
    queryKey: ['doc-layout-values', layoutKey, locale, recordId ?? null],
    queryFn: () => getLayoutValues(layoutKey, locale, recordId ?? null),
    enabled: open,
  });

  const data = query.data;
  // A fresh state from the server replaces the working copy (load, publish, restore, switch).
  const accept = useCallback(
    (next: LayoutEditorData) => {
      queryClient.setQueryData(queryKey, next);
      setHistory(historyOf(next.state.template));
      setSavedTemplate(next.state.template);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queryClient, layoutKey, target.projectId, variant, locale],
  );
  useEffect(() => {
    if (data) {
      setHistory(historyOf(data.state.template));
      setSavedTemplate(data.state.template);
    }
  }, [data]);

  const template = history?.present ?? null;
  const dirty = template !== null && template !== savedTemplate;
  const readOnly = !data?.can_edit || narrow;

  const change = useCallback((next: LayoutTemplate) => setHistory((h) => (h ? historyPush(h, next) : h)), []);
  const undo = useCallback(() => setHistory((h) => (h ? historyUndo(h) : h)), []);
  const redo = useCallback(() => setHistory((h) => (h ? historyRedo(h) : h)), []);

  useEffect(() => {
    if (!open || readOnly) return;
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return; // native undo inside a field
      if (e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey)) {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, readOnly, undo, redo]);

  // Live preview, debounced; an older request is cancelled by a newer one.
  useEffect(() => {
    if (!open || !template) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setPreviewing(true);
      try {
        const blob = await fetchLayoutPreview(layoutKey, locale, template, recordId ?? null, controller.signal);
        const url = URL.createObjectURL(blob);
        setPreviewUrl((old) => {
          if (old) URL.revokeObjectURL(old);
          return url;
        });
        setPreviewError(false);
      } catch (err) {
        if (!controller.signal.aborted) setPreviewError(true);
      } finally {
        if (!controller.signal.aborted) setPreviewing(false);
      }
    }, PREVIEW_DELAY_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [open, template, layoutKey, locale, recordId]);
  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const run = async (action: () => Promise<LayoutEditorData | void>, success?: string) => {
    setBusy(true);
    try {
      const next = await action();
      if (next) accept(next);
      if (success) addToast({ type: 'success', title: success });
    } catch (err) {
      addToast({ type: 'error', title: t('doc_layout.failed', { defaultValue: 'That did not work' }), message: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  const saveDraft = () => template && run(() => saveLayoutDraft(target, template), t('doc_layout.saved', { defaultValue: 'Draft saved' }));
  const publish = () =>
    template &&
    run(async () => {
      if (dirty) await saveLayoutDraft(target, template);
      const next = await publishLayout(target, note);
      setNote('');
      return next;
    }, t('doc_layout.published', { defaultValue: 'Published: new documents print with this layout' }));

  const onImport = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text()) as Record<string, unknown>;
      await run(() => importLayout(target, parsed), t('doc_layout.imported', { defaultValue: 'Imported into the draft' }));
    } catch {
      addToast({ type: 'error', title: t('doc_layout.import_bad', { defaultValue: 'This file is not a document layout' }) });
    }
  };
  const onExport = () =>
    run(async () => {
      const body = await exportLayout(target);
      const blob = new Blob([JSON.stringify(body, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${layoutKey.replace('.', '-')}-${variant}.json`;
      a.click();
      URL.revokeObjectURL(url);
    });

  const issues = data?.state.issues ?? [];
  const errors = issues.filter((i) => i.severity === 'error');
  const spec = data?.spec;
  const state = data?.state;
  const panelProps =
    spec && template
      ? {
          template,
          spec,
          locale,
          readOnly,
          samples: valuesQuery.data?.values ?? {},
          clauses: clausesQuery.data?.items ?? [],
          onChange: change,
        }
      : null;

  const subtitle = state
    ? state.inherits === 'standard'
      ? t('doc_layout.inherits_standard', { defaultValue: 'Standard layout in force' })
      : state.inherits === 'workspace'
        ? t('doc_layout.inherits_company', { defaultValue: 'Company layout in force; edits here apply to this project only' })
        : t('doc_layout.version_in_force', { defaultValue: 'Version {{n}} in force', n: state.published_number })
    : undefined;

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      title={title ?? t('doc_layout.customize', { defaultValue: 'Customize document' })}
      subtitle={subtitle}
      widthClass="max-w-[min(1240px,100vw)]"
      backdropCloses={!dirty}
      busy={busy}
    >
      {!data || !template || !spec || !state || !panelProps ? (
        <div className="flex h-40 items-center justify-center text-content-tertiary">
          {query.isError ? errorText(query.error) : <Loader2 className="animate-spin" size={18} />}
        </div>
      ) : (
        <div className="flex h-full min-h-0 flex-col gap-3 lg:flex-row" data-testid="layout-editor">
          {!narrow && (
            <div className="flex min-h-0 w-full flex-col gap-3 lg:w-[30rem] lg:shrink-0">
              <div className="flex flex-wrap items-center gap-2">
                {projectId && (
                  <div role="radiogroup" aria-label={t('doc_layout.scope', { defaultValue: 'Applies to' })} className="inline-flex rounded-md border border-border-light p-0.5">
                    {(['workspace', 'project'] as const).map((s) => (
                      <button
                        key={s}
                        type="button"
                        role="radio"
                        aria-checked={scope === s}
                        disabled={busy || dirty}
                        title={dirty ? t('doc_layout.save_first', { defaultValue: 'Save or undo your changes first' }) : undefined}
                        onClick={() => setScope(s)}
                        className={clsx('rounded px-2 py-0.5 text-xs', scope === s ? 'bg-oe-blue/10 text-oe-blue-text' : 'text-content-secondary')}
                        data-testid={`layout-scope-${s}`}
                      >
                        {s === 'workspace' ? t('doc_layout.scope_company', { defaultValue: 'Company default' }) : t('doc_layout.scope_project', { defaultValue: 'This project' })}
                      </button>
                    ))}
                  </div>
                )}
                <select
                  className={clsx(INPUT, 'h-7 w-auto text-xs')}
                  value={variant}
                  disabled={busy || dirty}
                  aria-label={t('doc_layout.variant', { defaultValue: 'Variant' })}
                  onChange={(e) => {
                    if (e.target.value === '__new__') {
                      setNewVariant('');
                      return;
                    }
                    setVariant(e.target.value);
                  }}
                  data-testid="layout-variant"
                >
                  {[...new Set(['standard', ...state.variants.map((v) => v.variant), variant])].map((v) => {
                    const info = state.variants.find((x) => x.variant === v);
                    return (
                      <option key={v} value={v}>
                        {(info?.name || v) + (info?.is_default ? ` (${t('doc_layout.default', { defaultValue: 'default' })})` : '')}
                      </option>
                    );
                  })}
                  {!readOnly && <option value="__new__">{t('doc_layout.new_variant', { defaultValue: '+ New variant' })}</option>}
                </select>
                <select className={clsx(INPUT, 'h-7 w-auto text-xs')} value={locale} aria-label={t('doc_layout.edit_language', { defaultValue: 'Editing language' })} onChange={(e) => setLocale(e.target.value)} data-testid="layout-language">
                  {spec.languages.map((l) => (
                    <option key={l} value={l}>
                      {l.toUpperCase()}
                    </option>
                  ))}
                </select>
                <div className="ml-auto flex items-center gap-0.5">
                  <button type="button" className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-surface-secondary disabled:opacity-30" disabled={readOnly || !history?.past.length} onClick={undo} aria-label={t('doc_layout.undo', { defaultValue: 'Undo' })} title={t('doc_layout.undo', { defaultValue: 'Undo' })} data-testid="layout-undo">
                    <Undo2 size={14} />
                  </button>
                  <button type="button" className="inline-flex h-7 w-7 items-center justify-center rounded-md hover:bg-surface-secondary disabled:opacity-30" disabled={readOnly || !history?.future.length} onClick={redo} aria-label={t('doc_layout.redo', { defaultValue: 'Redo' })} title={t('doc_layout.redo', { defaultValue: 'Redo' })} data-testid="layout-redo">
                    <Redo2 size={14} />
                  </button>
                </div>
              </div>
              {newVariant !== null && (
                <form
                  className="flex items-center gap-1.5"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const key = variantKey(newVariant);
                    if (key) setVariant(key);
                    setNewVariant(null);
                  }}
                  data-testid="layout-new-variant"
                >
                  <input
                    autoFocus
                    className={clsx(INPUT, 'h-7 flex-1 text-xs')}
                    value={newVariant}
                    maxLength={40}
                    placeholder={t('doc_layout.variant_name', { defaultValue: 'Name of the new variant' })}
                    aria-label={t('doc_layout.variant_name', { defaultValue: 'Name of the new variant' })}
                    onChange={(e) => setNewVariant(e.target.value)}
                    onKeyDown={(e) => e.key === 'Escape' && setNewVariant(null)}
                  />
                  <button type="submit" disabled={!variantKey(newVariant)} className="rounded-md bg-oe-blue px-2 py-1 text-xs font-medium text-white disabled:opacity-40">
                    {t('doc_layout.variant_create', { defaultValue: 'Create' })}
                  </button>
                  <button type="button" onClick={() => setNewVariant(null)} className="rounded-md px-2 py-1 text-xs text-content-secondary hover:bg-surface-secondary">
                    {t('common.cancel', { defaultValue: 'Cancel' })}
                  </button>
                </form>
              )}
              {!data.can_edit && (
                <p className="rounded-md bg-surface-secondary px-3 py-2 text-xs text-content-secondary">
                  {t('doc_layout.read_only', { defaultValue: 'You can look at the layout. Changing it needs the Document manager role.' })}
                </p>
              )}
              <div role="tablist" className="flex gap-1 border-b border-border-light" aria-label={t('doc_layout.customize', { defaultValue: 'Customize document' })}>
                {TABS.map((id) => (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    aria-selected={tab === id}
                    onClick={() => setTab(id)}
                    className={clsx('-mb-px border-b-2 px-3 py-1.5 text-sm', tab === id ? 'border-oe-blue text-content-primary' : 'border-transparent text-content-secondary hover:text-content-primary')}
                    data-testid={`layout-tab-${id}`}
                  >
                    {t(`doc_layout.tab_${id}`, { defaultValue: id[0]?.toUpperCase() + id.slice(1) })}
                  </button>
                ))}
              </div>
              <div role="tabpanel" className="min-h-0 flex-1 overflow-y-auto pr-1">
                {tab === 'content' && <ContentPanel {...panelProps} />}
                {tab === 'layout' && <LayoutPanel {...panelProps} />}
                {tab === 'branding' && <BrandingPanel {...panelProps} />}
                {tab === 'history' && (
                  <HistoryPanel
                    state={state}
                    readOnly={readOnly}
                    busy={busy}
                    diff={diff}
                    onRestore={(id) => run(() => restoreLayoutVersion(target, id), t('doc_layout.restored', { defaultValue: 'Restored as a new version' }))}
                    onDiff={async (id) => {
                      if (diff?.versionId === id) return setDiff(null);
                      try {
                        setDiff({ versionId: id, changes: (await diffLayoutVersion(layoutKey, id)).changes });
                      } catch (err) {
                        addToast({ type: 'error', title: errorText(err) });
                      }
                    }}
                  />
                )}
              </div>
              {errors.length > 0 && (
                <ul className="space-y-0.5 rounded-md border border-semantic-error/30 bg-semantic-error/5 px-3 py-2 text-xs text-semantic-error" role="alert" data-testid="layout-issues">
                  {errors.slice(0, 6).map((issue, i) => (
                    <li key={`${issue.rule_id}-${issue.block}-${i}`}>
                      {t(`doc_layout.rule.${issue.rule_id.replace('doctpl.', '')}`, {
                        defaultValue: issue.rule_id,
                        ...issue.params,
                      })}
                      {issue.block ? ` (${issue.block})` : ''}
                    </li>
                  ))}
                </ul>
              )}
              {!readOnly && (
                <div className="space-y-2 border-t border-border-light pt-2">
                  <input className={clsx(INPUT, 'text-xs')} value={note} maxLength={500} placeholder={t('doc_layout.note', { defaultValue: 'What changed (for the history)' })} onChange={(e) => setNote(e.target.value)} aria-label={t('doc_layout.note', { defaultValue: 'What changed (for the history)' })} />
                  <div className="flex flex-wrap items-center gap-1.5">
                    <button type="button" disabled={busy} onClick={publish} className="rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-oe-blue/90 disabled:opacity-50" data-testid="layout-publish">
                      {t('doc_layout.publish', { defaultValue: 'Publish' })}
                    </button>
                    <button type="button" disabled={busy || !dirty} onClick={saveDraft} className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-surface-secondary disabled:opacity-40" data-testid="layout-save-draft">
                      {t('doc_layout.save_draft', { defaultValue: 'Save draft' })}
                    </button>
                    {state.has_draft && (
                      <button type="button" disabled={busy} onClick={() => run(() => discardLayoutDraft(target))} className="rounded-md px-2 py-1.5 text-sm text-content-secondary hover:bg-surface-secondary">
                        {t('doc_layout.discard', { defaultValue: 'Discard draft' })}
                      </button>
                    )}
                    <span className="ml-auto flex items-center gap-0.5">
                      <button type="button" disabled={busy} onClick={async () => {
                          const ok = await confirm({
                            title: t('doc_layout.reset', { defaultValue: 'Reset to standard' }),
                            message: t('doc_layout.reset_confirm', { defaultValue: 'Print this document in the standard layout again? Your versions stay in the history.' }),
                            confirmLabel: t('doc_layout.reset', { defaultValue: 'Reset to standard' }),
                            variant: 'warning',
                          });
                          if (ok) await run(() => resetLayout(target), t('doc_layout.reset_done', { defaultValue: 'Standard layout in force' }));
                        }} className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-surface-secondary" aria-label={t('doc_layout.reset', { defaultValue: 'Reset to standard' })} title={t('doc_layout.reset', { defaultValue: 'Reset to standard' })} data-testid="layout-reset">
                        <RotateCcw size={14} />
                      </button>
                      <button type="button" disabled={busy} onClick={onExport} className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-surface-secondary" aria-label={t('doc_layout.export', { defaultValue: 'Export as file' })} title={t('doc_layout.export', { defaultValue: 'Export as file' })}>
                        <Download size={14} />
                      </button>
                      <button type="button" disabled={busy} onClick={() => fileRef.current?.click()} className="inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-surface-secondary" aria-label={t('doc_layout.import', { defaultValue: 'Import from file' })} title={t('doc_layout.import', { defaultValue: 'Import from file' })}>
                        <Upload size={14} />
                      </button>
                      <input ref={fileRef} type="file" accept="application/json,.json" className="hidden" onChange={(e) => e.target.files?.[0] && void onImport(e.target.files[0])} />
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    {!state.is_default && state.published_number !== null && (
                      <button type="button" disabled={busy} onClick={() => run(() => makeLayoutDefault(target))} className="rounded-md border border-border-light px-2 py-0.5 hover:bg-surface-secondary">
                        {t('doc_layout.make_default', { defaultValue: 'Use this variant by default' })}
                      </button>
                    )}
                    {variant !== 'standard' && state.variants.some((v) => v.variant === variant && v.scope === state.scope) && (
                      <button type="button" disabled={busy} onClick={async () => {
                        const ok = await confirm({
                          title: t('doc_layout.delete_variant', { defaultValue: 'Delete this variant' }),
                          message: t('doc_layout.delete_variant_confirm', { defaultValue: 'Delete this variant and its versions? Documents already issued keep their record.' }),
                        });
                        if (ok) await run(async () => { const next = await deleteLayoutVariant(target); setVariant('standard'); return next; });
                      }} className="rounded-md border border-border-light px-2 py-0.5 text-semantic-error hover:bg-surface-secondary">
                        {t('doc_layout.delete_variant', { defaultValue: 'Delete this variant' })}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="relative min-h-[60vh] flex-1 overflow-hidden rounded-lg border border-border-light bg-surface-secondary">
            {narrow && (
              <p className="border-b border-border-light bg-surface-primary px-3 py-2 text-xs text-content-secondary">
                {t('doc_layout.narrow', { defaultValue: 'Open on a wider screen to change the layout.' })}
              </p>
            )}
            {previewing && (
              <span className="absolute right-2 top-2 z-10 inline-flex items-center gap-1 rounded bg-surface-primary/90 px-2 py-0.5 text-2xs text-content-tertiary">
                <Loader2 size={11} className="animate-spin" /> {t('doc_layout.rendering', { defaultValue: 'Updating preview' })}
              </span>
            )}
            {(valuesQuery.data?.issues ?? []).length > 0 && (
              <ul className="absolute inset-x-2 bottom-2 z-10 space-y-0.5 rounded-md border border-semantic-warning/40 bg-surface-primary/95 px-3 py-2 text-xs" aria-live="polite" data-testid="layout-record-issues">
                {(valuesQuery.data?.issues ?? []).slice(0, 4).map((issue, i) => (
                  <li key={`${issue.rule_id}-${i}`} className={issue.severity === 'error' ? 'text-semantic-error' : 'text-content-secondary'}>
                    {t('doc_layout.record_missing', { defaultValue: '{{field}} is missing on this record ({{source}})', field: issue.params.field ?? '', source: issue.params.source ?? '' })}
                  </li>
                ))}
              </ul>
            )}
            {previewError && !previewUrl ? (
              <p className="p-4 text-sm text-content-tertiary">{t('doc_layout.preview_failed', { defaultValue: 'The preview could not be drawn. Check the issues on the left.' })}</p>
            ) : previewUrl ? (
              <iframe title={t('doc_layout.preview', { defaultValue: 'Preview' })} src={previewUrl} className="h-full min-h-[60vh] w-full" data-testid="layout-preview" />
            ) : null}
          </div>
        </div>
      )}
      <ConfirmDialog {...confirmProps} />
    </SideDrawer>
  );
}
