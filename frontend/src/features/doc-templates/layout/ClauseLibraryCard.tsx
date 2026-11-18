// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings card of the clause library: the reusable texts (payment terms,
 * warranty, retention) a layout's clause block prints, one text per language.
 * Clauses a country pack ships are listed read-only with their source; a firm
 * copies one under a key of its own to change it.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Lock, Pencil, Plus, Trash2 } from 'lucide-react';

import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';

import { INPUT } from './BlockEditor';
import { deleteClause, listClauses, saveClause, type Clause, type I18nText } from './layoutApi';
import { clauseKey, clauseText } from './layoutModel';

function languageName(code: string, uiLang: string): string {
  try {
    return new Intl.DisplayNames([uiLang], { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}

interface Draft {
  key: string;
  isNew: boolean;
  category: string;
  title: I18nText;
  text: I18nText;
  lang: string;
}

function errorText(err: unknown): string {
  if (err && typeof err === 'object' && 'detail' in err) {
    const detail = (err as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message);
  }
  return err instanceof Error ? err.message : String(err);
}

export function ClauseLibraryCard() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const { data } = useQuery({ queryKey: ['doc-layout-clauses'], queryFn: listClauses });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const uiLang = (i18n.language || 'en').split('-')[0] ?? 'en';
  const items = useMemo(() => data?.items ?? [], [data]);
  const canEdit = data?.can_edit !== false;
  const languages = data?.languages?.length ? data.languages : ['en'];
  if (!data) return null;

  const begin = (clause: Clause | null, copy = false) => {
    const lang = clause && !clause.text[uiLang] ? (Object.keys(clause.text)[0] ?? uiLang) : uiLang;
    setDraft({
      key: clause && !copy ? clause.key : clause ? clauseKey(`${clause.key}_copy`) : '',
      isNew: !clause || copy,
      category: clause?.category ?? '',
      title: { ...(clause?.title ?? {}) },
      text: { ...(clause?.text ?? {}) },
      lang,
    });
  };

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    try {
      await saveClause(draft.key, { category: draft.category, title: draft.title, text: draft.text });
      await qc.invalidateQueries({ queryKey: ['doc-layout-clauses'] });
      addToast({ type: 'success', title: t('doc_layout.clause_saved', { defaultValue: 'Clause saved' }) });
      setDraft(null);
    } catch (err) {
      addToast({ type: 'error', title: t('doc_layout.failed', { defaultValue: 'That did not work' }), message: errorText(err) });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (clause: Clause) => {
    const ok = await confirm({
      title: t('doc_layout.clause_delete', { defaultValue: 'Delete clause' }),
      message: t('doc_layout.clause_delete_confirm', {
        defaultValue: 'Delete the clause "{{name}}"? Layouts that use it print nothing in its place.',
        name: clauseText(clause.title, uiLang) || clause.key,
      }),
      confirmLabel: t('doc_layout.clause_delete', { defaultValue: 'Delete clause' }),
      variant: 'danger',
    });
    if (!ok) return;
    try {
      await deleteClause(clause.key);
      await qc.invalidateQueries({ queryKey: ['doc-layout-clauses'] });
    } catch (err) {
      addToast({ type: 'error', title: t('doc_layout.failed', { defaultValue: 'That did not work' }), message: errorText(err) });
    }
  };

  const taken = new Set(items.map((c) => c.key));
  const keyClash = !!draft?.isNew && taken.has(draft.key);
  const canSave = !!draft && /^[a-z][a-z0-9_]{0,39}$/.test(draft.key) && !keyClash && Object.values(draft.text).some((v) => v.trim());

  return (
    <section className="mb-6 rounded-xl border border-border-light bg-surface-primary p-4" data-testid="clause-library-card">
      <div className="flex items-start gap-3">
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('doc_layout.clause_library', { defaultValue: 'Clause library' })}
          </h3>
          <p className="mt-0.5 text-xs text-content-secondary">
            {t('doc_layout.clause_library_hint', {
              defaultValue: 'Reusable texts a document layout prints in a clause block, one text per language. Clauses from your country pack are read-only.',
            })}
          </p>
        </div>
        {canEdit && !draft && (
          <button
            type="button"
            onClick={() => begin(null)}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs hover:bg-surface-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
            data-testid="clause-new"
          >
            <Plus size={13} />
            {t('doc_layout.clause_new', { defaultValue: 'New clause' })}
          </button>
        )}
      </div>

      {draft && (
        <div className="mt-3 space-y-2 rounded-lg border border-border-light bg-surface-secondary p-3" data-testid="clause-form">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <label className="text-xs text-content-secondary">
              {t('doc_layout.clause_key', { defaultValue: 'Key' })}
              <input
                className={INPUT}
                value={draft.key}
                disabled={!draft.isNew}
                onChange={(e) => setDraft({ ...draft, key: clauseKey(e.target.value) })}
                data-testid="clause-key"
              />
            </label>
            <label className="text-xs text-content-secondary">
              {t('doc_layout.clause_category', { defaultValue: 'Category' })}
              <input
                className={INPUT}
                value={draft.category}
                maxLength={40}
                onChange={(e) => setDraft({ ...draft, category: e.target.value })}
              />
            </label>
            <label className="text-xs text-content-secondary">
              {t('doc_layout.clause_language', { defaultValue: 'Language' })}
              <select
                className={INPUT}
                value={draft.lang}
                onChange={(e) => setDraft({ ...draft, lang: e.target.value })}
                data-testid="clause-language"
              >
                {Array.from(new Set([...languages, draft.lang])).map((code) => (
                  <option key={code} value={code}>
                    {languageName(code, uiLang)}
                    {draft.text[code]?.trim() ? ' ✓' : ''}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {keyClash && (
            <p className="text-xs text-semantic-error" role="alert">
              {t('doc_layout.clause_key_taken', { defaultValue: 'A clause with this key exists already' })}
            </p>
          )}
          <label className="block text-xs text-content-secondary">
            {t('doc_layout.clause_title', { defaultValue: 'Title' })}
            <input
              className={INPUT}
              value={draft.title[draft.lang] ?? ''}
              maxLength={200}
              onChange={(e) => setDraft({ ...draft, title: { ...draft.title, [draft.lang]: e.target.value } })}
              data-testid="clause-title"
            />
          </label>
          <label className="block text-xs text-content-secondary">
            {t('doc_layout.clause_text', { defaultValue: 'Text' })}
            <textarea
              className={`${INPUT} h-28 py-1.5`}
              value={draft.text[draft.lang] ?? ''}
              maxLength={4000}
              onChange={(e) => setDraft({ ...draft, text: { ...draft.text, [draft.lang]: e.target.value } })}
              data-testid="clause-text"
            />
          </label>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setDraft(null)} className="rounded-md px-3 py-1 text-xs hover:bg-surface-primary">
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            <button
              type="button"
              disabled={!canSave || busy}
              onClick={save}
              className="rounded-md bg-oe-blue px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
              data-testid="clause-save"
            >
              {t('common.save', { defaultValue: 'Save' })}
            </button>
          </div>
        </div>
      )}

      {items.length === 0 && !draft ? (
        <p className="mt-3 text-xs text-content-tertiary">
          {t('doc_layout.clause_none', { defaultValue: 'No clauses yet. A clause written once prints the same in every layout that uses it.' })}
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-border-light">
          {items.map((clause) => (
            <li key={clause.key} className="flex items-start gap-3 py-2" data-testid={`clause-${clause.key}`}>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm text-content-primary">
                  <span className="truncate">{clauseText(clause.title, uiLang) || clause.key}</span>
                  {clause.category && <span className="text-2xs text-content-tertiary">{clause.category}</span>}
                  {clause.locked && (
                    <span
                      className="inline-flex items-center gap-1 rounded bg-surface-secondary px-1.5 py-0.5 text-2xs text-content-secondary"
                      title={clause.source}
                      data-testid={`clause-locked-${clause.key}`}
                    >
                      <Lock size={10} />
                      {t('doc_layout.clause_from_pack', { defaultValue: 'Country pack {{country}}', country: clause.country ?? '' })}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 line-clamp-2 text-xs text-content-secondary">{clauseText(clause.text, uiLang)}</p>
                <p className="mt-0.5 text-2xs text-content-tertiary">
                  {Object.keys(clause.text).filter((k) => clause.text[k]?.trim()).join(' · ')}
                  {clause.locked && clause.source ? ` · ${clause.source}` : ''}
                </p>
              </div>
              {canEdit && (
                <div className="flex shrink-0 items-center gap-1">
                  {clause.locked ? (
                    <button
                      type="button"
                      onClick={() => begin(clause, true)}
                      className="rounded p-1 text-content-secondary hover:bg-surface-secondary"
                      aria-label={t('doc_layout.clause_copy', { defaultValue: 'Copy to edit' })}
                      title={t('doc_layout.clause_copy', { defaultValue: 'Copy to edit' })}
                    >
                      <Copy size={14} />
                    </button>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => begin(clause)}
                        className="rounded p-1 text-content-secondary hover:bg-surface-secondary"
                        aria-label={t('common.edit', { defaultValue: 'Edit' })}
                        data-testid={`clause-edit-${clause.key}`}
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => remove(clause)}
                        className="rounded p-1 text-content-secondary hover:bg-surface-secondary hover:text-semantic-error"
                        aria-label={t('doc_layout.clause_delete', { defaultValue: 'Delete clause' })}
                      >
                        <Trash2 size={14} />
                      </button>
                    </>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog {...confirmProps} />
    </section>
  );
}
