// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Per-document look - the fourth section of Company & documents.
 *
 * The panel above sets the look of every PDF. This one lets a single kind of
 * document differ from it: one row per type, and inside a row one line per
 * field the type's generator reads. A field is either set for this document
 * or follows the look above, and the checkbox says which, because "the same
 * colour as the workspace" and "follows the workspace colour" look identical
 * today and part ways the day someone changes the workspace.
 *
 * Unset fields show the inherited value, read from the saved workspace look
 * (the same query the panel above keeps current), so a reset up there shows
 * here at once rather than after a refetch.
 *
 * The letterhead fields do nothing while the company profile has no legal
 * name and no document logo, since nothing prints a letterhead then. They are
 * disabled with the reason next to them instead of accepting a value that
 * changes no document.
 *
 * Each row's sample PDF is drawn from the saved settings on the sheet that
 * document prints on, so what it shows is what prints.
 *
 * A type whose generator prints optional parts (the purchase order's notes,
 * the invoice's payment history...) also lists those parts, each with a switch.
 * They are saved on their own, because they say what the document contains
 * rather than how it looks.
 */

import { useEffect, useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { ChevronDown, ExternalLink, FileStack, Loader2, RotateCcw, Save } from 'lucide-react';
import { Button, Card, Input, SkeletonText } from '@/shared/ui';
import { Toggle } from '@/shared/ui/Toggle';
import { getErrorMessage, triggerDownload } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  getDocumentAppearance,
  getDocumentAppearanceOptions,
  type DocumentAppearance,
  type DocumentAppearanceOptions,
} from '@/features/property-dev/api';
import { COMPANY_PROFILE_KEY, getCompanyProfile, hasLetterhead } from './companyProfile';
import {
  DOCUMENT_TYPES_KEY,
  LETTERHEAD_FIELDS,
  fetchDocumentTypeSamplePdf,
  getDocumentTypes,
  isDocumentTypeField,
  resetDocumentTypeOverride,
  saveDocumentTypeOverride,
  saveDocumentTypeSections,
  type DocumentTypeEntry,
  type DocumentTypeField,
  type DocumentTypeOverride,
} from './documentTemplates';

const SELECT_CLS =
  'h-8 w-full rounded border border-border bg-surface-primary px-2 text-xs disabled:opacity-60';

export function DocumentTemplatesPanel() {
  const { t } = useTranslation();
  const userRole = useAuthStore((s) => s.userRole);
  // The roles the server's admin gate lets through, as in the sections above.
  const canEdit = userRole === 'admin' || userRole === 'superuser' || userRole === 'owner';

  const typesQ = useQuery({
    queryKey: DOCUMENT_TYPES_KEY,
    queryFn: getDocumentTypes,
    staleTime: 60_000,
  });
  // Same keys and functions as the appearance panel above, so all read one cache.
  const workspaceQ = useQuery({
    queryKey: ['document-appearance'],
    queryFn: getDocumentAppearance,
    staleTime: 60_000,
  });
  const optionsQ = useQuery({
    queryKey: ['document-appearance', 'options'],
    queryFn: getDocumentAppearanceOptions,
    staleTime: 5 * 60_000,
  });
  const profileQ = useQuery({
    queryKey: COMPANY_PROFILE_KEY,
    queryFn: getCompanyProfile,
  });

  // Unknown until the profile arrives, and unknown does not lock anything: the
  // server accepts the value either way, the lock is only there to explain.
  const letterhead = profileQ.data ? hasLetterhead(profileQ.data) : true;

  if (typesQ.isLoading) {
    return (
      <Card padding="md" data-testid="doc-types-loading">
        <SkeletonText lines={3} />
      </Card>
    );
  }

  if (typesQ.isError) {
    return (
      <Card padding="md">
        <p className="text-xs text-content-secondary">
          {t('settings.document_templates.load_failed', {
            defaultValue: 'Could not load the document types.',
          })}
        </p>
      </Card>
    );
  }

  const entries = typesQ.data ?? [];
  if (entries.length === 0) return null;

  return (
    <Card padding="md" data-testid="doc-types-panel">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          <FileStack size={16} />
        </div>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('settings.document_templates.title', { defaultValue: 'Per-document look' })}
          </h2>
          <p className="mt-0.5 max-w-3xl text-xs text-content-secondary">
            {t('settings.document_templates.subtitle', {
              defaultValue:
                'Give one kind of document a look of its own. Whatever you do not set here follows the look above, and each sample prints on the paper that document uses.',
            })}
          </p>
        </div>
      </div>

      <ul className="mt-4 divide-y divide-border rounded-lg border border-border">
        {entries.map((entry) => (
          <DocumentTypeRow
            key={entry.key}
            entry={entry}
            workspace={workspaceQ.data ?? entry.effective}
            options={optionsQ.data}
            letterhead={letterhead}
            canEdit={canEdit}
          />
        ))}
      </ul>

      {!canEdit && (
        <p className="mt-3 text-xs text-content-secondary">
          {t('property_dev.doc_appearance.admin_only', {
            defaultValue: 'Only an admin can change this.',
          })}
        </p>
      )}
    </Card>
  );
}

/* ── One document type ───────────────────────────────────────────────── */

interface DocumentTypeRowProps {
  entry: DocumentTypeEntry;
  /** The saved workspace look, which every unset field follows. */
  workspace: DocumentAppearance;
  options: DocumentAppearanceOptions | undefined;
  /** Whether printed documents carry a letterhead at all. */
  letterhead: boolean;
  canEdit: boolean;
}

function sameOverride(a: DocumentTypeOverride, b: DocumentTypeOverride): boolean {
  const keysA = Object.keys(a) as DocumentTypeField[];
  const keysB = Object.keys(b) as DocumentTypeField[];
  return keysA.length === keysB.length && keysA.every((k) => k in b && a[k] === b[k]);
}

function DocumentTypeRow({ entry, workspace, options, letterhead, canEdit }: DocumentTypeRowProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const panelId = useId();

  // The fields this client knows how to edit, in the server's order. A field a
  // newer server adds is left out rather than drawn as a control with no meaning.
  const fields = useMemo(() => entry.fields.filter(isDocumentTypeField), [entry.fields]);

  // The draft holds exactly the pinned fields: a key present is set for this
  // document, a key absent follows the workspace. Re-seeded from what the
  // server stored after every save and reset.
  const [draft, setDraft] = useState<DocumentTypeOverride>(entry.override);
  useEffect(() => {
    setDraft(entry.override);
  }, [entry.override]);

  const dirty = !sameOverride(draft, entry.override);
  const ownLook = Object.keys(entry.override).length > 0;
  const name = t(`settings.document_templates.types.${entry.key}`, { defaultValue: entry.label });

  const store = (stored: DocumentTypeEntry) => {
    qc.setQueryData<DocumentTypeEntry[]>(DOCUMENT_TYPES_KEY, (prev) =>
      prev?.map((e) => (e.key === stored.key ? stored : e)),
    );
    setDraft(stored.override);
  };

  const saveM = useMutation({
    mutationFn: (next: DocumentTypeOverride) => saveDocumentTypeOverride(entry.key, next),
    onSuccess: (stored) => {
      store(stored);
      addToast({
        type: 'success',
        title: t('settings.document_templates.saved', {
          defaultValue: 'Saved. New documents of this kind use it.',
        }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('settings.document_templates.save_failed', {
          defaultValue: "Could not save this document's look",
        }),
        message: getErrorMessage(e),
      }),
  });

  const resetM = useMutation({
    mutationFn: () => resetDocumentTypeOverride(entry.key),
    onSuccess: (stored) => {
      store(stored);
      addToast({
        type: 'success',
        title: t('settings.document_templates.reset_done', {
          defaultValue: 'This document follows the look above again.',
        }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('settings.document_templates.reset_failed', {
          defaultValue: "Could not reset this document's look",
        }),
        message: getErrorMessage(e),
      }),
  });

  const busy = saveM.isPending || resetM.isPending;

  const [sampleBusy, setSampleBusy] = useState(false);
  const openSample = async () => {
    // Opened before the request, while the click still counts as the user's
    // own gesture; a window opened after an await is a blocked popup.
    const tab = window.open('', '_blank');
    setSampleBusy(true);
    try {
      const blob = await fetchDocumentTypeSamplePdf(entry.key);
      if (tab) {
        const url = URL.createObjectURL(blob);
        tab.location.href = url;
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      } else {
        triggerDownload(blob, `sample-${entry.key}.pdf`);
        addToast({
          type: 'info',
          title: t('settings.company.sample_downloaded', {
            defaultValue: 'The browser blocked a new tab, so the sample PDF was downloaded instead.',
          }),
        });
      }
    } catch (e) {
      tab?.close();
      addToast({
        type: 'error',
        title: t('settings.company.sample_failed', {
          defaultValue: 'Could not open the sample PDF',
        }),
        message: getErrorMessage(e),
      });
    } finally {
      setSampleBusy(false);
    }
  };

  const pin = (field: DocumentTypeField, pinned: boolean) =>
    setDraft((prev) => {
      const next = { ...prev };
      if (pinned) {
        // Starts from the value the document prints today, so ticking the box
        // alone changes nothing until a value is picked.
        (next as Record<DocumentTypeField, unknown>)[field] = workspace[field];
      } else {
        delete next[field];
      }
      return next;
    });

  const setValue = (field: DocumentTypeField, value: string | boolean) =>
    setDraft((prev) => ({ ...prev, [field]: value }));

  const save = () => {
    // Built from the pinned set, not from the values: a pinned `false` for the
    // page numbers is a setting, and dropping it would quietly unpin it.
    const body: DocumentTypeOverride = {};
    for (const field of fields) {
      if (field in draft) (body as Record<DocumentTypeField, unknown>)[field] = draft[field];
    }
    saveM.mutate(body);
  };

  const hasLetterheadField = fields.some((f) => LETTERHEAD_FIELDS.includes(f));

  return (
    <li data-testid={`doc-type-row-${entry.key}`}>
      <button
        type="button"
        className="flex w-full items-center gap-3 px-3 py-2.5 text-start hover:bg-surface-secondary/50"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        data-testid={`doc-type-toggle-${entry.key}`}
      >
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-content-primary">{name}</span>
        {dirty && (
          <span className="shrink-0 text-xs text-content-secondary">
            {t('settings.company.unsaved', { defaultValue: 'Unsaved changes' })}
          </span>
        )}
        <span
          className={clsx(
            'shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium',
            ownLook ? 'bg-oe-blue/10 text-oe-blue' : 'bg-surface-secondary text-content-secondary',
          )}
          data-testid={`doc-type-status-${entry.key}`}
        >
          {ownLook
            ? t('settings.document_templates.status_own', { defaultValue: 'Own look' })
            : t('settings.document_templates.status_inherits', {
                defaultValue: 'Same as all documents',
              })}
        </span>
        <ChevronDown
          size={16}
          className={clsx('shrink-0 text-content-tertiary transition-transform', open && 'rotate-180')}
        />
      </button>

      {open && (
        <div id={panelId} className="border-t border-border px-3 py-3">
          {hasLetterheadField && !letterhead && (
            <p
              className="mb-3 rounded border border-border bg-surface-secondary/50 px-3 py-2 text-xs text-content-secondary"
              data-testid={`doc-type-no-letterhead-${entry.key}`}
            >
              {t('settings.document_templates.no_letterhead', {
                defaultValue:
                  'Letterhead settings take effect once the company details above have a legal name or a document logo.',
              })}
            </p>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            {fields.map((field) => {
              const pinned = field in draft;
              // A letterhead field with no letterhead to print changes nothing,
              // so it cannot be newly set. One set earlier can still be cleared.
              const inert = LETTERHEAD_FIELDS.includes(field) && !letterhead;
              return (
                <FieldEditor
                  key={field}
                  typeKey={entry.key}
                  field={field}
                  pinned={pinned}
                  value={draft[field] ?? workspace[field]}
                  options={options}
                  pinDisabled={!canEdit || busy || (inert && !pinned)}
                  controlDisabled={!canEdit || busy || !pinned || inert}
                  onPin={(next) => pin(field, next)}
                  onChange={(next) => setValue(field, next)}
                />
              );
            })}
          </div>

          {(entry.sections?.length ?? 0) > 0 && (
            <SectionsEditor entry={entry} canEdit={canEdit} onStored={store} />
          )}

          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
            {canEdit && (
              <>
                <Button
                  variant="primary"
                  size="sm"
                  icon={
                    saveM.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />
                  }
                  disabled={!dirty || busy}
                  onClick={save}
                  data-testid={`doc-type-save-${entry.key}`}
                >
                  {t('common.save', { defaultValue: 'Save' })}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<RotateCcw size={14} />}
                  disabled={!ownLook || busy}
                  onClick={() => resetM.mutate()}
                  data-testid={`doc-type-reset-${entry.key}`}
                >
                  {t('settings.document_templates.reset', { defaultValue: 'Use the look above' })}
                </Button>
              </>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void openSample()}
              disabled={sampleBusy}
              icon={
                sampleBusy ? <Loader2 size={14} className="animate-spin" /> : <ExternalLink size={14} />
              }
              data-testid={`doc-type-sample-${entry.key}`}
            >
              {t('settings.company.open_sample', { defaultValue: 'Open sample PDF' })}
            </Button>
            {dirty && (
              <span className="text-xs text-content-secondary">
                {t('settings.company.sample_saved_only', {
                  defaultValue: 'The sample PDF shows saved settings. Save your changes first.',
                })}
              </span>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

/* ── Sections ────────────────────────────────────────────────────────── */

interface SectionsEditorProps {
  entry: DocumentTypeEntry;
  canEdit: boolean;
  onStored: (stored: DocumentTypeEntry) => void;
}

function sameSections(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((s) => b.includes(s));
}

function SectionsEditor({ entry, canEdit, onStored }: SectionsEditorProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const sections = entry.sections ?? [];
  const stored = useMemo(() => entry.hidden_sections ?? [], [entry.hidden_sections]);

  // The draft is the set of sections left out; everything else prints.
  const [hidden, setHidden] = useState<string[]>(stored);
  useEffect(() => {
    setHidden(stored);
  }, [stored]);
  const dirty = !sameSections(hidden, stored);

  const saveM = useMutation({
    mutationFn: () => saveDocumentTypeSections(entry.key, hidden),
    onSuccess: (next) => {
      onStored(next);
      addToast({
        type: 'success',
        title: t('settings.document_templates.sections_saved', {
          defaultValue: 'Saved. New documents of this kind include only the sections switched on.',
        }),
      });
    },
    onError: (e) =>
      addToast({
        type: 'error',
        title: t('settings.document_templates.sections_save_failed', {
          defaultValue: 'Could not save the sections of this document',
        }),
        message: getErrorMessage(e),
      }),
  });

  const sectionLabel = (section: string) =>
    t(`settings.document_templates.sections.${section}`, { defaultValue: section.replace(/_/g, ' ') });

  return (
    <div className="mt-4 border-t border-border pt-3" data-testid={`doc-type-sections-${entry.key}`}>
      <h3 className="text-xs font-semibold text-content-primary">
        {t('settings.document_templates.sections_title', { defaultValue: 'What the document includes' })}
      </h3>
      <p className="mt-0.5 text-[11px] text-content-tertiary">
        {t('settings.document_templates.sections_hint', {
          defaultValue: 'Switch a section off to leave it out of every new document of this kind.',
        })}
      </p>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {sections.map((section) => {
          const shown = !hidden.includes(section);
          return (
            <div key={section} data-testid={`doc-type-section-${entry.key}-${section}`}>
              <Toggle
                size="sm"
                checked={shown}
                disabled={!canEdit || saveM.isPending}
                onChange={(next) =>
                  setHidden((prev) => (next ? prev.filter((s) => s !== section) : [...prev, section]))
                }
                label={sectionLabel(section)}
              />
            </div>
          );
        })}
      </div>
      {canEdit && (
        <div className="mt-3">
          <Button
            variant="secondary"
            size="sm"
            icon={saveM.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            disabled={!dirty || saveM.isPending}
            onClick={() => saveM.mutate()}
            data-testid={`doc-type-sections-save-${entry.key}`}
          >
            {t('settings.document_templates.sections_save', { defaultValue: 'Save sections' })}
          </Button>
        </div>
      )}
    </div>
  );
}

/* ── One field ───────────────────────────────────────────────────────── */

interface FieldEditorProps {
  typeKey: string;
  field: DocumentTypeField;
  pinned: boolean;
  /** The pinned value, or the inherited one when the field is not pinned. */
  value: string | boolean;
  options: DocumentAppearanceOptions | undefined;
  pinDisabled: boolean;
  controlDisabled: boolean;
  onPin: (pinned: boolean) => void;
  onChange: (value: string | boolean) => void;
}

function FieldEditor({
  typeKey,
  field,
  pinned,
  value,
  options,
  pinDisabled,
  controlDisabled,
  onPin,
  onChange,
}: FieldEditorProps) {
  const { t } = useTranslation();
  const labelId = useId();

  const label = (() => {
    switch (field) {
      case 'show_letterhead':
        return t('property_dev.doc_appearance.show_letterhead', {
          defaultValue: 'Print the company letterhead on the first page',
        });
      case 'logo_align':
        return t('property_dev.doc_appearance.logo_align', { defaultValue: 'Header position' });
      case 'accent_color':
        return t('property_dev.doc_appearance.accent_color', { defaultValue: 'Heading colour' });
      case 'footer_text':
        return t('property_dev.doc_appearance.footer_text', { defaultValue: 'Footer line' });
      case 'footer_color':
        return t('property_dev.doc_appearance.footer_color', { defaultValue: 'Footer colour' });
      case 'show_page_numbers':
        return t('property_dev.doc_appearance.page_numbers', { defaultValue: 'Show page numbers' });
      case 'watermark_text':
        return t('property_dev.doc_appearance.watermark', { defaultValue: 'Watermark' });
    }
  })();

  const alignLabel = (a: string) =>
    a === 'left'
      ? t('common.left', { defaultValue: 'Left' })
      : a === 'center'
        ? t('common.center', { defaultValue: 'Centre' })
        : t('common.right', { defaultValue: 'Right' });

  const control = (() => {
    switch (field) {
      case 'show_letterhead':
      case 'show_page_numbers':
        return (
          <Toggle
            checked={Boolean(value)}
            onChange={(next) => onChange(next)}
            disabled={controlDisabled}
            label={value ? t('common.on', { defaultValue: 'On' }) : t('common.off', { defaultValue: 'Off' })}
          />
        );
      case 'logo_align':
        return (
          <select
            value={String(value)}
            disabled={controlDisabled}
            onChange={(e) => onChange(e.target.value)}
            className={SELECT_CLS}
            aria-labelledby={labelId}
          >
            {(options?.logo_alignments ?? [String(value)]).map((a) => (
              <option key={a} value={a}>
                {alignLabel(a)}
              </option>
            ))}
          </select>
        );
      case 'accent_color':
      case 'footer_color':
        return (
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={String(value)}
              disabled={controlDisabled}
              onChange={(e) => onChange(e.target.value)}
              className="h-8 w-12 cursor-pointer rounded border border-border bg-surface-primary disabled:cursor-not-allowed disabled:opacity-60"
              aria-labelledby={labelId}
            />
            <code className="text-[11px] text-content-secondary">{String(value)}</code>
          </div>
        );
      case 'footer_text':
        return (
          <Input
            value={String(value)}
            maxLength={options?.max_footer_text}
            disabled={controlDisabled}
            onChange={(e) => onChange(e.target.value)}
            placeholder={t('property_dev.doc_appearance.footer_placeholder', {
              defaultValue: 'Leave empty to show the company name and date',
            })}
            aria-labelledby={labelId}
          />
        );
      case 'watermark_text':
        return (
          <Input
            value={String(value ?? '')}
            maxLength={options?.max_watermark_text}
            disabled={controlDisabled}
            onChange={(e) => onChange(e.target.value)}
            placeholder={t('property_dev.doc_appearance.watermark_placeholder', {
              defaultValue: 'Leave empty for no watermark',
            })}
            aria-labelledby={labelId}
          />
        );
    }
  })();

  return (
    <div
      role="group"
      aria-labelledby={labelId}
      className={clsx('text-xs', (field === 'footer_text' || field === 'watermark_text') && 'sm:col-span-2')}
      data-testid={`doc-type-field-${typeKey}-${field}`}
    >
      <div className="mb-1 flex items-start justify-between gap-2">
        <span id={labelId} className="font-medium text-content-primary">
          {label}
        </span>
        <label className="inline-flex shrink-0 items-center gap-1.5 text-content-secondary">
          <input
            type="checkbox"
            checked={pinned}
            disabled={pinDisabled}
            onChange={(e) => onPin(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border disabled:opacity-60"
            data-testid={`doc-type-pin-${typeKey}-${field}`}
          />
          {t('settings.document_templates.pin', { defaultValue: 'Set for this document' })}
        </label>
      </div>
      {control}
      {!pinned && (
        <p className="mt-1 text-[11px] text-content-tertiary">
          {t('settings.document_templates.inherited', { defaultValue: 'Follows the look above' })}
        </p>
      )}
    </div>
  );
}

export default DocumentTemplatesPanel;
