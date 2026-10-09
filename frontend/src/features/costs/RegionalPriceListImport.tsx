// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Import a regional price list": upload the file an Italian region publishes,
 * see what it holds (edition, licence, chapters, sample rows), then confirm to
 * create a cost catalogue named after the region and edition.
 *
 * Nothing is written until the user presses Import; the preview is read-only.
 * Both run as server jobs, so a list of any size shows how far it has got
 * instead of timing out.
 */
import { useRef, useState, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, BookOpen, CheckCircle2, Loader2, Upload } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { importFailureText } from '@/features/boq/importFailureText';
import {
  PRICE_LIST_REGIONS,
  PriceListError,
  discardPriceListUpload,
  importUploadedPriceList,
  repreviewPriceList,
  uploadPriceList,
  type PriceListImportResult,
  type PriceListOverrides,
  type PriceListPreview,
  type PriceListProgress,
} from './regionalPriceListApi';

const ACCEPT = '.xml,.xpwe,.pwe,.csv,.xlsx,.json,.zip,.txt';

function useErrorText() {
  const { t } = useTranslation();
  return (error: unknown): string => {
    if (!(error instanceof PriceListError)) {
      return t('costs_pricelist.error_generic', { defaultValue: 'The price list could not be read.' });
    }
    const p = error.params;
    const texts: Record<string, string> = {
      empty_file: t('costs_pricelist.error_empty_file', { defaultValue: 'The file is empty.' }),
      file_too_large: t('costs_pricelist.error_file_too_large', {
        defaultValue: 'The file is larger than {{limit}} MB.',
        limit: p.limit_mb,
      }),
      zip_unreadable: t('costs_pricelist.error_zip_unreadable', { defaultValue: 'The ZIP archive cannot be opened.' }),
      zip_too_many_members: t('costs_pricelist.error_zip_too_many_members', {
        defaultValue: 'The ZIP archive holds more than {{limit}} files.',
        limit: p.limit,
      }),
      zip_too_large_inflated: t('costs_pricelist.error_zip_too_large_inflated', {
        defaultValue: 'The ZIP archive would unpack to more than {{limit}} MB.',
        limit: p.limit_mb,
      }),
      zip_ratio_suspicious: t('costs_pricelist.error_zip_ratio_suspicious', {
        defaultValue: 'A file in the ZIP archive is compressed far more than any price list is, so it was not opened.',
      }),
      zip_encrypted: t('costs_pricelist.error_zip_encrypted', {
        defaultValue: 'The ZIP archive is password protected.',
      }),
      zip_member_too_large: t('costs_pricelist.error_zip_member_too_large', {
        defaultValue: 'A file in the ZIP archive unpacks to more than it declares, so the import stopped.',
      }),
      no_price_list_found: t('costs_pricelist.error_no_price_list_found', {
        defaultValue: 'No regional price list in a recognised format was found in this file.',
      }),
      pricelist_unreadable: t('costs_pricelist.error_generic', { defaultValue: 'The price list could not be read.' }),
      invalid_region: t('costs_pricelist.error_invalid_region', { defaultValue: 'Unknown region.' }),
      invalid_edition: t('costs_pricelist.error_invalid_edition', {
        defaultValue: 'The edition must be a year, such as 2025.',
      }),
      catalog_name_required: t('costs_pricelist.error_catalog_name_required', {
        defaultValue: 'Enter a name for the new catalogue.',
      }),
      catalog_name_too_long: t('costs_pricelist.error_catalog_name_too_long', {
        defaultValue: 'The catalogue name can be at most {{limit}} characters.',
        limit: p.limit,
      }),
      // Neutral on purpose: the name may be another user's catalogue.
      catalog_name_unavailable: p.suggestion
        ? t('costs_pricelist.error_catalog_name_unavailable_suggest', {
            defaultValue: 'This name cannot be used for a new catalogue. Choose another name, such as "{{suggestion}}".',
            suggestion: p.suggestion,
          })
        : t('costs_pricelist.error_catalog_name_unavailable', {
            defaultValue: 'This name cannot be used for a new catalogue. Choose another name.',
          }),
      zip_member_corrupt: p.member
        ? t('costs_pricelist.error_zip_member_corrupt_named', {
            defaultValue: 'The file "{{member}}" in the ZIP archive is damaged: its contents do not match its checksum. Download the archive again.',
            member: p.member,
          })
        : t('costs_pricelist.error_zip_member_corrupt', {
            defaultValue: 'A file in the ZIP archive is damaged: its contents do not match its checksum. Download the archive again.',
          }),
      text_encoding_unreadable: p.encoding
        ? t('costs_pricelist.error_text_encoding_unreadable', {
            defaultValue: 'The file is saved as {{encoding}} text, but its contents are not valid {{encoding}}. Save it again as UTF-8 or {{encoding}} and upload it.',
            encoding: p.encoding,
          })
        : t('costs_pricelist.error_text_encoding_unknown', {
            defaultValue: 'The file does not look like text in any encoding we read. Save the list as CSV (UTF-8) and upload it.',
          }),
      nothing_to_import: t('costs_pricelist.error_nothing_to_import', {
        defaultValue: 'The list holds no priced items to import.',
      }),
      import_failed: t('costs_pricelist.error_import_failed', {
        defaultValue: 'The import failed and was rolled back. Nothing was imported.',
      }),
      upload_not_found: t('costs_pricelist.error_upload_not_found', {
        defaultValue: 'The uploaded file is no longer on the server. Choose it again.',
      }),
    };
    // A reader's parse error (xpwe_not_well_formed, ...) carries the bill
    // import's code, worded under boq.import_error.<code>.
    return texts[error.code] ?? importFailureText(error, t, error.message);
  };
}

export function RegionalPriceListImport() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const errorText = useErrorText();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [progress, setProgress] = useState<PriceListProgress | null>(null);
  const [preview, setPreview] = useState<PriceListPreview | null>(null);
  const [overrides, setOverrides] = useState<PriceListOverrides>({});
  const [catalogName, setCatalogName] = useState('');
  const [result, setResult] = useState<PriceListImportResult | null>(null);

  const previewMutation = useMutation({
    // A new file is uploaded; a correction reads the upload the server already holds.
    mutationFn: async (args: { file: File | null; overrides: PriceListOverrides }) => {
      setProgress(null);
      if (args.file) {
        const stored = await uploadPriceList(args.file, args.overrides, setProgress);
        setUploadId(stored.uploadId);
        return stored.preview;
      }
      return repreviewPriceList(uploadId as string, args.overrides, setProgress);
    },
    onSuccess: (data) => {
      setPreview(data);
      setCatalogName((current) => current || data.source.suggested_catalog_name);
    },
    onSettled: () => setProgress(null),
  });

  const importMutation = useMutation({
    mutationFn: () => {
      setProgress(null);
      return importUploadedPriceList(uploadId as string, catalogName, overrides, preview?.counts.rows, setProgress);
    },
    onSettled: () => setProgress(null),
    onSuccess: (data) => {
      setResult(data);
      setPreview(null);
      setFile(null);
      setUploadId(null);
      queryClient.invalidateQueries({ queryKey: ['costs'] });
      addToast({
        type: 'success',
        title: t('costs_pricelist.imported_title', { defaultValue: 'Price list imported' }),
        message: t('costs_pricelist.imported_message', {
          defaultValue: '{{count}} items imported into "{{catalog}}".',
          count: data.imported,
          catalog: data.catalog,
        }),
      });
    },
  });

  const reset = () => {
    if (uploadId) void discardPriceListUpload(uploadId);
    setUploadId(null);
    setFile(null);
    setPreview(null);
    setOverrides({});
    setCatalogName('');
    previewMutation.reset();
    importMutation.reset();
    if (inputRef.current) inputRef.current.value = '';
  };

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const chosen = e.target.files?.[0];
    if (!chosen) return;
    if (uploadId) void discardPriceListUpload(uploadId);
    setUploadId(null);
    setResult(null);
    setFile(chosen);
    setPreview(null);
    setOverrides({});
    setCatalogName('');
    importMutation.reset();
    previewMutation.mutate({ file: chosen, overrides: {} });
  };

  const applyOverrides = (next: PriceListOverrides) => {
    setOverrides(next);
    setCatalogName('');
    if (uploadId) previewMutation.mutate({ file: null, overrides: next });
  };

  const number = (value: number) => value.toLocaleString(getNumberLocale());
  const money = (value: string | null) =>
    value === null
      ? '-'
      : Number(value).toLocaleString(getNumberLocale(), {
          style: 'currency',
          currency: 'EUR',
          minimumFractionDigits: 2,
          maximumFractionDigits: 5,
        });

  const warningText: Record<string, string> = {
    region_inferred: t('costs_pricelist.warning_region_inferred', {
      defaultValue: 'The region was recognised from the layout or the file name. Check it before importing.',
    }),
    region_not_detected: t('costs_pricelist.warning_region_not_detected', {
      defaultValue: 'The file does not say which region it is from. Choose the region below.',
    }),
    edition_not_detected: t('costs_pricelist.warning_edition_not_detected', {
      defaultValue: 'The file does not state its edition. Enter the year below.',
    }),
    licence_not_stated: t('costs_pricelist.warning_licence_not_stated', {
      defaultValue: "Neither the file nor the publisher's open-data record we know states a licence. Check the publisher's terms before sharing the data.",
    }),
    broken_numbers: t('costs_pricelist.warning_broken_numbers', {
      defaultValue:
        '{{count}} rows have a number whose decimal separator was lost (such as 15.403.443). Those values were left empty, never guessed.',
      count: preview?.counts.broken_rows ?? 0,
    }),
    duplicate_codes: t('costs_pricelist.warning_duplicate_codes', {
      defaultValue: '{{count}} codes appear more than once; only the first of each is imported.',
      count: preview?.counts.duplicates ?? 0,
    }),
    nothing_to_import: t('costs_pricelist.error_nothing_to_import', {
      defaultValue: 'The list holds no priced items to import.',
    }),
  };

  const skippedText: Record<string, string> = {
    same_list_other_format: t('costs_pricelist.skipped_same_list', {
      defaultValue: 'the same list in another format',
    }),
    analysis_table: t('costs_pricelist.skipped_analysis_table', { defaultValue: 'a table of price analyses' }),
    not_a_price_list_file: t('costs_pricelist.skipped_not_a_price_list', { defaultValue: 'not a price list file' }),
    format_not_recognised: t('costs_pricelist.skipped_format_not_recognised', {
      defaultValue: 'format not recognised',
    }),
  };

  const src = preview?.source;
  const licenceLine = !src?.licence
    ? t('costs_pricelist.licence_not_stated', { defaultValue: 'Licence: not stated' })
    : src.licence_stated_in === 'file'
      ? t('costs_pricelist.licence_from_file', {
          defaultValue: 'Licence: {{licence}} (stated in the file)',
          licence: src.licence,
        })
      : t('costs_pricelist.licence_from_catalogue', {
          defaultValue: "Licence: {{licence}} (stated in the publisher's open-data record)",
          licence: src.licence,
        });
  const needsRegion = !!preview && preview.warnings.some((w) => w === 'region_inferred' || w === 'region_not_detected');
  const importable = preview?.counts.importable ?? 0;
  const busy = previewMutation.isPending || importMutation.isPending;

  const readingText = t('costs_pricelist.reading_rows', {
    defaultValue: 'Reading the list... {{formatted}} rows read',
    count: progress?.rowsRead ?? 0,
    formatted: number(progress?.rowsRead ?? 0),
  });
  const importingText = !progress
    ? t('costs.import_importing', { defaultValue: 'Importing...' })
    : progress.percent > 0
      ? t('costs_pricelist.importing_percent', {
          defaultValue: 'Importing... {{percent}}%, {{formatted}} items written',
          percent: progress.percent,
          count: progress.imported,
          formatted: number(progress.imported),
        })
      : t('costs_pricelist.importing_rows', {
          defaultValue: 'Importing... {{formatted}} items written',
          count: progress.imported,
          formatted: number(progress.imported),
        });

  return (
    <Card className="mb-6" data-testid="regional-price-list-import">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle">
          <BookOpen size={20} className="text-oe-blue" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('costs_pricelist.title', { defaultValue: 'Import a regional price list' })}
          </h3>
          <p className="mt-1 text-sm text-content-secondary">
            {t('costs_pricelist.subtitle', {
              defaultValue:
                'Upload the prezzario an Italian region publishes (XML, CSV, XLSX, JSON, or the ZIP as downloaded), or a price list exported from estimating software as XPWE. You see what it holds before anything is imported.',
            })}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={onFile}
              data-testid="regional-price-list-file"
            />
            <Button
              variant="secondary"
              onClick={() => inputRef.current?.click()}
              disabled={busy}
              icon={previewMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
            >
              {previewMutation.isPending
                ? t('costs_pricelist.reading', { defaultValue: 'Reading the list...' })
                : t('costs_pricelist.choose_file', { defaultValue: 'Choose price list file' })}
            </Button>
            {file && <span className="truncate text-xs text-content-tertiary">{file.name}</span>}
          </div>

          {previewMutation.isPending && !!progress?.rowsRead && (
            <p className="mt-2 text-xs text-content-secondary" role="status" data-testid="regional-price-list-progress">
              {readingText}
            </p>
          )}

          {previewMutation.isError && (
            <p role="alert" className="mt-3 text-sm text-semantic-error">
              {errorText(previewMutation.error)}
            </p>
          )}

          {result && (
            <p className="mt-3 flex items-center gap-2 text-sm text-semantic-success">
              <CheckCircle2 size={16} />
              {t('costs_pricelist.imported_message', {
                defaultValue: '{{count}} items imported into "{{catalog}}".',
                count: result.imported,
                catalog: result.catalog,
              })}
            </p>
          )}

          {preview && src && (
            <div className="mt-4 space-y-4" data-testid="regional-price-list-preview">
              <div className="rounded-lg border border-border-light p-3 text-sm">
                <div className="font-medium text-content-primary">
                  {src.region_name
                    ? t('costs_pricelist.source_heading', {
                        defaultValue: '{{region}}, edition {{edition}}',
                        region: src.region_name,
                        edition: src.edition ?? '?',
                      })
                    : t('costs_pricelist.source_heading_unknown', {
                        defaultValue: 'Region not recognised, edition {{edition}}',
                        edition: src.edition ?? '?',
                      })}
                  {src.area ? ` · ${src.area}` : ''}
                </div>
                <div className="mt-1 text-xs text-content-secondary">{licenceLine}</div>
                <div className="mt-0.5 text-xs text-content-tertiary">
                  {t('costs_pricelist.attribution', {
                    defaultValue: 'Source: {{attribution}}',
                    attribution: src.attribution,
                  })}
                </div>
                <div className="mt-2 text-sm text-content-primary">
                  {t('costs_pricelist.counts', {
                    defaultValue: '{{importable}} priced items in {{chapters}} chapters',
                    importable: number(importable),
                    chapters: number(preview.chapter_count),
                  })}
                  {preview.counts.with_analysis > 0 &&
                    ` · ${t('costs_pricelist.with_analysis', {
                      defaultValue: '{{count}} with a price analysis',
                      count: preview.counts.with_analysis,
                    })}`}
                  {preview.counts.with_labour_share > 0 &&
                    ` · ${t('costs_pricelist.with_labour', {
                      defaultValue: '{{count}} state their labour share',
                      count: preview.counts.with_labour_share,
                    })}`}
                </div>
                {Object.entries(preview.counts.skipped).length > 0 && (
                  <div className="mt-1 text-xs text-content-tertiary">
                    {t('costs_pricelist.not_imported', {
                      defaultValue: 'Not imported: {{count}} rows without a usable price',
                      count: Object.values(preview.counts.skipped).reduce((a, b) => a + b, 0),
                    })}
                  </div>
                )}
              </div>

              {preview.warnings.length > 0 && (
                <ul className="space-y-1">
                  {preview.warnings.map((w) => (
                    <li key={w} className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-300">
                      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                      <span>{warningText[w] ?? w}</span>
                    </li>
                  ))}
                </ul>
              )}

              {(needsRegion || !src.edition) && (
                <div className="flex flex-wrap items-end gap-3">
                  <label className="text-xs text-content-secondary">
                    {t('costs_pricelist.region_label', { defaultValue: 'Region' })}
                    <select
                      className="mt-1 block rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm"
                      value={overrides.regionCode ?? src.region_code ?? ''}
                      onChange={(e) => applyOverrides({ ...overrides, regionCode: e.target.value || undefined })}
                      disabled={busy}
                    >
                      <option value="">{t('costs_pricelist.region_choose', { defaultValue: 'Choose...' })}</option>
                      {PRICE_LIST_REGIONS.map((r) => (
                        <option key={r.code} value={r.code}>
                          {r.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-content-secondary">
                    {t('costs_pricelist.edition_label', { defaultValue: 'Edition (year)' })}
                    <input
                      key={src.edition ?? 'none'}
                      className="mt-1 block w-24 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm"
                      inputMode="numeric"
                      defaultValue={overrides.edition ?? src.edition ?? ''}
                      onBlur={(e) => {
                        const value = e.target.value.trim();
                        if (value !== (overrides.edition ?? src.edition ?? '')) {
                          applyOverrides({ ...overrides, edition: value || undefined });
                        }
                      }}
                      disabled={busy}
                    />
                  </label>
                </div>
              )}

              {preview.chapters.length > 0 && (
                <div>
                  <div className="text-xs font-medium text-content-secondary">
                    {t('costs_pricelist.chapters', { defaultValue: 'Chapters' })}
                  </div>
                  <ul className="mt-1 grid gap-x-4 text-xs text-content-tertiary sm:grid-cols-2">
                    {preview.chapters.slice(0, 8).map((c) => (
                      <li key={`${c.code}-${c.title}`} className="truncate">
                        {c.code ? `${c.code} ` : ''}
                        {c.title} ({number(c.count)})
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {preview.sample_rows.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="text-content-secondary">
                      <tr>
                        <th className="py-1 pe-2 font-medium">{t('costs_pricelist.col_code', { defaultValue: 'Code' })}</th>
                        <th className="py-1 pe-2 font-medium">
                          {t('costs_pricelist.col_description', { defaultValue: 'Description' })}
                        </th>
                        <th className="py-1 pe-2 font-medium">{t('costs_pricelist.col_unit', { defaultValue: 'Unit' })}</th>
                        <th className="py-1 text-end font-medium">
                          {t('costs_pricelist.col_rate', { defaultValue: 'Price' })}
                        </th>
                      </tr>
                    </thead>
                    <tbody className="text-content-primary">
                      {preview.sample_rows.map((row) => (
                        <tr key={row.code} className="border-t border-border-light">
                          <td className="py-1 pe-2 font-mono whitespace-nowrap">{row.code}</td>
                          <td className="max-w-md truncate py-1 pe-2" title={row.description}>
                            {row.description}
                          </td>
                          <td className="py-1 pe-2 whitespace-nowrap">{row.source_unit || row.unit}</td>
                          <td className="py-1 text-end tabular-nums whitespace-nowrap">{money(row.rate)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {preview.skipped_files.length > 0 && (
                <ul className="text-xs text-content-tertiary">
                  {preview.skipped_files.map((s) => (
                    <li key={s.name}>
                      {t('costs_pricelist.skipped_file', {
                        defaultValue: 'Left out: {{name}} ({{reason}})',
                        name: s.name,
                        reason: skippedText[s.reason] ?? s.reason,
                      })}
                    </li>
                  ))}
                </ul>
              )}

              <div className="flex flex-wrap items-end gap-3">
                <label className="min-w-[16rem] flex-1 text-xs text-content-secondary">
                  {t('costs_pricelist.catalog_name', { defaultValue: 'New catalogue name' })}
                  <input
                    className="mt-1 block w-full rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm"
                    value={catalogName}
                    maxLength={50}
                    onChange={(e) => setCatalogName(e.target.value)}
                    disabled={busy}
                  />
                </label>
                <Button variant="secondary" onClick={reset} disabled={importMutation.isPending}>
                  {t('common.cancel', { defaultValue: 'Cancel' })}
                </Button>
                <Button
                  variant="primary"
                  onClick={() => importMutation.mutate()}
                  disabled={busy || importable === 0 || !catalogName.trim() || (needsRegion && !overrides.regionCode && !src.region_code)}
                  icon={importMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                >
                  {importMutation.isPending
                    ? t('costs.import_importing', { defaultValue: 'Importing...' })
                    : t('costs_pricelist.import_button', {
                        defaultValue: 'Import {{count}} items',
                        count: importable,
                      })}
                </Button>
              </div>
              {importMutation.isPending && (
                <div role="status" className="space-y-1" data-testid="regional-price-list-import-progress">
                  {progress && progress.percent > 0 && (
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
                      <div className="h-full rounded-full bg-oe-blue" style={{ width: `${progress.percent}%` }} />
                    </div>
                  )}
                  <p className="text-xs text-content-secondary">{importingText}</p>
                </div>
              )}
              {importMutation.isError && (
                <p role="alert" className="text-sm text-semantic-error">
                  {errorText(importMutation.error)}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
