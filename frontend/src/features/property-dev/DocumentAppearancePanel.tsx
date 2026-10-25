// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Document Appearance - how generated PDFs look.
 *
 * The sibling of the workspace brand: the brand says whose document it is,
 * this says what it looks like. Both are read by the same PDF layer, so a
 * change here shows up in every document the platform generates, not only the
 * property-development ones this page lists.
 *
 * Two halves, deliberately side by side:
 *
 *   - the controls, in four groups (page, header, footer, watermark), built
 *     from the server's own options endpoint so the form can never offer a
 *     value the server would discard; and
 *   - a live paper preview that redraws as you type.
 *
 * The preview is why this is a panel and not a form. Every value here is
 * visual - a colour, an alignment, a margin - and a number in a field does not
 * tell you whether 12 mm margins look cramped. The preview is an honest
 * approximation, not a renderer: it shows page proportions, margins, the brand
 * line at its chosen alignment in the accent colour, and the footer in its
 * colour with or without a page number. It deliberately does not try to mimic
 * the typeface, because the PDF uses DejaVu and the browser would not, and a
 * preview that lies about the face is worse than one that does not show it.
 * The "Preview a real document" button next to the built-in templates renders
 * the actual PDF, and that stays the source of truth.
 *
 * Writing needs admin. A non-admin sees the same panel read-only rather than
 * an empty space, because knowing how documents are configured is useful even
 * when you cannot change it.
 *
 * The panel sits in two places: here, above the built-in templates, and in the
 * Company & documents settings tab, which has no templates under it. The copy
 * that points "below" is swapped there, and that tab mirrors the unsaved draft
 * into its letterhead preview through `onDraftChange`.
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Palette, RotateCcw, Save } from 'lucide-react';
import { Button, Card, Input, SkeletonText } from '@/shared/ui';
import { Toggle } from '@/shared/ui/Toggle';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  getDocumentAppearance,
  getDocumentAppearanceOptions,
  resetDocumentAppearance,
  saveDocumentAppearance,
  type DocumentAppearance,
} from './api';
import {
  MARGIN_PRESETS,
  pageNumberSample,
  printStampSample,
  sheetMm,
  withAppearanceDefaults,
} from './documentPreviewLayout';

/**
 * One-click watermark words. Each is inserted in the reader's language and
 * stays editable, because the mark prints as saved, untranslated.
 */
export const WATERMARK_PRESETS = [
  { key: 'draft', i18nKey: 'property_dev.doc_appearance.watermark_preset_draft', fallback: 'DRAFT' },
  { key: 'confidential', i18nKey: 'property_dev.doc_appearance.watermark_preset_confidential', fallback: 'CONFIDENTIAL' },
  { key: 'copy', i18nKey: 'property_dev.doc_appearance.watermark_preset_copy', fallback: 'COPY' },
  { key: 'not_for_construction', i18nKey: 'property_dev.doc_appearance.watermark_preset_not_for_construction', fallback: 'NOT FOR CONSTRUCTION' },
] as const;

const SELECT_CLS =
  'h-8 w-full rounded border border-border bg-surface-primary px-2 text-xs disabled:opacity-60';

interface DocumentAppearancePanelProps {
  /** Where the panel is shown; decides whether the copy may point at templates below it. */
  placement?: 'templates' | 'settings';
  /** Called with the unsaved draft whenever it changes, so a sibling preview can follow it. */
  onDraftChange?: (draft: DocumentAppearance) => void;
}

export function DocumentAppearancePanel({
  placement = 'templates',
  onDraftChange,
}: DocumentAppearancePanelProps = {}) {
  const { t } = useTranslation();
  const inSettings = placement === 'settings';
  const addToast = useToastStore((s) => s.addToast);
  const qc = useQueryClient();
  const userRole = useAuthStore((s) => s.userRole);
  const canEdit =
    userRole === 'admin' || userRole === 'superuser' || userRole === 'owner';

  const appearanceQ = useQuery({
    queryKey: ['document-appearance'],
    queryFn: getDocumentAppearance,
    staleTime: 60_000,
  });
  const optionsQ = useQuery({
    queryKey: ['document-appearance', 'options'],
    queryFn: getDocumentAppearanceOptions,
    staleTime: 5 * 60_000,
  });

  // The draft the form edits. Seeded from the server and re-seeded whenever the
  // server's answer changes, so a save (which returns the sanitised result)
  // pulls the form onto exactly what was stored rather than leaving it showing
  // a value the server rejected.
  const [draft, setDraft] = useState<DocumentAppearance | null>(null);
  useEffect(() => {
    if (appearanceQ.data) setDraft(appearanceQ.data);
  }, [appearanceQ.data]);

  useEffect(() => {
    if (draft) onDraftChange?.(draft);
  }, [draft, onDraftChange]);

  const dirty = useMemo(() => {
    if (!draft || !appearanceQ.data) return false;
    return (Object.keys(draft) as (keyof DocumentAppearance)[]).some(
      (k) => draft[k] !== appearanceQ.data[k],
    );
  }, [draft, appearanceQ.data]);

  const saveM = useMutation({
    mutationFn: (next: DocumentAppearance) => saveDocumentAppearance(next),
    onSuccess: (stored) => {
      qc.setQueryData(['document-appearance'], stored);
      setDraft(stored);
      addToast({
        type: 'success',
        title: t('property_dev.doc_appearance.saved', {
          defaultValue: 'Document appearance saved. New exports use it.',
        }),
      });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const resetM = useMutation({
    mutationFn: resetDocumentAppearance,
    onSuccess: (defaults) => {
      qc.setQueryData(['document-appearance'], defaults);
      setDraft(defaults);
      addToast({
        type: 'success',
        title: t('property_dev.doc_appearance.reset_done', {
          defaultValue: 'Back to the platform look.',
        }),
      });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const busy = saveM.isPending || resetM.isPending;
  const options = optionsQ.data;

  const set = <K extends keyof DocumentAppearance>(
    key: K,
    value: DocumentAppearance[K],
  ) => setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));

  if (appearanceQ.isLoading || !draft) {
    return (
      <Card padding="md" data-testid="doc-appearance-loading">
        <SkeletonText lines={4} />
      </Card>
    );
  }

  if (appearanceQ.isError) {
    // Not an empty space and not a blocking error: the templates below still
    // work, so this says what is unavailable and lets the page carry on.
    return (
      <Card padding="md">
        <p className="text-xs text-content-secondary">
          {inSettings
            ? t('settings.company.appearance_load_failed', {
                defaultValue: 'Could not load the document appearance settings.',
              })
            : t('property_dev.doc_appearance.load_failed', {
                defaultValue:
                  'Could not load the document appearance settings. Templates below are unaffected.',
              })}
        </p>
      </Card>
    );
  }

  const look = withAppearanceDefaults(draft);
  const sheet = sheetMm(look.page_size, look.page_orientation);
  const ratio = sheet.w / sheet.h;
  const marginPct = (look.margin_mm / sheet.w) * 100;
  const landscape = look.page_orientation === 'landscape';
  const stampSample = printStampSample(look.print_stamp);
  const footerLeft =
    look.footer_text ||
    (look.print_stamp === 'auto'
      ? t('property_dev.doc_appearance.preview_footer', {
          defaultValue: 'Your company | Generated 2026-01-01',
        })
      : t('property_dev.doc_appearance.preview_brand', { defaultValue: 'Your company' }));
  const optionList = (offered: string[] | undefined, current: string) => offered ?? [current];

  return (
    <Card padding="md" data-testid="doc-appearance-panel">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          <Palette size={16} />
        </div>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-content-primary">
            {inSettings
              ? t('settings.company.appearance_title', {
                  defaultValue: 'Documents and PDF',
                })
              : t('property_dev.doc_appearance.title', {
                  defaultValue: 'How your documents look',
                })}
          </h2>
          <p className="mt-0.5 max-w-3xl text-xs text-content-secondary">
            {inSettings
              ? t('settings.company.appearance_subtitle', {
                  defaultValue:
                    'Applies to every PDF the platform generates. The logo and company details above head the first page.',
                })
              : t('property_dev.doc_appearance.subtitle', {
                  defaultValue:
                    'Applies to every PDF the platform generates, not just the templates below. Your logo and company name are set in workspace branding.',
                })}
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1fr)_260px]">
        {/* ── Controls, in four groups ── */}
        <div className="grid min-w-0 content-start gap-4">
          <AppearanceGroup
            testId="appearance-group-page"
            title={t('property_dev.doc_appearance.group_page', { defaultValue: 'Page' })}
          >
            <label className="text-xs">
              <span className="mb-1 block font-medium text-content-primary">
                {t('property_dev.doc_appearance.page_size', {
                  defaultValue: 'Paper size',
                })}
              </span>
              <select
                value={draft.page_size}
                disabled={!canEdit || busy || !options}
                onChange={(e) => set('page_size', e.target.value)}
                className={SELECT_CLS}
                data-testid="appearance-page-size"
              >
                {(options?.page_sizes ?? [draft.page_size]).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-xs">
              <span className="mb-1 block font-medium text-content-primary">
                {t('property_dev.doc_appearance.page_orientation', {
                  defaultValue: 'Orientation',
                })}
              </span>
              <select
                value={look.page_orientation}
                disabled={!canEdit || busy || !options}
                onChange={(e) => set('page_orientation', e.target.value)}
                className={SELECT_CLS}
                data-testid="appearance-orientation"
              >
                {optionList(options?.page_orientations, look.page_orientation).map((o) => (
                  <option key={o} value={o}>
                    {o === 'landscape'
                      ? t('property_dev.doc_appearance.orientation_landscape', {
                          defaultValue: 'Landscape',
                        })
                      : t('property_dev.doc_appearance.orientation_portrait', {
                          defaultValue: 'Portrait',
                        })}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-content-tertiary">
                {t('property_dev.doc_appearance.orientation_hint', {
                  defaultValue:
                    'For documents laid out on the workspace paper size, such as the property development forms. Forms with a fixed sheet keep it.',
                })}
              </p>
            </label>

            <div>
              <Input
                type="number"
                label={t('property_dev.doc_appearance.margin_mm', {
                  defaultValue: 'Page margin (mm)',
                })}
                value={draft.margin_mm}
                min={options?.min_margin_mm}
                max={options?.max_margin_mm}
                disabled={!canEdit || busy}
                onChange={(e) =>
                  set('margin_mm', Number(e.target.value) || draft.margin_mm)
                }
                hint={
                  options
                    ? t('property_dev.doc_appearance.margin_hint', {
                        defaultValue: '{{min}} to {{max}}. Most printers clip below 10.',
                        min: options.min_margin_mm,
                        max: options.max_margin_mm,
                      })
                    : undefined
                }
                data-testid="appearance-margin"
              />
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {MARGIN_PRESETS.map((preset) => (
                  <button
                    key={preset.key}
                    type="button"
                    disabled={!canEdit || busy}
                    aria-pressed={draft.margin_mm === preset.mm}
                    onClick={() => set('margin_mm', preset.mm)}
                    className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium disabled:cursor-not-allowed disabled:opacity-50 ${
                      draft.margin_mm === preset.mm
                        ? 'border-oe-blue text-oe-blue'
                        : 'border-border text-content-secondary hover:border-oe-blue hover:text-oe-blue'
                    }`}
                    data-testid={`appearance-margin-preset-${preset.key}`}
                  >
                    {preset.key === 'narrow'
                      ? t('property_dev.doc_appearance.margin_preset_narrow', {
                          defaultValue: 'Narrow',
                        })
                      : preset.key === 'wide'
                        ? t('property_dev.doc_appearance.margin_preset_wide', {
                            defaultValue: 'Wide',
                          })
                        : t('property_dev.doc_appearance.margin_preset_normal', {
                            defaultValue: 'Normal',
                          })}{' '}
                    ({preset.mm})
                  </button>
                ))}
              </div>
            </div>

            <Input
              type="number"
              label={t('property_dev.doc_appearance.base_font_size', {
                defaultValue: 'Body text size (pt)',
              })}
              value={draft.base_font_size}
              min={options?.min_font_size}
              max={options?.max_font_size}
              disabled={!canEdit || busy}
              onChange={(e) =>
                set('base_font_size', Number(e.target.value) || draft.base_font_size)
              }
              hint={
                options
                  ? t('property_dev.doc_appearance.font_hint', {
                      defaultValue: '{{min}} to {{max}}. Headings scale with it.',
                      min: options.min_font_size,
                      max: options.max_font_size,
                    })
                  : undefined
              }
              data-testid="appearance-font-size"
            />

            <label className="text-xs">
              <span className="mb-1 block font-medium text-content-primary">
                {t('property_dev.doc_appearance.accent_color', {
                  defaultValue: 'Heading colour',
                })}
              </span>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={draft.accent_color}
                  disabled={!canEdit || busy}
                  onChange={(e) => set('accent_color', e.target.value)}
                  className="h-8 w-12 cursor-pointer rounded border border-border bg-surface-primary disabled:opacity-60"
                  data-testid="appearance-accent"
                  aria-label={t('property_dev.doc_appearance.accent_color', {
                    defaultValue: 'Heading colour',
                  })}
                />
                <code className="text-[11px] text-content-secondary">
                  {draft.accent_color}
                </code>
              </div>
            </label>
          </AppearanceGroup>

          <AppearanceGroup
            testId="appearance-group-header"
            title={t('property_dev.doc_appearance.group_header', { defaultValue: 'Header' })}
          >
            <label className="text-xs">
              <span className="mb-1 block font-medium text-content-primary">
                {t('property_dev.doc_appearance.logo_align', {
                  defaultValue: 'Header position',
                })}
              </span>
              <select
                value={draft.logo_align}
                disabled={!canEdit || busy || !options}
                onChange={(e) => set('logo_align', e.target.value)}
                className={SELECT_CLS}
                data-testid="appearance-logo-align"
              >
                {(options?.logo_alignments ?? [draft.logo_align]).map((a) => (
                  <option key={a} value={a}>
                    {a === 'left'
                      ? t('common.left', { defaultValue: 'Left' })
                      : a === 'center'
                        ? t('common.center', { defaultValue: 'Centre' })
                        : t('common.right', { defaultValue: 'Right' })}
                  </option>
                ))}
              </select>
              {/* The exports that draw their own header title keep the logo in the
                  opposite corner on purpose, so the two never overlap. Without
                  this line a workspace that picks Left, opens a bill of
                  quantities and finds the logo still on the right reads the
                  control as broken rather than as deferring to a layout. */}
              <p className="mt-1 text-xs text-content-tertiary">
                {t('property_dev.doc_appearance.logo_align_hint', {
                  defaultValue:
                    'Exports that print their own title in the header keep the logo in the opposite corner, so the two do not overlap.',
                })}
              </p>
            </label>

            <div className="flex flex-col gap-4">
              <Toggle
                checked={draft.show_letterhead}
                onChange={(next) => set('show_letterhead', next)}
                disabled={!canEdit || busy}
                label={t('property_dev.doc_appearance.show_letterhead', {
                  defaultValue: 'Print the company letterhead on the first page',
                })}
                description={t('property_dev.doc_appearance.show_letterhead_hint', {
                  defaultValue:
                    'Turn off when you print on paper that already carries your letterhead.',
                })}
              />
              <Toggle
                checked={look.header_show_contact}
                onChange={(next) => set('header_show_contact', next)}
                disabled={!canEdit || busy}
                label={t('property_dev.doc_appearance.header_show_contact', {
                  defaultValue: 'Company address and contact in the header',
                })}
                description={t('property_dev.doc_appearance.header_show_contact_hint', {
                  defaultValue:
                    'Small print opposite the logo on pages that carry the header band, such as the bill of quantities. The first page shows the letterhead instead.',
                })}
              />
              <Toggle
                checked={look.header_rule}
                onChange={(next) => set('header_rule', next)}
                disabled={!canEdit || busy}
                label={t('property_dev.doc_appearance.header_rule', {
                  defaultValue: 'Line under the header',
                })}
              />
            </div>
          </AppearanceGroup>

          <AppearanceGroup
            testId="appearance-group-footer"
            title={t('property_dev.doc_appearance.group_footer', { defaultValue: 'Footer' })}
          >
            <div className="sm:col-span-2">
              <Input
                label={t('property_dev.doc_appearance.footer_text', {
                  defaultValue: 'Footer line',
                })}
                value={draft.footer_text}
                maxLength={options?.max_footer_text}
                disabled={!canEdit || busy}
                onChange={(e) => set('footer_text', e.target.value)}
                placeholder={t('property_dev.doc_appearance.footer_placeholder', {
                  defaultValue: 'Leave empty to show the company name and date',
                })}
                hint={t('property_dev.doc_appearance.footer_hint', {
                  defaultValue:
                    'Replaces the generated date. Use it for a registered company line.',
                })}
                data-testid="appearance-footer-text"
              />
            </div>

            <label className="text-xs">
              <span className="mb-1 block font-medium text-content-primary">
                {t('property_dev.doc_appearance.footer_color', {
                  defaultValue: 'Footer colour',
                })}
              </span>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={draft.footer_color}
                  disabled={!canEdit || busy}
                  onChange={(e) => set('footer_color', e.target.value)}
                  className="h-8 w-12 cursor-pointer rounded border border-border bg-surface-primary disabled:opacity-60"
                  data-testid="appearance-footer-color"
                  aria-label={t('property_dev.doc_appearance.footer_color', {
                    defaultValue: 'Footer colour',
                  })}
                />
                <code className="text-[11px] text-content-secondary">
                  {draft.footer_color}
                </code>
              </div>
            </label>

            <label className="text-xs">
              <span className="mb-1 block font-medium text-content-primary">
                {t('property_dev.doc_appearance.print_stamp', {
                  defaultValue: 'Print date and time',
                })}
              </span>
              <select
                value={look.print_stamp}
                disabled={!canEdit || busy || !options}
                onChange={(e) => set('print_stamp', e.target.value)}
                className={SELECT_CLS}
                data-testid="appearance-print-stamp"
              >
                {optionList(options?.print_stamps, look.print_stamp).map((m) => (
                  <option key={m} value={m}>
                    {m === 'none'
                      ? t('property_dev.doc_appearance.print_stamp_none', {
                          defaultValue: 'No date',
                        })
                      : m === 'date'
                        ? t('property_dev.doc_appearance.print_stamp_date', {
                            defaultValue: 'Print date',
                          })
                        : m === 'datetime'
                          ? t('property_dev.doc_appearance.print_stamp_datetime', {
                              defaultValue: 'Print date and time',
                            })
                          : t('property_dev.doc_appearance.print_stamp_auto', {
                              defaultValue: 'Default (date in the footer line)',
                            })}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-xs text-content-tertiary">
                {t('property_dev.doc_appearance.print_stamp_hint', {
                  defaultValue:
                    'Printed on its own line under the footer, in UTC. Not every document type prints that line yet.',
                })}
              </p>
            </label>

            <div className="sm:col-span-2 flex flex-col gap-4">
              <Toggle
                checked={draft.show_page_numbers}
                onChange={(next) => set('show_page_numbers', next)}
                disabled={!canEdit || busy}
                label={t('property_dev.doc_appearance.page_numbers', {
                  defaultValue: 'Show page numbers',
                })}
                description={t('property_dev.doc_appearance.page_numbers_hint', {
                  defaultValue:
                    'Turn off when these documents are filed inside a bundle that paginates itself.',
                })}
              />
              <label className="text-xs">
                <span className="mb-1 block font-medium text-content-primary">
                  {t('property_dev.doc_appearance.page_number_format', {
                    defaultValue: 'Page number format',
                  })}
                </span>
                {/* The formats are what the PDF prints, in English whatever the
                    interface language, so they are shown as printed. */}
                <select
                  value={look.page_number_format}
                  disabled={!canEdit || busy || !options || !draft.show_page_numbers}
                  onChange={(e) => set('page_number_format', e.target.value)}
                  className={SELECT_CLS}
                  data-testid="appearance-page-number-format"
                >
                  {optionList(options?.page_number_formats, look.page_number_format).map((f) => (
                    <option key={f} value={f}>
                      {pageNumberSample(f, 3, 7)}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-content-tertiary">
                  {t('property_dev.doc_appearance.page_number_format_hint', {
                    defaultValue:
                      'Used by the shared page footer. Forms with their own translated footer keep their wording.',
                  })}
                </p>
              </label>
              <Toggle
                checked={look.footer_show_registration}
                onChange={(next) => set('footer_show_registration', next)}
                disabled={!canEdit || busy}
                label={t('property_dev.doc_appearance.footer_show_registration', {
                  defaultValue: 'Registration numbers in the footer',
                })}
                description={t('property_dev.doc_appearance.footer_show_registration_hint', {
                  defaultValue:
                    'Prints the registration and licence line from the company details (tax ID, commercial register) under the footer.',
                })}
              />
            </div>
          </AppearanceGroup>

          <AppearanceGroup
            testId="appearance-group-watermark"
            title={t('property_dev.doc_appearance.group_watermark', {
              defaultValue: 'Watermark',
            })}
          >
            <div className="sm:col-span-2">
              <Input
                label={t('property_dev.doc_appearance.watermark', { defaultValue: 'Watermark' })}
                value={draft.watermark_text ?? ''}
                maxLength={options?.max_watermark_text}
                disabled={!canEdit || busy}
                onChange={(e) => set('watermark_text', e.target.value)}
                placeholder={t('property_dev.doc_appearance.watermark_placeholder', {
                  defaultValue: 'Leave empty for no watermark',
                })}
                hint={t('property_dev.doc_appearance.watermark_hint', {
                  defaultValue:
                    'Printed faintly across every page of forms and reports. A document type below can set its own or none.',
                })}
                data-testid="appearance-watermark"
              />
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {WATERMARK_PRESETS.map((preset) => {
                  const word = t(preset.i18nKey, {
                    defaultValue: preset.fallback,
                  });
                  return (
                    <button
                      key={preset.key}
                      type="button"
                      disabled={!canEdit || busy}
                      onClick={() => set('watermark_text', word)}
                      className="rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium text-content-secondary hover:border-oe-blue hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-50"
                      data-testid={`appearance-watermark-preset-${preset.key}`}
                    >
                      {word}
                    </button>
                  );
                })}
              </div>
            </div>

            <label className="text-xs">
              <span className="mb-1 block font-medium text-content-primary">
                {t('property_dev.doc_appearance.watermark_opacity', {
                  defaultValue: 'Watermark strength (%)',
                })}
              </span>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min={options?.min_watermark_opacity ?? 5}
                  max={options?.max_watermark_opacity ?? 40}
                  value={look.watermark_opacity}
                  disabled={!canEdit || busy}
                  onChange={(e) => set('watermark_opacity', Number(e.target.value))}
                  className="w-full disabled:opacity-60"
                  data-testid="appearance-watermark-opacity"
                  aria-label={t('property_dev.doc_appearance.watermark_opacity', {
                    defaultValue: 'Watermark strength (%)',
                  })}
                />
                <code className="w-8 shrink-0 text-right text-[11px] text-content-secondary">
                  {look.watermark_opacity}
                </code>
              </div>
            </label>

            <label className="text-xs">
              <span className="mb-1 block font-medium text-content-primary">
                {t('property_dev.doc_appearance.watermark_layout', {
                  defaultValue: 'Watermark direction',
                })}
              </span>
              <select
                value={look.watermark_layout}
                disabled={!canEdit || busy || !options}
                onChange={(e) => set('watermark_layout', e.target.value)}
                className={SELECT_CLS}
                data-testid="appearance-watermark-layout"
              >
                {optionList(options?.watermark_layouts, look.watermark_layout).map((l) => (
                  <option key={l} value={l}>
                    {l === 'horizontal'
                      ? t('property_dev.doc_appearance.watermark_layout_horizontal', {
                          defaultValue: 'Horizontal',
                        })
                      : t('property_dev.doc_appearance.watermark_layout_diagonal', {
                          defaultValue: 'Diagonal',
                        })}
                  </option>
                ))}
              </select>
            </label>
          </AppearanceGroup>
        </div>

        {/* ── Live preview ── */}
        <div className="lg:sticky lg:top-4 lg:self-start">
          <span className="mb-1 block text-xs font-medium text-content-primary">
            {t('property_dev.doc_appearance.preview', { defaultValue: 'Preview' })}
          </span>
          <div
            className="relative mx-auto w-full overflow-hidden rounded border border-border bg-white shadow-sm"
            style={{ aspectRatio: String(ratio), maxWidth: landscape ? '100%' : undefined }}
            data-testid="appearance-preview"
            aria-hidden="true"
          >
            {draft.watermark_text && (
              <div
                className="pointer-events-none absolute inset-0 flex items-center justify-center overflow-hidden"
                data-testid="appearance-preview-watermark"
              >
                <span
                  className="whitespace-nowrap font-bold text-[#6b7280]"
                  style={{
                    opacity: look.watermark_opacity / 100,
                    fontSize: `${Math.max(10, Math.min(28, 220 / Math.max(4, draft.watermark_text.length)))}px`,
                    transform:
                      look.watermark_layout === 'horizontal'
                        ? undefined
                        : `rotate(-${Math.round((Math.atan(1 / (ratio || 1)) * 180) / Math.PI)}deg)`,
                  }}
                >
                  {draft.watermark_text}
                </span>
              </div>
            )}
            <div
              className="flex h-full flex-col"
              style={{ padding: `${marginPct}%` }}
            >
              <div
                className="flex items-start justify-between gap-2"
                style={{
                  flexDirection: draft.logo_align === 'right' ? 'row-reverse' : 'row',
                  justifyContent: draft.logo_align === 'center' ? 'center' : 'space-between',
                }}
              >
                <div
                  className="truncate font-semibold"
                  style={{
                    color: draft.accent_color,
                    fontSize: `${draft.base_font_size * 0.62}px`,
                  }}
                >
                  {t('property_dev.doc_appearance.preview_brand', {
                    defaultValue: 'Your company',
                  })}
                </div>
                {look.header_show_contact && (
                  <div
                    className={`truncate text-[#666666] ${draft.logo_align === 'right' ? 'text-left' : 'text-right'}`}
                    style={{ fontSize: `${Math.max(4, draft.base_font_size * 0.4)}px` }}
                    data-testid="appearance-preview-contact"
                  >
                    {t('property_dev.doc_appearance.preview_contact', {
                      defaultValue: 'Your address and contact details',
                    })}
                  </div>
                )}
              </div>
              {look.header_rule && (
                <div
                  className="mt-1 h-px w-full bg-[#cccccc]"
                  data-testid="appearance-preview-rule"
                />
              )}
              <div className="mt-2 flex-1 space-y-1">
                {[100, 92, 96, 74, 88, 60].map((w, i) => (
                  <div
                    key={i}
                    className="rounded-sm bg-[#e5e7eb]"
                    style={{
                      width: `${w}%`,
                      height: `${Math.max(2, draft.base_font_size * 0.34)}px`,
                    }}
                  />
                ))}
              </div>
              <div
                className="flex flex-col gap-0.5"
                style={{
                  color: draft.footer_color,
                  fontSize: `${Math.max(4, draft.base_font_size * 0.45)}px`,
                }}
              >
                <div className="flex items-end justify-between gap-2">
                  <span className="truncate" data-testid="appearance-preview-footer">
                    {footerLeft}
                  </span>
                  {draft.show_page_numbers && (
                    <span className="shrink-0" data-testid="appearance-preview-page-number">
                      {pageNumberSample(look.page_number_format)}
                    </span>
                  )}
                </div>
                {(look.footer_show_registration || stampSample) && (
                  <div
                    className="flex items-end justify-between gap-2"
                    style={{ fontSize: '0.9em' }}
                    data-testid="appearance-preview-footer-2"
                  >
                    <span className="truncate">
                      {look.footer_show_registration
                        ? t('property_dev.doc_appearance.preview_registration', {
                            defaultValue: 'Your registration numbers',
                          })
                        : ''}
                    </span>
                    <span className="shrink-0">{stampSample}</span>
                  </div>
                )}
              </div>
            </div>
          </div>
          <p className="mt-1.5 text-[11px] leading-snug text-content-secondary">
            {inSettings
              ? t('settings.company.appearance_preview_note', {
                  defaultValue: 'Layout only. Open the sample PDF above to see a real one.',
                })
              : t('property_dev.doc_appearance.preview_note', {
                  defaultValue:
                    'Layout only. Use Preview on a template below to render a real PDF.',
                })}
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <Button
          variant="primary"
          size="sm"
          icon={busy ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          disabled={!canEdit || !dirty || busy}
          onClick={() => draft && saveM.mutate(draft)}
          data-testid="appearance-save"
        >
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          icon={<RotateCcw size={14} />}
          disabled={!canEdit || busy}
          onClick={() => resetM.mutate()}
          data-testid="appearance-reset"
        >
          {t('property_dev.doc_appearance.reset', {
            defaultValue: 'Reset to platform look',
          })}
        </Button>
        {/* The reset clears the workspace look only. A document type that sets
            its own look in Settings keeps it, and an admin who expected the
            reset to reach every document would otherwise find one unchanged. */}
        {canEdit && (
          <span className="text-xs text-content-tertiary" data-testid="appearance-reset-note">
            {t('settings.document_templates.workspace_reset_note', {
              defaultValue: 'Document types with their own look keep it after a reset.',
            })}
          </span>
        )}
        {!canEdit && (
          <span className="text-xs text-content-secondary">
            {t('property_dev.doc_appearance.admin_only', {
              defaultValue: 'Only an admin can change this.',
            })}
          </span>
        )}
        {canEdit && dirty && (
          <span className="text-xs text-content-secondary">
            {t('property_dev.doc_appearance.unsaved', {
              defaultValue: 'Unsaved changes. Existing PDFs are not re-rendered.',
            })}
          </span>
        )}
      </div>
    </Card>
  );
}

/** One titled group of controls; the legend is what names it for assistive technology. */
function AppearanceGroup({
  title,
  testId,
  children,
}: {
  title: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <fieldset className="min-w-0 rounded-lg border border-border-light p-3" data-testid={testId}>
      <legend className="px-1 text-[11px] font-semibold uppercase tracking-wide text-content-tertiary">
        {title}
      </legend>
      <div className="grid gap-4 sm:grid-cols-2">{children}</div>
    </fieldset>
  );
}

export default DocumentAppearancePanel;
