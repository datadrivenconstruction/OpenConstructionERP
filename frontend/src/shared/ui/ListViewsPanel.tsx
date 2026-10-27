// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Saved views for the main table of any list page: pick, save (personal or
 * shared with the team), make default, delete, and show or hide columns.
 * The page key is the route with ids replaced, so one view serves every
 * project. The default view applies when the page's table first appears.
 */
import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bookmark, Star, Trash2, X } from 'lucide-react';
import { listViewsApi, scopeKeyFor, type ListView } from '@/shared/lib/listViewsApi';
import {
  applyTableState,
  columnKeys,
  hiddenColumns,
  primaryTable,
  readTableState,
  setColumnHidden,
} from '@/shared/lib/tableEnhancer';
import { useToastStore } from '@/stores/useToastStore';

export function ListViewsPanel() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const scope = scopeKeyFor(pathname);
  const qc = useQueryClient();
  const [hasTable, setHasTable] = useState(false);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [shared, setShared] = useState(false);
  const [, force] = useState(0);
  const appliedFor = useRef<string | null>(null);

  // A cheap poll: the table mounts after its data loads, on any page.
  useEffect(() => {
    const tick = () => setHasTable(!!primaryTable());
    tick();
    const id = window.setInterval(tick, 1500);
    return () => window.clearInterval(id);
  }, [pathname]);

  const views = useQuery({
    queryKey: ['list-views', scope],
    queryFn: () => listViewsApi.list(scope),
    enabled: hasTable,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!hasTable || !views.data || appliedFor.current === scope) return;
    appliedFor.current = scope;
    const def = views.data.find((v) => v.is_default);
    const table = primaryTable();
    if (def && table) applyTableState(table, def.state);
  }, [hasTable, views.data, scope]);

  const toastError = () =>
    useToastStore.getState().addToast({ type: 'error', title: t('list_views.save_failed', { defaultValue: 'Could not save the layout' }) });

  const save = useMutation({
    mutationFn: () => {
      const table = primaryTable();
      if (!table) throw new Error('no table');
      return listViewsApi.create({ scope_key: scope, name: name.trim(), state: readTableState(table), is_shared: shared });
    },
    onSuccess: (res) => {
      setName('');
      qc.setQueryData<ListView[]>(['list-views', scope], (old) =>
        [...(old ?? []), res.view].sort((a, b) => a.name.localeCompare(b.name)),
      );
      for (const f of res.findings) useToastStore.getState().addToast({ type: 'warning', title: f.message });
    },
    onError: toastError,
  });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Parameters<typeof listViewsApi.update>[1] }) => listViewsApi.update(id, body),
    // Optimistic: a default star moves at once; the server answer confirms it.
    onMutate: ({ id, body }) => {
      const prev = qc.getQueryData<ListView[]>(['list-views', scope]);
      if (body.is_default !== undefined) {
        qc.setQueryData<ListView[]>(['list-views', scope], (old) =>
          (old ?? []).map((v) => ({ ...v, is_default: v.id === id ? !!body.is_default : body.is_default ? false : v.is_default })),
        );
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(['list-views', scope], ctx.prev);
      toastError();
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['list-views', scope] }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => listViewsApi.remove(id),
    onMutate: (id) => {
      const prev = qc.getQueryData<ListView[]>(['list-views', scope]);
      qc.setQueryData<ListView[]>(['list-views', scope], (old) => (old ?? []).filter((v) => v.id !== id));
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(['list-views', scope], ctx.prev);
      toastError();
    },
  });

  if (!hasTable) return null;
  const table = open ? primaryTable() : null;
  const keys = table ? columnKeys(table) : [];
  const hidden = new Set(table ? hiddenColumns(table) : []);

  return (
    <div className="oe-views" data-no-print>
      {open && (
        <div className="oe-views-panel" role="dialog" aria-label={t('list_views.title', { defaultValue: 'Table layouts' })}>
          <div className="flex items-center justify-between border-b border-border-light px-3 py-2">
            <span className="text-sm font-semibold text-content-primary">{t('list_views.title', { defaultValue: 'Table layouts' })}</span>
            <button type="button" onClick={() => setOpen(false)} aria-label={t('common.close', { defaultValue: 'Close' })} className="text-content-tertiary hover:text-content-primary">
              <X size={16} />
            </button>
          </div>
          <ul className="max-h-48 overflow-auto py-1">
            {(views.data ?? []).length === 0 && (
              <li className="px-3 py-2 text-xs text-content-tertiary">
                {t('list_views.empty', { defaultValue: 'No saved layouts for this table yet.' })}
              </li>
            )}
            {(views.data ?? []).map((v) => (
              <li key={v.id} className="flex items-center gap-1 px-2">
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate rounded px-1 py-1.5 text-start text-sm text-content-primary hover:bg-surface-secondary"
                  onClick={() => {
                    const tb = primaryTable();
                    if (tb) applyTableState(tb, v.state);
                    force((n) => n + 1);
                  }}
                >
                  {v.name}
                  {v.is_shared && (
                    <span className="ms-1.5 text-xs text-content-tertiary">
                      {v.is_own
                        ? t('list_views.shared', { defaultValue: 'shared' })
                        : t('list_views.from_team', { defaultValue: 'from team' })}
                    </span>
                  )}
                </button>
                {v.is_own && (
                  <>
                    <button
                      type="button"
                      aria-pressed={v.is_default}
                      title={t('list_views.make_default', { defaultValue: 'Open this layout by default' })}
                      aria-label={t('list_views.make_default', { defaultValue: 'Open this layout by default' })}
                      onClick={() => patch.mutate({ id: v.id, body: { is_default: !v.is_default } })}
                      className={v.is_default ? 'text-oe-blue' : 'text-content-tertiary hover:text-content-primary'}
                    >
                      <Star size={14} fill={v.is_default ? 'currentColor' : 'none'} />
                    </button>
                    <button
                      type="button"
                      title={t('list_views.delete', { defaultValue: 'Delete layout' })}
                      aria-label={t('list_views.delete', { defaultValue: 'Delete layout' })}
                      onClick={() => remove.mutate(v.id)}
                      className="text-content-tertiary hover:text-semantic-error"
                    >
                      <Trash2 size={14} />
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
          <form
            className="flex flex-col gap-2 border-t border-border-light p-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) save.mutate();
            }}
          >
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
              placeholder={t('list_views.name_placeholder', { defaultValue: 'Name of this layout' })}
              aria-label={t('list_views.name_placeholder', { defaultValue: 'Name of this layout' })}
              className="h-8 rounded border border-border bg-surface-primary px-2 text-sm text-content-primary"
            />
            <label className="flex items-center gap-2 text-xs text-content-secondary">
              <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
              {t('list_views.share_team', { defaultValue: 'Share with the team' })}
            </label>
            <button
              type="submit"
              disabled={!name.trim() || save.isPending}
              className="h-8 rounded bg-oe-blue px-3 text-sm font-medium text-white disabled:opacity-50"
            >
              {t('list_views.save', { defaultValue: 'Save current layout' })}
            </button>
          </form>
          {keys.length > 0 && (
            <div className="max-h-40 overflow-auto border-t border-border-light px-3 py-2">
              <p className="mb-1 text-xs font-medium text-content-secondary">{t('list_views.columns', { defaultValue: 'Columns' })}</p>
              {keys.map((k, i) => (
                <label key={`${k}-${i}`} className="flex items-center gap-2 py-0.5 text-xs text-content-primary">
                  <input
                    type="checkbox"
                    checked={!hidden.has(i)}
                    onChange={(e) => {
                      if (table) setColumnHidden(table, i, !e.target.checked);
                      force((n) => n + 1);
                    }}
                  />
                  <span className="truncate">{k}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}
      <button type="button" className="oe-views-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Bookmark size={14} />
        {t('list_views.title', { defaultValue: 'Table layouts' })}
        {(views.data?.length ?? 0) > 0 && <span className="oe-views-count">{views.data?.length}</span>}
      </button>
    </div>
  );
}
