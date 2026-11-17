// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Editor drawer for one document kind in one language: text blocks with a
 * field picker, locked legal blocks from the country pack, a server preview
 * that follows the draft, and save / publish / versions / reset.
 *
 * The text is the firm's words only; amounts and line items always come from
 * the record. The preview is drawn by the server with the same generator the
 * document uses, against sample values or a record the user can open.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Lock, Plus, Send } from 'lucide-react';
import {
  Badge,
  Button,
  ConfirmDialog,
  DateDisplay,
  ErrorState,
  SideDrawer,
  SkeletonText,
  WideModal,
} from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  discardDraft,
  fetchPreview,
  getEditor,
  listRecords,
  publishTemplate,
  resetTemplate,
  restoreVersion,
  saveDraft,
  sendTest,
  type DocIssue,
  type EditorState,
  type EmailPreview,
  type MergeFieldInfo,
  type TemplateOptions,
} from './api';
import {
  DOCUMENT_LANGUAGES,
  RTL_LANGUAGES,
  hasBlockingIssue,
  insertField,
  opensPicker,
  sameBlocks,
  unknownFields,
} from './docTemplateText';
import { languageLabel, useBlockLabel, useFieldGroupLabel, useKindLabel } from './labels';

interface Props {
  kindKey: string;
  initialLocale: string;
  canEdit: boolean;
  emailEnabled: boolean;
  onClose: () => void;
}

const MAX_SIGNATURE_BYTES = 300 * 1024;

export function DocTemplateEditor({ kindKey, initialLocale, canEdit, emailEnabled, onClose }: Props) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const kindLabel = useKindLabel();
  const blockLabel = useBlockLabel();
  const uiLang = (i18n.language || 'en').split('-')[0] ?? 'en';
  const [locale, setLocale] = useState(initialLocale);
  const state = useQuery({ queryKey: ['doc-templates', 'editor', kindKey, locale], queryFn: () => getEditor(kindKey, locale) });
  const [text, setText] = useState<Record<string, string>>({});
  const [options, setOptions] = useState<TemplateOptions>({ font: 'sans', signature_image: '' });
  const [baseline, setBaseline] = useState<Record<string, string>>({});
  const [confirmLeave, setConfirmLeave] = useState<null | (() => void)>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const blockRefs = useRef<Record<string, HTMLTextAreaElement | null>>({});

  useEffect(() => {
    if (!state.data) return;
    setText(state.data.text);
    setBaseline(state.data.text);
    setOptions(state.data.options);
  }, [state.data]);

  const dirty = !sameBlocks(text, baseline) || (state.data ? options.font !== state.data.options.font || options.signature_image !== state.data.options.signature_image : false);
  const known = useMemo(() => new Set((state.data?.fields ?? []).map((f) => f.path)), [state.data]);
  const localIssues: DocIssue[] = useMemo(() => {
    const out: DocIssue[] = [];
    for (const [block, value] of Object.entries(text)) {
      for (const field of unknownFields(value, known)) {
        out.push({ rule_id: 'doctpl.unknown_merge_field', severity: 'error', block, params: { field } });
      }
    }
    if (state.data?.channel === 'email' && !(text.subject ?? '').trim() && state.data.blocks.includes('subject')) {
      out.push({ rule_id: 'doctpl.email_subject_empty', severity: 'error', block: 'subject', params: {} });
    }
    return out;
  }, [text, known, state.data]);
  const serverIssues = (state.data?.issues ?? []).filter(
    (i) => !['doctpl.unknown_merge_field', 'doctpl.email_subject_empty'].includes(i.rule_id) || !dirty,
  );
  const issues = dirty ? [...localIssues, ...serverIssues.filter((i) => i.severity !== 'error')] : serverIssues;

  const refresh = (next: EditorState) => {
    qc.setQueryData(['doc-templates', 'editor', kindKey, locale], next);
    qc.invalidateQueries({ queryKey: ['doc-templates', 'list'] });
  };
  const onError = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });
  const saveM = useMutation({
    mutationFn: () => saveDraft(kindKey, locale, text, options),
    onSuccess: (next) => {
      refresh(next);
      addToast({ type: 'success', title: t('settings.document_templates.draft_saved', { defaultValue: 'Draft saved' }) });
    },
    onError,
  });
  const publishM = useMutation({
    mutationFn: async () => {
      await saveDraft(kindKey, locale, text, options);
      return publishTemplate(kindKey, locale);
    },
    onSuccess: (next) => {
      refresh(next);
      addToast({ type: 'success', title: t('settings.document_templates.published', { defaultValue: 'Published' }) });
    },
    onError,
  });
  const discardM = useMutation({
    mutationFn: () => discardDraft(kindKey, locale),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['doc-templates'] }),
    onError,
  });
  const restoreM = useMutation({
    mutationFn: (id: string) => restoreVersion(kindKey, locale, id),
    onSuccess: (next) => {
      refresh(next);
      setVersionsOpen(false);
    },
    onError,
  });
  const resetM = useMutation({
    mutationFn: () => resetTemplate(kindKey, locale),
    onSuccess: (next) => {
      refresh(next);
      setConfirmReset(false);
    },
    onError,
  });
  const testM = useMutation({
    mutationFn: () => sendTest(kindKey, locale, text),
    onSuccess: (r) =>
      addToast(
        r.sent
          ? { type: 'success', title: t('settings.document_templates.test_sent', { defaultValue: 'Test sent to {{to}}', to: r.to }) }
          : { type: 'error', title: r.detail || t('settings.document_templates.test_failed', { defaultValue: 'Test email was not sent' }) },
      ),
    onError,
  });

  const guard = (action: () => void) => (dirty ? setConfirmLeave(() => action) : action());
  const busy = saveM.isPending || publishM.isPending || resetM.isPending || restoreM.isPending;
  const rtl = RTL_LANGUAGES.has(locale);
  const blocking = hasBlockingIssue(localIssues);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      if (canEdit && dirty) saveM.mutate();
    }
  };

  const title = state.data
    ? `${kindLabel(state.data.key, state.data.label)} - ${languageLabel(locale, uiLang)}`
    : kindLabel(kindKey, kindKey);

  return (
    <SideDrawer
      open
      onClose={() => guard(onClose)}
      title={title}
      widthClass="w-full md:max-w-[1200px]"
      busy={busy}
      headerActions={
        <select
          className="oe-input py-0"
          value={locale}
          aria-label={t('settings.document_templates.language', { defaultValue: 'Language' })}
          onChange={(e) => {
            const next = e.target.value;
            guard(() => setLocale(next));
          }}
        >
          {DOCUMENT_LANGUAGES.map((code) => (
            <option key={code} value={code}>
              {languageLabel(code, uiLang)}
            </option>
          ))}
        </select>
      }
    >
      <div onKeyDown={onKeyDown} data-testid="doc-template-editor">
        {state.isLoading && <SkeletonText lines={8} />}
        {state.isError && (
          <ErrorState
            title={t('settings.document_templates.load_failed', { defaultValue: 'Could not load document templates' })}
            onRetry={() => state.refetch()}
          />
        )}
        {state.data && (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-end gap-2">
              {state.data.has_draft && (
                <Button variant="ghost" size="sm" disabled={!canEdit || busy} onClick={() => discardM.mutate()}>
                  {t('settings.document_templates.discard', { defaultValue: 'Discard' })}
                </Button>
              )}
              {state.data.channel === 'email' && (
                <span title={emailEnabled ? undefined : t('settings.document_templates.email_off', { defaultValue: 'Email delivery is off on this server' })}>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<Send size={14} />}
                    disabled={!canEdit || !emailEnabled || testM.isPending || blocking}
                    onClick={() => testM.mutate()}
                  >
                    {t('settings.document_templates.send_test', { defaultValue: 'Send test to me' })}
                  </Button>
                </span>
              )}
              <Button variant="secondary" size="sm" disabled={!canEdit || !dirty || busy} onClick={() => saveM.mutate()}>
                {t('settings.document_templates.save_draft', { defaultValue: 'Save draft' })}
              </Button>
              <Button
                variant="primary"
                size="sm"
                disabled={!canEdit || busy || blocking || (!dirty && !state.data.has_draft)}
                onClick={() => publishM.mutate()}
                data-testid="doc-template-publish"
              >
                {t('settings.document_templates.publish', { defaultValue: 'Publish' })}
              </Button>
            </div>

            {!state.data.has_translation && !state.data.has_draft && (
              <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/50 px-3 py-2 text-xs text-content-secondary">
                <span>
                  {state.data.primary_locale && state.data.primary_locale !== locale
                    ? t('settings.document_templates.no_translation', {
                        defaultValue: 'No translation: documents in this language print your {{language}} text.',
                        language: languageLabel(state.data.primary_locale, uiLang),
                      })
                    : t('settings.document_templates.uses_default', { defaultValue: 'Uses default text' })}
                </span>
                {canEdit && (
                  <button
                    type="button"
                    className="font-medium text-oe-blue hover:underline"
                    onClick={() => setText({ ...state.data.default_text })}
                  >
                    {t('settings.document_templates.start_from_default', { defaultValue: 'Start from default' })}
                  </button>
                )}
              </div>
            )}

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                {state.data.blocks.map((block) => (
                  <BlockField
                    key={block}
                    id={`dt-block-${block}`}
                    label={blockLabel(block)}
                    value={text[block] ?? ''}
                    fields={state.data.fields}
                    readOnly={!canEdit}
                    dir={rtl ? 'rtl' : 'ltr'}
                    lang={locale}
                    hasError={issues.some((i) => i.block === block && i.severity === 'error')}
                    onChange={(v) => setText((prev) => ({ ...prev, [block]: v }))}
                    registerRef={(el) => {
                      blockRefs.current[block] = el;
                    }}
                  />
                ))}
                {state.data.legal_blocks.map((lb) => (
                  <div
                    key={lb.id}
                    className="rounded-lg border border-border-light bg-surface-secondary/60 px-3 py-2 text-sm"
                    aria-readonly="true"
                    aria-describedby={`dt-legal-${lb.id}`}
                    data-testid={`doc-template-legal-${lb.id}`}
                  >
                    <div className="flex items-center gap-1.5 font-medium text-content-primary">
                      <Lock size={13} /> {lb.text}
                    </div>
                    <p id={`dt-legal-${lb.id}`} className="mt-0.5 text-xs text-content-secondary">
                      {t('settings.document_templates.legal_locked', {
                        defaultValue: 'Required by {{source}}. This text cannot be removed.',
                        source: lb.source,
                      })}
                    </p>
                  </div>
                ))}
                {state.data.channel === 'pdf' && (
                  <MoreOptions options={options} setOptions={setOptions} readOnly={!canEdit} />
                )}
              </div>
              <PreviewPane
                state={state.data}
                locale={locale}
                text={text}
                options={options}
                issues={issues}
                onFocusBlock={(b) => blockRefs.current[b]?.focus()}
              />
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border-light pt-3 text-xs text-content-secondary">
              <span>{t('settings.document_templates.versions', { defaultValue: 'Versions' })}:</span>
              {state.data.versions.slice(0, 3).map((v) => (
                <span key={v.id}>
                  v{v.number}
                  {v.is_published && ` ${t('settings.document_templates.published_short', { defaultValue: 'published' })}`}{' '}
                  <DateDisplay value={v.created_at} format="numeric" /> {v.author_name}
                </span>
              ))}
              {state.data.versions.length > 0 && (
                <button type="button" className="font-medium text-oe-blue hover:underline" onClick={() => setVersionsOpen(true)}>
                  {t('settings.document_templates.restore', { defaultValue: 'Restore' })}
                </button>
              )}
              {canEdit && state.data.published_text && (
                <button type="button" className="font-medium text-oe-blue hover:underline" onClick={() => setConfirmReset(true)}>
                  {t('settings.document_templates.reset_default', { defaultValue: 'Reset to default' })}
                </button>
              )}
            </div>

            <WideModal
              open={versionsOpen}
              onClose={() => setVersionsOpen(false)}
              title={t('settings.document_templates.versions', { defaultValue: 'Versions' })}
              size="md"
            >
              <table className="w-full text-sm">
                <tbody>
                  {state.data.versions.map((v) => (
                    <tr key={v.id} className="border-b border-border-light last:border-0">
                      <td className="py-1.5">v{v.number}</td>
                      <td className="py-1.5">
                        <DateDisplay value={v.created_at} format="datetime" />
                      </td>
                      <td className="py-1.5">{v.author_name}</td>
                      <td className="py-1.5 text-content-secondary">{v.note}</td>
                      <td className="py-1.5 text-end">
                        {v.is_published ? (
                          <Badge variant="blue" size="sm">
                            {t('settings.document_templates.published_short', { defaultValue: 'published' })}
                          </Badge>
                        ) : (
                          <Button size="sm" variant="secondary" disabled={!canEdit || busy} onClick={() => restoreM.mutate(v.id)}>
                            {t('settings.document_templates.restore', { defaultValue: 'Restore' })}
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </WideModal>
          </>
        )}
      </div>
      <ConfirmDialog
        open={confirmReset}
        title={t('settings.document_templates.reset_default', { defaultValue: 'Reset to default' })}
        message={t('settings.document_templates.reset_confirm', {
          defaultValue: 'Documents in this language print the built-in text again. Earlier versions stay in the history.',
        })}
        variant="warning"
        loading={resetM.isPending}
        onConfirm={() => resetM.mutate()}
        onCancel={() => setConfirmReset(false)}
      />
      <ConfirmDialog
        open={confirmLeave !== null}
        title={t('settings.document_templates.unsaved_title', { defaultValue: 'Unsaved changes' })}
        message={t('settings.document_templates.unsaved_message', { defaultValue: 'Leave without saving your text?' })}
        variant="warning"
        onConfirm={() => {
          const next = confirmLeave;
          setConfirmLeave(null);
          setBaseline(text);
          next?.();
        }}
        onCancel={() => setConfirmLeave(null)}
      />
    </SideDrawer>
  );
}

function BlockField({
  id,
  label,
  value,
  fields,
  readOnly,
  dir,
  lang,
  hasError,
  onChange,
  registerRef,
}: {
  id: string;
  label: string;
  value: string;
  fields: MergeFieldInfo[];
  readOnly: boolean;
  dir: 'rtl' | 'ltr';
  lang: string;
  hasError: boolean;
  onChange: (v: string) => void;
  registerRef: (el: HTMLTextAreaElement | null) => void;
}) {
  const { t } = useTranslation();
  const groupLabel = useFieldGroupLabel();
  const [picker, setPicker] = useState(false);
  const [active, setActive] = useState(0);
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const caret = useRef(0);

  const choose = (path: string) => {
    const r = insertField(value, caret.current, path);
    onChange(r.text);
    setPicker(false);
    requestAnimationFrame(() => {
      ref.current?.focus();
      ref.current?.setSelectionRange(r.caret, r.caret);
    });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.ctrlKey && e.key === ' ') {
      e.preventDefault();
      caret.current = e.currentTarget.selectionStart;
      setPicker(true);
      return;
    }
    if (!picker) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      setPicker(false);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, fields.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const f = fields[active];
      if (f) choose(f.path);
    }
  };

  const listId = `${id}-fields`;
  return (
    <div className="relative">
      <label htmlFor={id} className="oe-label mb-1 block">
        {label}
      </label>
      <textarea
        id={id}
        ref={(el) => {
          ref.current = el;
          registerRef(el);
        }}
        className={`oe-input min-h-[64px] w-full font-normal ${hasError ? 'border-semantic-error' : ''}`}
        rows={Math.min(10, Math.max(2, value.split('\n').length + 1))}
        value={value}
        dir={dir}
        lang={lang}
        readOnly={readOnly}
        role={picker ? 'combobox' : undefined}
        aria-expanded={picker || undefined}
        aria-controls={picker ? listId : undefined}
        aria-activedescendant={picker ? `${listId}-${active}` : undefined}
        aria-invalid={hasError || undefined}
        onChange={(e) => {
          onChange(e.target.value);
          caret.current = e.target.selectionStart;
          if (opensPicker(e.target.value, e.target.selectionStart)) {
            setActive(0);
            setPicker(true);
          }
        }}
        onKeyDown={onKeyDown}
        onBlur={() => setTimeout(() => setPicker(false), 150)}
      />
      {!readOnly && (
        <button
          type="button"
          className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
          onClick={() => {
            caret.current = ref.current?.selectionStart ?? value.length;
            setActive(0);
            setPicker((p) => !p);
          }}
        >
          <Plus size={12} /> {t('settings.document_templates.insert_field', { defaultValue: 'Insert field' })}
        </button>
      )}
      {picker && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-lg border border-border-light bg-surface-primary py-1 shadow-lg"
        >
          {fields.map((f, i) => (
            <li
              key={f.path}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(f.path);
              }}
              className={`flex cursor-pointer items-baseline justify-between gap-3 px-3 py-1 text-sm ${i === active ? 'bg-surface-secondary' : ''}`}
            >
              <span>
                <span className="text-xs text-content-tertiary">{groupLabel(f.group)} </span>
                <bdi className="font-mono text-xs">{`{{${f.path}}}`}</bdi>
              </span>
              <bdi className="truncate text-xs text-content-secondary">{f.sample}</bdi>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MoreOptions({
  options,
  setOptions,
  readOnly,
}: {
  options: TemplateOptions;
  setOptions: (o: TemplateOptions) => void;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  const [error, setError] = useState('');
  const onFile = (file: File | undefined) => {
    setError('');
    if (!file) return;
    if (!['image/png', 'image/jpeg'].includes(file.type) || file.size > MAX_SIGNATURE_BYTES) {
      setError(t('settings.document_templates.signature_invalid', { defaultValue: 'Use a PNG or JPEG image under 300 KB.' }));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setOptions({ ...options, signature_image: String(reader.result || '') });
    reader.readAsDataURL(file);
  };
  return (
    <details className="rounded-lg border border-border-light px-3 py-2 text-sm">
      <summary className="cursor-pointer text-content-secondary">
        {t('settings.document_templates.more_options', { defaultValue: 'More options' })}
      </summary>
      <div className="mt-2 space-y-3">
        <label className="flex items-center gap-2">
          <span className="oe-label">{t('settings.document_templates.font', { defaultValue: 'Typeface' })}</span>
          <select
            className="oe-input py-0"
            value={options.font}
            disabled={readOnly}
            onChange={(e) => setOptions({ ...options, font: e.target.value === 'serif' ? 'serif' : 'sans' })}
          >
            <option value="sans">{t('settings.document_templates.font_sans', { defaultValue: 'Sans serif' })}</option>
            <option value="serif">{t('settings.document_templates.font_serif', { defaultValue: 'Serif (Noto Serif)' })}</option>
          </select>
        </label>
        <div>
          <span className="oe-label block">{t('settings.document_templates.signature_image', { defaultValue: 'Signature image' })}</span>
          <p className="text-xs text-content-secondary">
            {t('settings.document_templates.signature_note', {
              defaultValue: 'Printed as a picture and labelled as such. It is not an electronic signature.',
            })}
          </p>
          {options.signature_image && (
            <img src={options.signature_image} alt="" className="mt-1 h-10 rounded border border-border-light bg-white" />
          )}
          {!readOnly && (
            <div className="mt-1 flex items-center gap-3">
              <input type="file" accept="image/png,image/jpeg" onChange={(e) => onFile(e.target.files?.[0])} className="text-xs" />
              {options.signature_image && (
                <button type="button" className="text-xs text-oe-blue hover:underline" onClick={() => setOptions({ ...options, signature_image: '' })}>
                  {t('settings.document_templates.remove', { defaultValue: 'Remove' })}
                </button>
              )}
            </div>
          )}
          {error && <p className="mt-1 text-xs text-semantic-error">{error}</p>}
        </div>
      </div>
    </details>
  );
}

function PreviewPane({
  state,
  locale,
  text,
  options,
  issues,
  onFocusBlock,
}: {
  state: EditorState;
  locale: string;
  text: Record<string, string>;
  options: TemplateOptions;
  issues: DocIssue[];
  onFocusBlock: (block: string) => void;
}) {
  const { t } = useTranslation();
  const [recordId, setRecordId] = useState<string>('');
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [email, setEmail] = useState<EmailPreview | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const records = useQuery({
    queryKey: ['doc-templates', 'records', state.key],
    queryFn: () => listRecords(state.key),
    enabled: state.has_records,
  });

  const run = useCallback(
    async (signal: AbortSignal) => {
      setLoading(true);
      setFailed(false);
      try {
        const r = await fetchPreview(state.key, locale, text, options, recordId || null, signal);
        if ('pdf' in r) {
          setEmail(null);
          setPdfUrl((old) => {
            if (old) URL.revokeObjectURL(old);
            return URL.createObjectURL(r.pdf);
          });
        } else {
          setEmail(r.email);
        }
      } catch (e) {
        if (!signal.aborted) setFailed(true);
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    },
    [state.key, locale, text, options, recordId],
  );

  useEffect(() => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => void run(ctrl.signal), 600);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [run]);

  useEffect(() => () => {
    if (pdfUrl) URL.revokeObjectURL(pdfUrl);
  }, [pdfUrl]);

  const issueText = (i: DocIssue) =>
    t(`validation.${i.rule_id}`, { defaultValue: i.rule_id, ...i.params });

  return (
    <div className="space-y-2">
      {state.has_records && (records.data?.items.length ?? 0) > 0 && (
        <label className="flex items-center gap-2 text-sm">
          <span className="oe-label">{t('settings.document_templates.preview_with', { defaultValue: 'Preview with' })}</span>
          <select className="oe-input flex-1 py-0" value={recordId} onChange={(e) => setRecordId(e.target.value)}>
            <option value="">{t('settings.document_templates.sample_record', { defaultValue: 'Sample values' })}</option>
            {records.data?.items.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="min-h-[420px] overflow-hidden rounded-lg border border-border-light bg-surface-secondary/40" dir={RTL_LANGUAGES.has(locale) ? 'rtl' : 'ltr'}>
        {failed ? (
          <ErrorState
            compact
            title={t('settings.document_templates.preview_failed', { defaultValue: 'Preview could not be drawn' })}
            onRetry={() => void run(new AbortController().signal)}
          />
        ) : email ? (
          <div>
            {email.subject && <div className="border-b border-border-light bg-surface-primary px-3 py-2 text-sm font-medium">{email.subject}</div>}
            <iframe title="email-preview" sandbox="" srcDoc={email.html} className="h-[520px] w-full bg-white" />
          </div>
        ) : pdfUrl ? (
          <iframe title="pdf-preview" src={pdfUrl} className="h-[560px] w-full" />
        ) : (
          <SkeletonText lines={10} />
        )}
      </div>
      <div className="flex items-center justify-between text-xs text-content-secondary">
        <span aria-live="polite">
          {loading
            ? t('settings.document_templates.preview_updating', { defaultValue: 'Updating preview' })
            : t('settings.document_templates.preview_status', { defaultValue: 'Preview updated' })}
        </span>
        {pdfUrl && !email && (
          <a href={pdfUrl} target="_blank" rel="noreferrer" className="font-medium text-oe-blue hover:underline">
            {t('settings.document_templates.open_pdf', { defaultValue: 'Open PDF' })}
          </a>
        )}
      </div>
      {issues.length > 0 && (
        <ul className="space-y-1 text-xs" data-testid="doc-template-issues">
          {issues.map((i, n) => (
            <li key={`${i.rule_id}-${n}`}>
              <button
                type="button"
                className={`text-start hover:underline ${i.severity === 'error' ? 'text-semantic-error' : 'text-content-secondary'}`}
                onClick={() => i.block && onFocusBlock(i.block)}
              >
                {issueText(i)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
