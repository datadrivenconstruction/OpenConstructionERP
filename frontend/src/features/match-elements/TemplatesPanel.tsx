// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Tenant-scoped match-template library (cross-project memory).

import { useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { X, Trash2, Loader2, Library, Sparkles } from 'lucide-react';
import { matchElementsApi } from './api';
import { getIntlLocale } from '@/shared/lib/formatters';

interface Props {
  onClose: () => void;
  /** Signatures of the groups in the active match session. Templates whose
   *  signature is in this set are "hits" - saved mappings this session is
   *  reusing right now. They get a badge and float to the top. Optional, so
   *  the panel still works when opened without a session in context. */
  activeSignatures?: readonly string[];
}

export function TemplatesPanel({ onClose, activeSignatures }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const listQ = useQuery({
    queryKey: ['match-templates'],
    queryFn: matchElementsApi.listTemplates,
  });

  // Which saved templates does the current session actually reuse? A hit =
  // a template whose signature matches a group in this session. We surface
  // those first, and count them in the header, so the cross-project memory
  // is visible instead of buried in a long list.
  const activeSet = useMemo(
    () => new Set((activeSignatures ?? []).filter(Boolean)),
    [activeSignatures],
  );
  const templates = useMemo(() => {
    const rows = listQ.data ?? [];
    if (activeSet.size === 0) return rows;
    // Stable partition: hits first (each list is already use_count-ordered).
    const hits = rows.filter((r) => activeSet.has(r.signature));
    const rest = rows.filter((r) => !activeSet.has(r.signature));
    return [...hits, ...rest];
  }, [listQ.data, activeSet]);
  const hitCount = useMemo(
    () => (listQ.data ?? []).filter((r) => activeSet.has(r.signature)).length,
    [listQ.data, activeSet],
  );

  const deleteMut = useMutation({
    mutationFn: (id: string) => matchElementsApi.deleteTemplate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['match-templates'] }),
  });

  // Escape closes the slide-over.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} aria-hidden />
      <aside
        className="fixed top-0 right-0 bottom-0 w-full sm:w-[560px] bg-white dark:bg-slate-900 z-50 shadow-2xl flex flex-col border-l border-slate-200 dark:border-slate-700"
        role="dialog"
        aria-modal="true"
        aria-labelledby="templates-panel-heading"
      >
        <header className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Library className="w-5 h-5 text-indigo-500" />
            <h2 id="templates-panel-heading" className="text-base font-semibold">
              {t('match_elements.templates.title', 'Template library')}
            </h2>
            <span className="text-xs text-slate-500">
              {listQ.data ? t('match_elements.templates.count', '{{count}} signatures', { count: listQ.data.length }) : ''}
            </span>
            {hitCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-medium text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200">
                <Sparkles className="h-3 w-3" />
                {t('match_elements.templates.hit_count', {
                  defaultValue: '{{count}} in this session',
                  count: hitCount,
                })}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('match_elements.templates.close', 'Close template library')}
            className="p-1.5 rounded hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
        </header>

        <div className="flex-1 overflow-auto p-4">
          {listQ.isLoading && (
            <div className="text-center text-slate-500 py-8">
              <Loader2 className="w-5 h-5 animate-spin inline mr-2" />
              {t('match_elements.templates.loading', 'Loading library…')}
            </div>
          )}
          {listQ.data && listQ.data.length === 0 && (
            <div className="text-center text-slate-500 py-12 text-sm">
              <p>{t('match_elements.templates.empty', 'No saved templates yet.')}</p>
              <p className="text-xs mt-2 opacity-70">
                {t('match_elements.templates.empty_hint', 'Confirmed matches with "Save to library" enabled appear here and propagate to future projects.')}
              </p>
            </div>
          )}
          {templates.map((tpl) => {
            const isHit = activeSet.has(tpl.signature);
            return (
            <div
              key={tpl.id}
              className={
                isHit
                  ? 'mb-3 p-3 rounded border border-indigo-300 dark:border-indigo-600 bg-indigo-50/50 dark:bg-indigo-900/10 transition'
                  : 'mb-3 p-3 rounded border border-slate-200 dark:border-slate-700 hover:border-indigo-300 dark:hover:border-indigo-600 transition'
              }
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <div className="text-sm font-medium truncate">
                      {tpl.label ?? <span className="text-slate-400 italic">{t('match_elements.templates.unnamed', '(unnamed)')}</span>}
                    </div>
                    {isHit && (
                      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-200">
                        <Sparkles className="h-2.5 w-2.5" />
                        {t('match_elements.templates.hit_badge', {
                          defaultValue: 'Matched here',
                        })}
                      </span>
                    )}
                  </div>
                  <div className="font-mono text-xs text-slate-500 truncate mt-0.5">
                    {t('match_elements.templates.sig', 'sig: {{prefix}}…', { prefix: tpl.signature.slice(0, 16) })}
                  </div>
                  <div className="text-xs text-slate-600 dark:text-slate-300 mt-1">
                    {t('match_elements.templates.used', 'Used')} <strong className="tabular-nums">{tpl.use_count}</strong>×
                    {tpl.last_used_at && (
                      <> · {t('match_elements.templates.last', 'last {{date}}', { date: new Date(tpl.last_used_at).toLocaleDateString(getIntlLocale()) })}</>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {tpl.source_fields.map((f) => (
                      <span
                        key={f}
                        className="px-1.5 py-0.5 text-[10px] rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-mono"
                      >
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
                <button
                  onClick={() => {
                    if (confirm(t('match_elements.templates.remove_confirm', 'Remove this template from the library?'))) deleteMut.mutate(tpl.id);
                  }}
                  disabled={deleteMut.isPending}
                  className="p-1.5 rounded text-slate-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-900/20 disabled:opacity-50"
                  title={t('match_elements.templates.remove_title', 'Remove from library')}
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
            );
          })}
        </div>

        <footer className="px-4 py-3 border-t border-slate-200 dark:border-slate-700 text-xs text-slate-500">
          {t('match_elements.templates.footer', 'Templates are tenant-scoped. Confirmed signatures auto-suggest matches in future projects.')}
        </footer>
      </aside>
    </>
  );
}
