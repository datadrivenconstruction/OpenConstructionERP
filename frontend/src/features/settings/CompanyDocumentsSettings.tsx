// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Company & documents - the logos, the letterhead and how printed documents look.
 *
 * Some firms may not send an RFI without their formal letterhead on it, so
 * this tab gathers everything a printed document carries in one place, top to
 * bottom in the order a site manager thinks about it:
 *
 *   1. two logos, because they do different jobs: the app logo sits in the
 *      sidebar and is often a cropped mark, the document logo is the formal
 *      artwork for paper (and falls back to the app logo when empty);
 *   2. the company details printed under or beside that logo, with a live
 *      preview of the top of page one and a real sample PDF one click away;
 *   3. the document appearance panel, reused from property development;
 *   4. the per-document look, for a kind of document that should differ from
 *      the look above (DocumentTemplatesPanel).
 *
 * The app logo keeps living in the branding store and its endpoint; the rest
 * is the company profile (/api/v1/company-profile/). Admins edit; everyone
 * else sees the same tab read-only, because knowing what documents print is
 * useful even when you cannot change it.
 */

import { useRef, useState, type DragEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Building2,
  ExternalLink,
  ImageIcon,
  Loader2,
  Lock,
  Save,
  Trash2,
  Upload,
} from 'lucide-react';
import { Button, Card, Input, SkeletonText } from '@/shared/ui';
import { ApiError, getErrorMessage, triggerDownload } from '@/shared/lib/api';
import { fmtFixed, fmtList } from '@/shared/lib/formatters';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { BRANDING_MAX_LOGO_BYTES, useBrandingStore } from '@/stores/useBrandingStore';
import { ACCEPTED_IMAGE_TYPES, fileToDataUrl } from '@/app/layout/CustomBranding';
import { isSvgDataUrl, rasteriseSvgToPng } from './rasteriseSvg';
import { DocumentAppearancePanel } from '@/features/property-dev/DocumentAppearancePanel';
import { DocumentTemplatesPanel } from './DocumentTemplatesPanel';
import { getDocumentAppearance, type DocumentAppearance } from '@/features/property-dev/api';
import {
  COMPANY_PROFILE_KEY,
  COMPANY_PROFILE_OPTIONS_KEY,
  COMPANY_TEXT_FIELDS,
  fetchSampleDocumentPdf,
  getCompanyProfile,
  getCompanyProfileOptions,
  hasLetterhead,
  saveCompanyProfile,
  type CompanyProfile,
  type CompanyTextField,
} from './companyProfile';

type CompanyForm = Record<CompanyTextField, string>;

const EMPTY_FORM: CompanyForm = {
  legal_name: '',
  address: '',
  registration_line: '',
  phone: '',
  email: '',
  website: '',
};

/** Aspect ratios of the preview sheet, matching the appearance panel's. */
const PAGE_RATIO: Record<string, number> = {
  A4: 210 / 297,
  LETTER: 216 / 279,
  LEGAL: 216 / 356,
};

const PAGE_WIDTH_MM: Record<string, number> = {
  A4: 210,
  LETTER: 216,
  LEGAL: 216,
};

/** Short names for the accepted image types. Notation, the same in every language. */
const IMAGE_TYPE_NAMES: Record<string, string> = {
  'image/png': 'PNG',
  'image/jpeg': 'JPG',
  'image/svg+xml': 'SVG',
  'image/webp': 'WebP',
};

/** Longest `data:image/...;base64,` prefix, subtracted before sizing the file. */
const DATA_URL_PREFIX_CHARS = 'data:image/svg+xml;base64,'.length;

/**
 * The largest file whose data URL still fits the server's character cap.
 * Base64 writes every 3 bytes as 4 characters.
 */
function maxBytesForDataUrlChars(chars: number): number {
  return Math.floor((chars - DATA_URL_PREFIX_CHARS) / 4) * 3;
}

function fmtMegabytes(bytes: number): string {
  return fmtFixed(bytes / (1024 * 1024), 1);
}

type Translate = ReturnType<typeof useTranslation>['t'];

function typeNamesOf(types: readonly string[]): string {
  return fmtList(types.map((m) => IMAGE_TYPE_NAMES[m] ?? m));
}

function logoTypeError(t: Translate, types: readonly string[]): string {
  return t('settings.company.logo_type_error', {
    defaultValue: 'This file type is not supported. Use {{types}}.',
    types: typeNamesOf(types),
  });
}

function logoSizeError(t: Translate, sizeBytes: number, maxBytes: number): string {
  return t('settings.company.logo_size_error', {
    defaultValue: 'This file is {{size}} MB. The limit is {{max}} MB.',
    size: fmtMegabytes(sizeBytes),
    max: fmtMegabytes(maxBytes),
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Say why the server refused a document logo, in the reader's language.
 *
 * A logo the server would not print is answered with a 422 whose detail names
 * the reason and the limits, and the stored logo is kept. The reason picks the
 * sentence; the server's own English sentence is only the fallback for a
 * reason this screen does not know yet.
 */
function describeLogoRefusal(
  t: Translate,
  err: unknown,
  file: File,
  fallback: { types: readonly string[]; maxChars: number },
): string {
  const detail = err instanceof ApiError && isRecord(err.body) ? err.body.detail : null;
  if (!isRecord(detail) || detail.error !== 'invalid_document_logo') return getErrorMessage(err);
  if (detail.reason === 'too_large') {
    const maxChars = typeof detail.max_chars === 'number' ? detail.max_chars : fallback.maxChars;
    return logoSizeError(t, file.size, maxBytesForDataUrlChars(maxChars));
  }
  if (detail.reason === 'unsupported_format') {
    const types = Array.isArray(detail.accepted_types)
      ? detail.accepted_types.filter((v): v is string => typeof v === 'string')
      : fallback.types;
    return logoTypeError(t, types);
  }
  return typeof detail.message === 'string' ? detail.message : getErrorMessage(err);
}

function formFrom(profile: CompanyProfile): CompanyForm {
  return COMPANY_TEXT_FIELDS.reduce(
    (acc, f) => ({ ...acc, [f]: profile[f] ?? '' }),
    { ...EMPTY_FORM },
  );
}

/**
 * Fold a fresh server answer into the form without losing typing.
 *
 * A field still showing what the previous answer said takes the new value; a
 * field the user has changed keeps the change. That matters because the logo
 * saves on its own, and its answer arrives while the details may be half typed.
 */
function reseed(
  current: CompanyForm,
  previous: CompanyProfile | null,
  next: CompanyProfile,
): CompanyForm {
  if (!previous) return formFrom(next);
  return COMPANY_TEXT_FIELDS.reduce(
    (acc, f) => ({ ...acc, [f]: current[f] === (previous[f] ?? '') ? next[f] ?? '' : current[f] }),
    { ...EMPTY_FORM },
  );
}

/** Keep at most `max` lines, so the textarea cannot grow a line the PDF would drop. */
function limitLines(value: string, max: number): string {
  return value.split('\n').slice(0, max).join('\n');
}

export function CompanyDocumentsSettings() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userRole = useAuthStore((s) => s.userRole);
  // The roles the server's admin gate lets through: superuser and owner are
  // aliases of admin there. A manager lands read-only, as the server would.
  const canEdit = userRole === 'admin' || userRole === 'superuser' || userRole === 'owner';

  const profileQ = useQuery({
    queryKey: COMPANY_PROFILE_KEY,
    queryFn: getCompanyProfile,
  });
  const optionsQ = useQuery({
    queryKey: COMPANY_PROFILE_OPTIONS_KEY,
    queryFn: getCompanyProfileOptions,
    staleTime: 5 * 60_000,
  });
  // Same key and function as the appearance panel below, so both read one cache.
  const appearanceQ = useQuery({
    queryKey: ['document-appearance'],
    queryFn: getDocumentAppearance,
    staleTime: 60_000,
  });
  // The panel's unsaved draft, so the letterhead preview follows the header
  // position and paper size as they are changed, not only once saved.
  const [appearanceDraft, setAppearanceDraft] = useState<DocumentAppearance | null>(null);
  const savedAppearance = appearanceQ.data;
  const appearance = appearanceDraft ?? savedAppearance ?? null;
  const appearanceDirty =
    appearanceDraft !== null &&
    savedAppearance !== undefined &&
    (Object.keys(appearanceDraft) as (keyof DocumentAppearance)[]).some(
      (k) => appearanceDraft[k] !== savedAppearance[k],
    );

  const brandMode = useBrandingStore((s) => s.mode);
  const brandLogo = useBrandingStore((s) => s.logoDataUrl);
  const brandLogoPng = useBrandingStore((s) => s.logoPngDataUrl);
  const setBrandLogo = useBrandingStore((s) => s.setLogo);
  const persistBranding = useBrandingStore((s) => s.persistToServer);
  const appLogo = brandMode === 'logo' ? brandLogo : null;

  const profile = profileQ.data;
  const options = optionsQ.data;

  // Seeded while rendering rather than from an effect, and only once per
  // answer, for the reason EInvoiceSettings records: an effect runs after the
  // frame is painted, and on that frame every field differs from the empty
  // form, so the Save button would offer a change nobody made.
  const [form, setForm] = useState<CompanyForm>(EMPTY_FORM);
  const [seededFrom, setSeededFrom] = useState<CompanyProfile | null>(null);
  if (profile && profile !== seededFrom) {
    const previous = seededFrom;
    setSeededFrom(profile);
    setForm((current) => reseed(current, previous, profile));
  }

  const dirtyFields = profile
    ? COMPANY_TEXT_FIELDS.filter((f) => form[f] !== (profile[f] ?? ''))
    : [];
  const dirty = dirtyFields.length > 0;

  const saveM = useMutation({
    mutationFn: (patch: Partial<CompanyProfile>) => saveCompanyProfile(patch),
    onSuccess: (stored) => {
      // The answer is the sanitised record, so the form moves onto exactly
      // what was stored (trimmed lines, a dropped fourth address line).
      setSeededFrom(stored);
      setForm(formFrom(stored));
      qc.setQueryData(COMPANY_PROFILE_KEY, stored);
      addToast({
        type: 'success',
        title: t('settings.company.saved', {
          defaultValue: 'Company details saved. New documents print them.',
        }),
      });
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  // Saved in a PUT of its own, never with the details: the server refuses a
  // whole request whose logo it would not print, so bundling the two would
  // lose the typed details along with the bad file. Failures are reported by
  // the caller, an upload in the slot and a removal as a toast.
  const logoM = useMutation({
    mutationFn: (logo: { svg: string; png?: string }) =>
      saveCompanyProfile({
        document_logo_data_url: logo.svg,
        ...(logo.png ? { document_logo_png_data_url: logo.png } : {}),
      }),
    onSuccess: (stored, sent) => {
      qc.setQueryData(COMPANY_PROFILE_KEY, stored);
      addToast({
        type: 'success',
        title: sent.svg
          ? t('settings.company.doc_logo_saved', { defaultValue: 'Document logo saved' })
          : t('settings.company.doc_logo_removed', {
              defaultValue: 'Document logo removed. Documents use the app logo.',
            }),
      });
    },
  });

  const [appLogoBusy, setAppLogoBusy] = useState(false);
  const applyAppLogo = async (dataUrl: string | null) => {
    setAppLogoBusy(true);
    try {
      let png: string | null = null;
      if (dataUrl && isSvgDataUrl(dataUrl)) {
        try {
          png = await rasteriseSvgToPng(dataUrl);
        } catch {
          png = null; // the SVG is still saved; the notice asks for a re-upload
        }
      }
      setBrandLogo(dataUrl, png);
      const ok = await persistBranding();
      addToast(
        ok
          ? {
              type: 'success',
              title: dataUrl
                ? t('branding.logo_saved', { defaultValue: 'Logo updated' })
                : t('settings.company.app_logo_removed', { defaultValue: 'App logo removed' }),
              message: t('branding.saved_workspace', {
                defaultValue: 'Applied across this workspace.',
              }),
            }
          : {
              type: 'warning',
              title: t('settings.company.app_logo_local_only', {
                defaultValue: 'Changed in this browser only. The server did not accept it.',
              }),
            },
      );
    } finally {
      setAppLogoBusy(false);
    }
  };

  const [sampleBusy, setSampleBusy] = useState(false);
  const openSample = async () => {
    // Opened before the request, while the click still counts as the user's
    // own gesture. A window opened after an await is a popup, and most
    // browsers block it.
    const tab = window.open('', '_blank');
    setSampleBusy(true);
    try {
      const blob = await fetchSampleDocumentPdf();
      if (tab) {
        const url = URL.createObjectURL(blob);
        tab.location.href = url;
        // Long enough for the tab to load it; the tab keeps its copy after.
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      } else {
        triggerDownload(blob, 'sample.pdf');
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

  const docLogo = profile?.document_logo_data_url ?? '';
  const maxLen = (f: CompanyTextField): number | undefined => options?.max_lengths[f];
  const maxAddressLines = options?.max_address_lines ?? null;
  const docLogoMaxBytes = options ? maxBytesForDataUrlChars(options.max_logo_data_url_chars) : null;

  const setField = (f: CompanyTextField, value: string) =>
    setForm((prev) => ({ ...prev, [f]: value }));

  const save = () => {
    if (!profile) return;
    const patch: Partial<CompanyProfile> = {};
    for (const f of dirtyFields) patch[f] = form[f];
    saveM.mutate(patch);
  };

  return (
    <div className="space-y-5" data-testid="company-documents-settings">
      {!canEdit && (
        <div
          className="flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary/50 px-4 py-3 text-sm text-content-secondary"
          data-testid="company-read-only"
        >
          <Lock size={15} className="mt-0.5 shrink-0" />
          <span>
            {t('settings.company.read_only', {
              defaultValue:
                'An admin sets the logos and company details. You can see here what printed documents carry.',
            })}
          </span>
        </div>
      )}

      {/* ── Logos ── */}
      <Card padding="md">
        <SectionHeader
          icon={<ImageIcon size={16} />}
          title={t('settings.company.logos_title', { defaultValue: 'Logos' })}
          subtitle={t('settings.company.logos_subtitle', {
            defaultValue:
              'Two logos, two jobs: one sits in the app sidebar, the other prints on your documents.',
          })}
        />
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <LogoSlot
            testId="logo-slot-app"
            title={t('settings.company.app_logo_title', {
              defaultValue: 'Logo in the app (sidebar)',
            })}
            hint={t('settings.company.app_logo_hint', {
              defaultValue: 'Shown at the top left of the sidebar and on the sign-in page.',
            })}
            dataUrl={appLogo}
            needsReupload={isSvgDataUrl(appLogo) && !brandLogoPng}
            accept={ACCEPTED_IMAGE_TYPES}
            maxBytes={BRANDING_MAX_LOGO_BYTES}
            canEdit={canEdit}
            busy={appLogoBusy}
            onFile={async (file) => applyAppLogo(await fileToDataUrl(file))}
            onRemove={() => void applyAppLogo(null)}
          />
          <LogoSlot
            testId="logo-slot-document"
            title={t('settings.company.doc_logo_title', { defaultValue: 'Logo on documents' })}
            hint={t('settings.company.doc_logo_hint', {
              defaultValue: 'Your formal logo for printed documents. If empty, the app logo is used.',
            })}
            dataUrl={docLogo || null}
            needsReupload={isSvgDataUrl(docLogo) && !profile?.document_logo_png_data_url}
            fallbackUrl={appLogo}
            accept={options?.logo_mime_types ?? null}
            maxBytes={docLogoMaxBytes}
            canEdit={canEdit && Boolean(profile)}
            busy={logoM.isPending}
            onFile={async (file) => {
              if (!options || docLogoMaxBytes === null) return;
              const dataUrl = await fileToDataUrl(file, {
                accept: options.logo_mime_types,
                maxBytes: docLogoMaxBytes,
              });
              try {
                let png: string | undefined;
                if (isSvgDataUrl(dataUrl)) {
                  try {
                    png = await rasteriseSvgToPng(dataUrl);
                  } catch {
                    png = undefined; // still saved; the notice asks for a re-upload
                  }
                }
                await logoM.mutateAsync({ svg: dataUrl, png });
              } catch (e) {
                // Thrown on as a plain message, which the slot shows under
                // the drop zone, next to the file it is about.
                throw new Error(
                  describeLogoRefusal(t, e, file, {
                    types: options.logo_mime_types,
                    maxChars: options.max_logo_data_url_chars,
                  }),
                );
              }
            }}
            onRemove={() =>
              logoM.mutate({ svg: '' }, {
                onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
              })
            }
          />
        </div>
      </Card>

      {/* ── Letterhead: details and live preview ── */}
      <Card padding="md" data-testid="company-letterhead">
        <SectionHeader
          icon={<Building2 size={16} />}
          title={t('settings.company.details_title', { defaultValue: 'Company letterhead' })}
          subtitle={t('settings.company.details_subtitle', {
            defaultValue:
              'Printed at the top of the first page of the documents you export, such as RFIs. Write each line exactly as it appears on your company paper.',
          })}
        />

        {profileQ.isLoading ? (
          <div className="mt-4">
            <SkeletonText lines={5} />
          </div>
        ) : profileQ.isError || !profile ? (
          <p className="mt-4 text-sm text-content-secondary">
            {t('settings.company.load_failed', {
              defaultValue: 'Could not load the company details. Try again in a moment.',
            })}
          </p>
        ) : (
          <>
            <div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
              <form
                noValidate
                className="grid content-start gap-4 sm:grid-cols-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (canEdit && dirty) save();
                }}
              >
                <div className="sm:col-span-2">
                  <Input
                    id="company-legal-name"
                    label={t('settings.company.legal_name', { defaultValue: 'Legal company name' })}
                    value={form.legal_name}
                    maxLength={maxLen('legal_name')}
                    readOnly={!canEdit}
                    onChange={(e) => setField('legal_name', e.target.value)}
                    placeholder={t('settings.company.legal_name_placeholder', {
                      defaultValue: 'Acme Construction Ltd',
                    })}
                    hint={t('settings.company.legal_name_hint', {
                      defaultValue:
                        'The letterhead prints once a legal name or a document logo is set. Address and numbers alone do not switch it on.',
                    })}
                  />
                </div>

                <div className="sm:col-span-2 flex flex-col gap-1.5">
                  <label
                    htmlFor="company-address"
                    className="text-sm font-medium text-content-primary"
                  >
                    {t('settings.company.address', { defaultValue: 'Address' })}
                  </label>
                  <textarea
                    id="company-address"
                    name="company-address"
                    autoComplete="off"
                    rows={maxAddressLines ?? 3}
                    value={form.address}
                    maxLength={maxLen('address')}
                    readOnly={!canEdit}
                    onChange={(e) =>
                      setField(
                        'address',
                        maxAddressLines ? limitLines(e.target.value, maxAddressLines) : e.target.value,
                      )
                    }
                    placeholder={t('settings.company.address_placeholder', {
                      defaultValue: '12 Harbour Road\nSpringfield 12345\nUnited States',
                    })}
                    className="w-full resize-none rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary hover:border-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                    aria-describedby="company-address-hint"
                  />
                  {maxAddressLines !== null && (
                    <p id="company-address-hint" className="text-xs text-content-tertiary">
                      {t('settings.company.address_hint', {
                        defaultValue: 'Up to {{lines}} lines, in the order your country writes them.',
                        lines: maxAddressLines,
                      })}
                    </p>
                  )}
                </div>

                <div className="sm:col-span-2">
                  <Input
                    id="company-registration-line"
                    label={t('settings.company.registration_line', {
                      defaultValue: 'Registration and licence numbers',
                    })}
                    value={form.registration_line}
                    maxLength={maxLen('registration_line')}
                    readOnly={!canEdit}
                    onChange={(e) => setField('registration_line', e.target.value)}
                    placeholder={t('settings.company.registration_line_placeholder', {
                      defaultValue: 'CA License #1234567 · EIN 12-3456789',
                    })}
                    hint={t('settings.company.registration_line_hint', {
                      defaultValue: 'One line, printed exactly as you type it.',
                    })}
                  />
                </div>

                <Input
                  id="company-phone"
                  type="tel"
                  label={t('settings.company.phone', { defaultValue: 'Phone' })}
                  value={form.phone}
                  maxLength={maxLen('phone')}
                  readOnly={!canEdit}
                  onChange={(e) => setField('phone', e.target.value)}
                />
                <Input
                  id="company-email"
                  type="email"
                  label={t('settings.company.email', { defaultValue: 'Email' })}
                  value={form.email}
                  maxLength={maxLen('email')}
                  readOnly={!canEdit}
                  onChange={(e) => setField('email', e.target.value)}
                />
                <div className="sm:col-span-2">
                  <Input
                    id="company-website"
                    label={t('settings.company.website', { defaultValue: 'Website' })}
                    value={form.website}
                    maxLength={maxLen('website')}
                    readOnly={!canEdit}
                    onChange={(e) => setField('website', e.target.value)}
                  />
                </div>
              </form>

              <div>
                <span className="mb-1 block text-xs font-medium text-content-primary">
                  {t('settings.company.preview_title', {
                    defaultValue: 'Top of page 1, as printed',
                  })}
                </span>
                <LetterheadPreview
                  form={form}
                  documentLogo={docLogo}
                  appLogo={appLogo}
                  appearance={appearance}
                />
                <Button
                  variant="secondary"
                  size="sm"
                  className="mt-3"
                  onClick={() => void openSample()}
                  disabled={sampleBusy}
                  icon={
                    sampleBusy ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <ExternalLink size={14} />
                    )
                  }
                  data-testid="company-open-sample"
                >
                  {t('settings.company.open_sample', { defaultValue: 'Open sample PDF' })}
                </Button>
                {(dirty || appearanceDirty) && (
                  <p className="mt-1.5 text-[11px] leading-snug text-content-secondary">
                    {t('settings.company.sample_saved_only', {
                      defaultValue: 'The sample PDF shows saved settings. Save your changes first.',
                    })}
                  </p>
                )}
              </div>
            </div>

            {canEdit && (
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
                <Button
                  variant="primary"
                  size="sm"
                  icon={
                    saveM.isPending ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Save size={14} />
                    )
                  }
                  disabled={!dirty || saveM.isPending}
                  onClick={save}
                  data-testid="company-save"
                >
                  {t('settings.company.save', { defaultValue: 'Save company details' })}
                </Button>
                {dirty && (
                  <span className="text-xs text-content-secondary">
                    {t('settings.company.unsaved', { defaultValue: 'Unsaved changes' })}
                  </span>
                )}
              </div>
            )}
          </>
        )}
      </Card>

      {/* ── How documents look ── */}
      <DocumentAppearancePanel placement="settings" onDraftChange={setAppearanceDraft} />

      {/* ── Per-document look ── */}
      <DocumentTemplatesPanel />
    </div>
  );
}

/* ── Section header ──────────────────────────────────────────────────── */

function SectionHeader({
  icon,
  title,
  subtitle,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
        {icon}
      </div>
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-content-primary">{title}</h2>
        <p className="mt-0.5 max-w-3xl text-xs text-content-secondary">{subtitle}</p>
      </div>
    </div>
  );
}

/* ── Logo slot ───────────────────────────────────────────────────────── */

interface LogoSlotProps {
  testId: string;
  title: string;
  hint: string;
  dataUrl: string | null;
  /** An SVG stored without its PNG copy, which PDFs need. */
  needsReupload?: boolean;
  /** What prints while this slot is empty (the document logo's fallback). */
  fallbackUrl?: string | null;
  /** Accepted MIME types; `null` while the server's list is still loading. */
  accept: readonly string[] | null;
  maxBytes: number | null;
  canEdit: boolean;
  busy: boolean;
  /** Called with a file that already passed the type and size checks. */
  onFile: (file: File) => Promise<void>;
  onRemove: () => void;
}

function LogoSlot({
  testId,
  title,
  hint,
  dataUrl,
  needsReupload = false,
  fallbackUrl = null,
  accept,
  maxBytes,
  canEdit,
  busy,
  onFile,
  onRemove,
}: LogoSlotProps) {
  const { t } = useTranslation();
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const ready = canEdit && accept !== null && maxBytes !== null && !busy;

  const typeNames = accept ? typeNamesOf(accept) : '';

  const take = async (file: File | undefined) => {
    if (!file || !ready || !accept || maxBytes === null) return;
    // Checked here, before the shared reader, so every message the user sees
    // is in their language rather than the reader's English.
    if (!accept.includes(file.type)) {
      setProblem(logoTypeError(t, accept));
      return;
    }
    if (file.size > maxBytes) {
      setProblem(logoSizeError(t, file.size, maxBytes));
      return;
    }
    setProblem(null);
    try {
      await onFile(file);
    } catch (e) {
      setProblem(getErrorMessage(e));
    }
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    void take(e.dataTransfer.files?.[0]);
  };

  const browse = () => fileRef.current?.click();

  return (
    <div
      className={clsx(
        'flex flex-col rounded-xl border p-4 transition-colors',
        dragging ? 'border-oe-blue bg-oe-blue/5' : 'border-border-light bg-surface-primary',
      )}
      data-testid={testId}
      onDragOver={(e) => {
        if (!ready) return;
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={ready ? onDrop : undefined}
    >
      <h3 className="text-sm font-semibold text-content-primary">{title}</h3>
      <p className="mt-0.5 text-xs text-content-secondary">{hint}</p>

      <input
        ref={fileRef}
        type="file"
        accept={accept?.join(',')}
        className="hidden"
        onChange={(e) => {
          void take(e.target.files?.[0]);
          // Cleared so picking the same file again after an error still fires.
          e.target.value = '';
        }}
      />

      {dataUrl ? (
        <>
          {/* The same logo on white paper and on a dark sidebar, because a
              transparent logo that works on one often disappears on the other. */}
          <div className="mt-3 grid grid-cols-2 gap-2">
            <LogoTile src={dataUrl} dark={false} label={t('settings.company.on_white', { defaultValue: 'On white' })} />
            <LogoTile src={dataUrl} dark label={t('settings.company.on_dark', { defaultValue: 'On dark' })} />
          </div>
          {canEdit && (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={busy ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
                onClick={browse}
                disabled={!ready}
              >
                {t('settings.company.logo_replace', { defaultValue: 'Replace' })}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                icon={<Trash2 size={14} />}
                onClick={() => {
                  setProblem(null);
                  onRemove();
                }}
                disabled={busy}
              >
                {t('common.remove', { defaultValue: 'Remove' })}
              </Button>
            </div>
          )}
        </>
      ) : canEdit ? (
        <div
          role="button"
          tabIndex={ready ? 0 : -1}
          aria-disabled={!ready}
          onClick={browse}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              browse();
            }
          }}
          className={clsx(
            'mt-3 flex flex-1 flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors',
            ready
              ? 'cursor-pointer border-border hover:border-oe-blue/60 hover:bg-surface-secondary/40'
              : 'cursor-wait border-border-light opacity-60',
          )}
        >
          {busy ? (
            <Loader2 size={20} className="animate-spin text-oe-blue" />
          ) : (
            <Upload size={20} className="text-oe-blue" />
          )}
          <p className="text-sm font-medium text-content-primary">
            {t('branding.logo_drop', {
              defaultValue: 'Drop your logo here, or click to browse',
            })}
          </p>
        </div>
      ) : (
        <p className="mt-3 text-sm text-content-tertiary">
          {t('settings.company.logo_none', { defaultValue: 'No logo set.' })}
        </p>
      )}

      {dataUrl && needsReupload && (
        <p className="mt-2 text-xs text-semantic-warning" data-testid={`${testId}-reupload`}>
          {t('settings.company.logo_svg_reupload', {
            defaultValue: 'Upload this SVG logo again so it prints on your PDFs.',
          })}
        </p>
      )}

      {canEdit && accept && maxBytes !== null && (
        <p className="mt-2 text-[11px] leading-snug text-content-tertiary">
          {t('settings.company.logo_formats', {
            defaultValue:
              '{{types}}, up to {{max}} MB. A transparent PNG or an SVG in a wide format prints best.',
            types: typeNames,
            max: fmtMegabytes(maxBytes),
          })}
        </p>
      )}

      {!dataUrl && fallbackUrl && (
        <div className="mt-2 flex items-center gap-2 text-[11px] text-content-secondary">
          <img
            src={fallbackUrl}
            alt=""
            className="h-5 w-10 rounded border border-border-light bg-white object-contain"
            draggable={false}
          />
          {t('settings.company.doc_logo_fallback', {
            defaultValue: 'Documents print the app logo until you add one here.',
          })}
        </div>
      )}

      {problem && (
        <p role="alert" className="mt-2 text-xs text-semantic-error">
          {problem}
        </p>
      )}
    </div>
  );
}

function LogoTile({ src, dark, label }: { src: string; dark: boolean; label: string }) {
  return (
    <figure className="flex flex-col gap-1">
      <div
        className={clsx(
          'flex h-20 items-center justify-center rounded-lg border p-3',
          dark ? 'border-slate-700 bg-slate-900' : 'border-border-light bg-white',
        )}
      >
        <img src={src} alt={label} className="max-h-full max-w-full object-contain" draggable={false} />
      </div>
      <figcaption className="text-center text-[10px] text-content-tertiary">{label}</figcaption>
    </figure>
  );
}

/* ── Letterhead preview ──────────────────────────────────────────────── */

/** The logo box the letterhead draws, in millimetres: shallower when centred. */
const LOGO_BOX_MM = { side: { w: 60, h: 20 }, centre: { w: 60, h: 15 } } as const;

/**
 * The top of page one as the server prints it, redrawn as the user types.
 *
 * The geometry follows the PDF: the logo box, the gap to the rule and the
 * space before the body are converted from millimetres to a share of the
 * printable width, so they keep their proportions at any preview size (a
 * vertical margin in percent is measured against the width too). The text is
 * drawn larger than its 9 and 7.5 pt, keeping their ratio, because at true
 * scale it would not be readable on screen. Like the appearance preview it
 * does not mimic the typeface; the sample PDF is the source of truth.
 *
 * Honest about when there is nothing to print: the server draws a letterhead
 * only with a legal name or a document logo, and only while the appearance
 * switch is on, so the preview shows neither a tidy contact block nor the app
 * logo in cases the PDF would leave blank.
 */
function LetterheadPreview({
  form,
  documentLogo,
  appLogo,
  appearance,
}: {
  form: CompanyForm;
  documentLogo: string;
  appLogo: string | null;
  appearance: DocumentAppearance | null;
}) {
  const { t } = useTranslation();
  const pageSize = appearance?.page_size ?? 'A4';
  const ratio = PAGE_RATIO[pageSize] ?? PAGE_RATIO.A4;
  const pageWidthMm = PAGE_WIDTH_MM[pageSize] ?? 210;
  const marginMm = appearance?.margin_mm ?? 20;
  const contentMm = Math.max(1, pageWidthMm - 2 * marginMm);
  const pct = (mm: number) => `${(mm / contentMm) * 100}%`;
  const align = appearance?.logo_align ?? 'left';
  const centred = align === 'center';
  const accent = appearance?.accent_color ?? '#1a1a2e';
  const switchedOn = appearance?.show_letterhead !== false;
  const printable = hasLetterhead({
    legal_name: form.legal_name,
    document_logo_data_url: documentLogo,
  });
  const logo = documentLogo || appLogo;
  const box = centred ? LOGO_BOX_MM.centre : LOGO_BOX_MM.side;

  // The middle dot is separator notation, not prose. Centred, the address
  // becomes one line, as the PDF prints it there.
  const addressLines = form.address
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  const address = centred && addressLines.length > 0 ? [addressLines.join(' · ')] : addressLines;
  const contact = [form.phone, form.email, form.website]
    .map((part) => part.trim())
    .filter(Boolean)
    .join(' · ');

  // Beside a logo the block reads away from it; without one it takes the
  // logo's place, so it aligns to the chosen side itself.
  const textAlign = centred
    ? 'text-center'
    : logo
      ? align === 'right'
        ? 'text-left'
        : 'text-right'
      : align === 'right'
        ? 'text-right'
        : 'text-left';

  const notice = (text: string, testId?: string) => (
    <p
      className="rounded border border-dashed border-[#d1d5db] px-2 py-3 text-center text-[10px] text-[#6b7280]"
      data-testid={testId}
    >
      {text}
    </p>
  );

  return (
    <div
      className="relative w-full overflow-hidden rounded border border-border bg-white shadow-sm"
      style={{ aspectRatio: String(ratio) }}
      data-testid="letterhead-preview"
    >
      <div className="flex h-full flex-col" style={{ padding: `${(marginMm / pageWidthMm) * 100}%` }}>
        {!switchedOn ? (
          notice(
            t('settings.company.preview_switched_off', {
              defaultValue: 'The letterhead is switched off in Document appearance below.',
            }),
          )
        ) : !printable ? (
          notice(
            t('settings.company.preview_empty', {
              defaultValue: 'No letterhead yet. Add a legal name or a document logo and it appears here.',
            }),
            'letterhead-preview-empty',
          )
        ) : (
          <>
            <div
              className={clsx(
                'flex gap-2',
                centred
                  ? 'flex-col items-center'
                  : align === 'right'
                    ? 'flex-row-reverse items-center justify-between'
                    : 'flex-row items-center justify-between',
              )}
            >
              {logo && (
                <div
                  className="flex shrink-0 items-center justify-center"
                  style={{ width: pct(box.w), aspectRatio: `${box.w} / ${box.h}` }}
                >
                  <img
                    src={logo}
                    alt=""
                    className="max-h-full max-w-full object-contain"
                    draggable={false}
                  />
                </div>
              )}
              <div className={clsx('min-w-0 break-words', textAlign, !logo && 'w-full')}>
                {form.legal_name.trim() && (
                  <div
                    className="text-[11px] font-bold leading-tight"
                    style={{ color: accent }}
                    data-testid="letterhead-preview-name"
                  >
                    {form.legal_name}
                  </div>
                )}
                {address.map((line, i) => (
                  <div key={i} className="text-[9px] leading-snug text-[#666666]">
                    {line}
                  </div>
                ))}
                {form.registration_line.trim() && (
                  <div className="text-[9px] leading-snug text-[#666666]">
                    {form.registration_line}
                  </div>
                )}
                {contact && <div className="text-[9px] leading-snug text-[#666666]">{contact}</div>}
              </div>
            </div>
            <div className="h-px w-full bg-[#cccccc]" style={{ marginTop: pct(3) }} />
          </>
        )}

        {/* The document itself, greyed: a title bar, then body lines. */}
        <div
          className="flex-1 space-y-1.5"
          style={{ marginTop: pct(5) }}
          aria-hidden="true"
        >
          <div className="h-2 w-2/5 rounded-sm opacity-70" style={{ backgroundColor: accent }} />
          {[100, 94, 97, 70, 90, 84, 60, 96, 88].map((w, i) => (
            <div key={i} className="h-1 rounded-sm bg-[#e5e7eb]" style={{ width: `${w}%` }} />
          ))}
        </div>
      </div>
    </div>
  );
}
