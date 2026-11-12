// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Settings > Letter templates: the wording of the letters the platform sends
 * (award letter, rejection notice, invitation to tender), per language.
 *
 * Left: the letters grouped by module, a mark on the ones the company changed.
 * Right: language, the editor with field chips, and a live preview rendered by
 * the server with sample values. Managers and admins save and reset; everyone
 * else reads. A letter is written in the project's language when it is issued,
 * so the language here is the letter's, not the interface's.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Lock, RotateCcw, Save } from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonText } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchLetterPreview,
  getLetterTemplate,
  listLetterTemplates,
  resetLetterTemplate,
  saveLetterTemplate,
  type LetterTemplateSummary,
} from './api';
import { LetterTextEditor, hasBlockingIssue } from './LetterTextEditor';
import { sameText, type LetterText } from './letterRules';

const LANGUAGE_NAMES: Record<string, string> = {};

function languageName(code: string, uiLanguage: string): string {
  const cacheKey = `${uiLanguage}:${code}`;
  if (!LANGUAGE_NAMES[cacheKey]) {
    try {
      LANGUAGE_NAMES[cacheKey] = new Intl.DisplayNames([uiLanguage], { type: 'language' }).of(code) ?? code;
    } catch {
      LANGUAGE_NAMES[cacheKey] = code;
    }
  }
  return LANGUAGE_NAMES[cacheKey] ?? code;
}

export function useLetterTitle(): (key: string) => string {
  const { t } = useTranslation();
  const titles: Record<string, string> = {
    'tendering.award_letter': t('letter_templates.tpl_award_letter', { defaultValue: 'Award letter' }),
    'tendering.rejection_letter': t('letter_templates.tpl_rejection_letter', { defaultValue: 'Rejection notice' }),
    'tendering.invitation_email': t('letter_templates.tpl_invitation_email', { defaultValue: 'Invitation to tender (email)' }),
  };
  return (key: string) => titles[key] ?? key;
}

function useModuleTitle(): (module: string) => string {
  const { t } = useTranslation();
  return (module: string) =>
    module === 'tendering' ? t('letter_templates.module_tendering', { defaultValue: 'Tendering' }) : module;
}

export function LetterTemplatesSettings() {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  const canEdit = userRole === 'admin' || userRole === 'manager';
  const letterTitle = useLetterTitle();
  const moduleTitle = useModuleTitle();

  const list = useQuery({ queryKey: ['letter-templates'], queryFn: listLetterTemplates });
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const selected: LetterTemplateSummary | undefined =
    list.data?.find((x) => x.key === selectedKey) ?? list.data?.[0];
  const uiPrimary = (i18n.language || 'en').split('-')[0] ?? 'en';
  const [language, setLanguage] = useState<string | null>(null);
  const lang = selected
    ? language && selected.languages.includes(language)
      ? language
      : selected.languages.includes(uiPrimary)
        ? uiPrimary
        : 'en'
    : 'en';

  const resolved = useQuery({
    queryKey: ['letter-templates', selected?.key, lang],
    queryFn: () => getLetterTemplate(selected!.key, { language: lang }),
    enabled: !!selected,
  });

  const [draft, setDraft] = useState<LetterText | null>(null);
  useEffect(() => {
    if (resolved.data) setDraft(resolved.data.text);
  }, [resolved.data]);

  // Live preview, debounced, from the unsaved draft.
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!selected || !draft) return undefined;
    let cancelled = false;
    let url: string | null = null;
    const timer = window.setTimeout(async () => {
      try {
        const blob = await fetchLetterPreview(selected.key, lang, draft);
        if (cancelled || !blob) return;
        url = URL.createObjectURL(blob);
        setPreviewUrl(url);
      } catch {
        // Preview is a convenience; the editor stays usable without it.
      }
    }, 700);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      if (url) URL.revokeObjectURL(url);
    };
  }, [selected, lang, draft]);

  const save = useMutation({
    mutationFn: () => saveLetterTemplate(selected!.key, { ...draft!, language: lang }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['letter-templates'] });
      addToast({ type: 'success', title: t('letter_templates.saved', { defaultValue: 'Letter template saved' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const reset = useMutation({
    mutationFn: () => resetLetterTemplate(selected!.key, lang),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['letter-templates'] }),
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const groups = useMemo(() => {
    const out = new Map<string, LetterTemplateSummary[]>();
    for (const item of list.data ?? []) out.set(item.module, [...(out.get(item.module) ?? []), item]);
    return [...out.entries()];
  }, [list.data]);

  if (list.isLoading) {
    return (
      <Card padding="md">
        <SkeletonText lines={6} />
      </Card>
    );
  }
  if (list.isError || !list.data?.length) {
    return (
      <EmptyState
        title={t('letter_templates.load_failed', { defaultValue: 'No letter templates are available.' })}
      />
    );
  }

  const placeholders = resolved.data?.placeholders ?? [];
  const customised = selected?.customised_languages.includes(lang) ?? false;
  const dirty = !!draft && !!resolved.data && !sameText(draft, resolved.data.text);
  const blocked = !draft || hasBlockingIssue(draft, placeholders);

  return (
    <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]" data-testid="letter-templates-settings">
      <Card padding="sm">
        <nav className="space-y-3">
          {groups.map(([module, items]) => (
            <div key={module}>
              <div className="oe-overline mb-1">{moduleTitle(module)}</div>
              <ul className="space-y-0.5">
                {items.map((item) => (
                  <li key={item.key}>
                    <button
                      type="button"
                      onClick={() => setSelectedKey(item.key)}
                      aria-current={item.key === selected?.key ? 'true' : undefined}
                      className={clsx(
                        'flex w-full items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-sm',
                        item.key === selected?.key
                          ? 'bg-surface-secondary text-content-primary font-medium'
                          : 'text-content-secondary hover:bg-surface-secondary',
                      )}
                    >
                      <span className="truncate">{letterTitle(item.key)}</span>
                      {item.customised_languages.length > 0 && <Badge size="sm" variant="blue">{item.customised_languages.length}</Badge>}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card padding="md">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h3 className="oe-card-title mr-auto">{selected ? letterTitle(selected.key) : ''}</h3>
            {customised ? (
              <Badge variant="blue">{t('letter_templates.customised', { defaultValue: 'Customised' })}</Badge>
            ) : (
              <Badge>{t('letter_templates.default_text', { defaultValue: 'Default text' })}</Badge>
            )}
            <label className="flex items-center gap-1.5 text-xs text-content-secondary">
              {t('letter_templates.language', { defaultValue: 'Letter language' })}
              <select
                className="oe-select w-auto"
                value={lang}
                onChange={(e) => setLanguage(e.target.value)}
                data-testid="letter-language"
              >
                {(selected?.languages ?? []).map((code) => (
                  <option key={code} value={code}>
                    {languageName(code, i18n.language || 'en')}
                    {selected?.customised_languages.includes(code) ? ' *' : ''}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {!canEdit && (
            <p className="mb-3 flex items-center gap-1.5 text-xs text-content-tertiary">
              <Lock size={14} />
              {t('letter_templates.read_only', { defaultValue: 'Only managers and admins can change letter templates.' })}
            </p>
          )}
          {resolved.isLoading || !draft ? (
            <SkeletonText lines={8} />
          ) : (
            <LetterTextEditor value={draft} onChange={setDraft} placeholders={placeholders} readOnly={!canEdit} />
          )}
          {canEdit && (
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button
                variant="secondary"
                icon={<RotateCcw size={16} />}
                disabled={!customised || reset.isPending}
                onClick={() => reset.mutate()}
              >
                {t('letter_templates.reset', { defaultValue: 'Reset to default' })}
              </Button>
              <Button
                variant="primary"
                icon={<Save size={16} />}
                disabled={!dirty || blocked || save.isPending}
                loading={save.isPending}
                onClick={() => save.mutate()}
              >
                {t('letter_templates.save', { defaultValue: 'Save template' })}
              </Button>
            </div>
          )}
        </Card>

        <Card padding="sm">
          <div className="oe-overline mb-2">{t('letter_templates.preview', { defaultValue: 'Preview with sample values' })}</div>
          {previewUrl ? (
            <iframe
              title={t('letter_templates.preview', { defaultValue: 'Preview with sample values' })}
              src={previewUrl}
              className="h-[640px] w-full rounded-lg border border-border bg-surface-primary"
              // The email preview is HTML from the server: no scripts. A PDF needs the viewer.
              sandbox={selected?.kind === 'email' ? '' : undefined}
              data-testid="letter-preview"
            />
          ) : (
            <SkeletonText lines={10} />
          )}
        </Card>
      </div>
    </div>
  );
}
