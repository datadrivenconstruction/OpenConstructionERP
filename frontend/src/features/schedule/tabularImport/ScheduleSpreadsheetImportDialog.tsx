// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Import a schedule from an Excel workbook or a CSV file.
 *
 * Flow: pick a file (or download a template first) -> the server reads it and
 * writes nothing -> the person checks the column mapping, confirms the date
 * order when the file leaves it open, reads the problems row by row and ticks
 * what the client may see -> import as a new schedule, or into the draft the
 * dialog was opened from. The commit re-sends the same file with the preview's
 * SHA-256, so what is written is exactly what was reviewed.
 *
 * Refusals come back with a stable `detail.code`: a second import of the same
 * file offers to import it again on purpose, and errors found at commit time
 * are listed per row like the preview's.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Copy, Download, FileSpreadsheet, Loader2, Upload, XCircle } from 'lucide-react';

import { Badge, Button, Input, WideModal, WideModalSection } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { changedColumns, chooseColumn, type ColumnMapping } from '@/features/boq/columnMappingOverride';
import { ClientMilestonePicker } from './ClientMilestonePicker';
import { ColumnMappingTable } from './ColumnMappingTable';
import { DateOrderChoice } from './DateOrderChoice';
import { ImportIssuesList } from './ImportIssuesList';
import { errorText } from './labels';
import {
  TEMPLATE_LANGUAGES,
  commitSpreadsheet,
  downloadTemplate,
  importErrorDetail,
  previewSpreadsheet,
  readMapping,
  templateLanguageFor,
  type DateOrder,
  type ImportIssue,
  type TabularCommitResult,
  type TabularPreview,
  type TemplateFormat,
  type TemplateLanguage,
} from './tabularImport';

const ACCEPT = '.xlsx,.xls,.csv,.txt,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,text/csv';

export interface ScheduleSpreadsheetImportDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  /** The schedule the dialog was opened from; a draft can have its contents replaced. */
  schedule?: { id: string; name: string; status: string } | null;
  /** Called once the import is written, to refresh whatever lists it. */
  onImported?: (result: TabularCommitResult) => void;
  /** Offered as "Open schedule" on the result; omitted, the result only closes. */
  onOpenSchedule?: (result: TabularCommitResult) => void;
  /** Where the import goes unless the person picks otherwise; "replace" applies to a draft only. */
  defaultTarget?: 'new' | 'replace';
}

interface PreviewArgs {
  file: File;
  chosen: ColumnMapping;
  read: ColumnMapping;
  dateOrder: DateOrder | null;
  fresh: boolean;
}

function mappingField(read: ColumnMapping, chosen: ColumnMapping): string | null {
  const changed = changedColumns(read, chosen);
  return Object.keys(changed).length > 0 ? JSON.stringify(changed) : null;
}

function languageName(code: string, uiLanguage: string): string {
  try {
    const names = new Intl.DisplayNames([uiLanguage || 'en'], { type: 'language' });
    return names.of(code) ?? code;
  } catch {
    return code;
  }
}

export function ScheduleSpreadsheetImportDialog({
  open,
  onClose,
  projectId,
  schedule = null,
  onImported,
  onOpenSchedule,
  defaultTarget = 'new',
}: ScheduleSpreadsheetImportDialogProps) {
  const { t, i18n } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<TabularPreview | null>(null);
  const [read, setRead] = useState<ColumnMapping>({});
  const [chosen, setChosen] = useState<ColumnMapping>({});
  const [dateOrder, setDateOrder] = useState<DateOrder | null>(null);
  const [visible, setVisible] = useState<Set<string>>(new Set());
  const canReplace = schedule !== null && (schedule.status || 'draft') === 'draft';
  const initialTarget = defaultTarget === 'replace' && canReplace ? 'replace' : 'new';
  const [target, setTarget] = useState<'new' | 'replace'>(initialTarget);
  const [name, setName] = useState('');
  const [allowDuplicate, setAllowDuplicate] = useState(false);
  const [duplicateRefused, setDuplicateRefused] = useState(false);
  const [commitIssues, setCommitIssues] = useState<ImportIssue[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TabularCommitResult | null>(null);
  const [templateLang, setTemplateLang] = useState<TemplateLanguage>(() => templateLanguageFor(i18n.language));
  const [templateBusy, setTemplateBusy] = useState<TemplateFormat | null>(null);
  // A later preview supersedes an earlier one still in flight.
  const previewSeq = useRef(0);

  const reset = () => {
    setFile(null);
    setPreview(null);
    setRead({});
    setChosen({});
    setDateOrder(null);
    setVisible(new Set());
    setTarget(initialTarget);
    setName('');
    setAllowDuplicate(false);
    setDuplicateRefused(false);
    setCommitIssues([]);
    setError(null);
    setResult(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  useEffect(() => {
    if (!open) reset();
  }, [open]);

  const previewMut = useMutation({
    mutationFn: async (args: PreviewArgs) => {
      const seq = ++previewSeq.current;
      const answer = await previewSpreadsheet({
        projectId,
        file: args.file,
        columnMapping: args.fresh ? null : mappingField(args.read, args.chosen),
        dateOrder: args.dateOrder,
      });
      return { answer, seq, fresh: args.fresh };
    },
    onSuccess: ({ answer, seq, fresh }) => {
      if (seq !== previewSeq.current) return;
      setPreview(answer);
      setCommitIssues([]);
      setError(null);
      const refs = new Set((answer.document?.activities ?? []).map((a) => a.ref));
      if (fresh) {
        const proposal = readMapping(answer.columns);
        setRead(proposal);
        setChosen(proposal);
        setVisible(new Set());
      } else {
        setVisible((current) => new Set([...current].filter((ref) => refs.has(ref))));
      }
    },
    onError: (err) => {
      const detail = importErrorDetail(err);
      setError(detail ? errorText(t, detail) : getErrorMessage(err));
    },
  });

  const commitMut = useMutation({
    mutationFn: (allow: boolean) => {
      if (!file || !preview) throw new Error('nothing to import');
      return commitSpreadsheet({
        projectId,
        file,
        columnMapping: mappingField(read, chosen),
        dateOrder,
        expectedSha256: preview.sha256,
        target,
        scheduleId: target === 'replace' ? schedule?.id : null,
        name: target === 'new' ? name : null,
        allowDuplicate: allow,
        clientVisibleRefs: [...visible],
      });
    },
    onSuccess: (answer) => {
      setResult(answer);
      setError(null);
      setCommitIssues([]);
      onImported?.(answer);
    },
    onError: (err) => {
      const detail = importErrorDetail(err);
      setCommitIssues([]);
      if (detail?.code === 'duplicate_import') {
        setDuplicateRefused(true);
        setAllowDuplicate(false);
        setError(null);
        return;
      }
      if (detail?.code === 'import_has_errors') {
        setCommitIssues(detail.issues ?? []);
        setError(errorText(t, detail));
        return;
      }
      setError(detail ? errorText(t, detail) : getErrorMessage(err));
    },
  });

  const busy = previewMut.isPending || commitMut.isPending;

  const pickFile = (next: File | undefined) => {
    if (!next) return;
    reset();
    setFile(next);
    previewMut.mutate({ file: next, read: {}, chosen: {}, dateOrder: null, fresh: true });
  };

  const choose = (column: string, field: string) => {
    if (!file) return;
    const next = chooseColumn(read, chosen, column, field);
    setChosen(next);
    previewMut.mutate({ file, read, chosen: next, dateOrder, fresh: false });
  };

  const pickDateOrder = (order: DateOrder) => {
    if (!file) return;
    setDateOrder(order);
    previewMut.mutate({ file, read, chosen, dateOrder: order, fresh: false });
  };

  const getTemplate = async (format: TemplateFormat) => {
    setTemplateBusy(format);
    try {
      await downloadTemplate(templateLang, format);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setTemplateBusy(null);
    }
  };

  const unconfirmed = preview?.issues.find((issue) => issue.code === 'date_order_unconfirmed') ?? null;
  const dateExample = useMemo(() => {
    const fromIssue = unconfirmed?.params?.example;
    if (typeof fromIssue === 'string') return fromIssue;
    const detected = preview?.issues.find((issue) => issue.code === 'date_order_detected')?.params?.example;
    return typeof detected === 'string' ? detected : null;
  }, [preview, unconfirmed]);
  const suggestedOrder = (unconfirmed?.params?.suggested as DateOrder | undefined) ?? preview?.date_order ?? null;
  const showDateOrder = preview !== null && (preview.date_order !== null || dateOrder !== null);
  const duplicates = preview?.duplicate_of ?? [];
  const showDuplicate = duplicateRefused || duplicates.length > 0;
  const parsed = preview?.document ?? null;
  const canCommit =
    preview !== null &&
    parsed !== null &&
    !preview.has_errors &&
    !busy &&
    !(showDuplicate && !allowDuplicate);

  const title = t('schedule.tabular_import.title', { defaultValue: 'Import a schedule from Excel or CSV' });

  // ── Result ──────────────────────────────────────────────────────────────
  if (result) {
    const findings = result.validation.findings.slice(0, 10);
    return (
      <WideModal
        open={open}
        onClose={onClose}
        title={title}
        size="lg"
        testId="tabular-import-dialog"
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              {t('common.close', { defaultValue: 'Close' })}
            </Button>
            {onOpenSchedule && (
              <Button variant="primary" onClick={() => onOpenSchedule(result)}>
                {t('schedule.tabular_import.open_schedule', { defaultValue: 'Open schedule' })}
              </Button>
            )}
          </>
        }
      >
        <div className="space-y-4" data-testid="tabular-import-result">
          <div className="flex items-start gap-2">
            <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-semantic-success" />
            <div>
              <p className="text-sm font-semibold text-content-primary">
                {result.replaced
                  ? t('schedule.tabular_import.done_replaced', {
                      defaultValue: 'The contents of "{{name}}" were replaced',
                      name: result.schedule_name,
                    })
                  : t('schedule.tabular_import.done_created', {
                      defaultValue: 'Schedule "{{name}}" was created',
                      name: result.schedule_name,
                    })}
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge variant="success">
                  {t('schedule.tabular_import.n_activities', {
                    count: result.activity_count,
                    defaultValue_one: '{{count}} activity',
                    defaultValue_other: '{{count}} activities',
                  })}
                </Badge>
                <Badge variant="blue">
                  {t('schedule.tabular_import.n_links', {
                    count: result.relationship_count,
                    defaultValue_one: '{{count}} link',
                    defaultValue_other: '{{count}} links',
                  })}
                </Badge>
                <Badge variant="neutral">
                  {t('schedule.tabular_import.n_critical', {
                    count: result.critical_count,
                    defaultValue_one: '{{count}} critical activity',
                    defaultValue_other: '{{count}} critical activities',
                  })}
                </Badge>
                <Badge variant="neutral">
                  {t('schedule.tabular_import.n_duration', {
                    count: result.project_duration_days,
                    defaultValue_one: '{{count}} working day overall',
                    defaultValue_other: '{{count}} working days overall',
                  })}
                </Badge>
              </div>
            </div>
          </div>

          <WideModalSection
            title={t('schedule.tabular_import.quality_title', { defaultValue: 'Schedule quality check' })}
            columns={1}
          >
            {result.validation.findings.length === 0 ? (
              <p className="text-xs text-content-secondary">
                {t('schedule.tabular_import.quality_clean', { defaultValue: 'The quality check found nothing to fix.' })}
              </p>
            ) : (
              <ul className="space-y-1 text-xs">
                {findings.map((finding, index) => (
                  <li key={`${finding.rule_id}-${index}`} className="text-content-secondary">
                    {finding.row
                      ? t('schedule.tabular_import.quality_finding_row', {
                          defaultValue: 'Row {{row}}: {{message}}',
                          row: finding.row,
                          message: finding.message,
                        })
                      : finding.message}
                  </li>
                ))}
                {result.validation.findings.length > findings.length && (
                  <li className="text-content-tertiary">
                    {t('schedule.tabular_import.quality_more', {
                      count: result.validation.findings.length - findings.length,
                      defaultValue_one: 'and {{count}} more finding',
                      defaultValue_other: 'and {{count}} more findings',
                    })}
                  </li>
                )}
              </ul>
            )}
          </WideModalSection>

          {result.warnings.length > 0 && (
            <WideModalSection
              title={t('schedule.tabular_import.warnings_title', { defaultValue: 'Read with warnings' })}
              columns={1}
            >
              <ImportIssuesList issues={result.warnings} columns={preview?.columns} />
            </WideModalSection>
          )}
        </div>
      </WideModal>
    );
  }

  // ── Upload and review ───────────────────────────────────────────────────
  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={title}
      subtitle={t('schedule.tabular_import.subtitle', {
        defaultValue:
          'One row per activity: an ID, a name, dates or a duration, and predecessors such as "A10FS+2d". Nothing is written until you import.',
      })}
      size="xl"
      busy={commitMut.isPending}
      testId="tabular-import-dialog"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={commitMut.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {preview && (
            <Button
              variant="primary"
              onClick={() => commitMut.mutate(allowDuplicate)}
              disabled={!canCommit}
              loading={commitMut.isPending}
              icon={<Upload size={16} />}
            >
              {target === 'replace'
                ? t('schedule.tabular_import.import_replace', { defaultValue: 'Replace contents' })
                : t('schedule.tabular_import.import_new', { defaultValue: 'Import' })}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-5">
        {/* File and template */}
        <WideModalSection columns={2}>
          <div>
            <label
              htmlFor="tabular-import-file"
              className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-secondary"
            >
              {t('schedule.tabular_import.file_label', { defaultValue: 'Spreadsheet (.xlsx, .xls or .csv)' })}
            </label>
            <input
              ref={fileInputRef}
              id="tabular-import-file"
              type="file"
              accept={ACCEPT}
              disabled={busy}
              onChange={(e) => pickFile(e.target.files?.[0])}
              className="block w-full text-sm text-content-secondary file:mr-3 file:cursor-pointer file:rounded-lg file:border-0 file:bg-surface-secondary file:px-3 file:py-2 file:text-sm file:font-medium file:text-content-primary hover:file:bg-surface-secondary/70"
            />
            {file && (
              <span className="mt-1.5 inline-flex items-center gap-1.5 text-xs text-content-secondary">
                <FileSpreadsheet size={13} className="text-oe-blue" />
                {file.name}
              </span>
            )}
          </div>
          <div>
            <label
              htmlFor="tabular-template-lang"
              className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-secondary"
            >
              {t('schedule.tabular_import.template_label', { defaultValue: 'Start from a template' })}
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <select
                id="tabular-template-lang"
                value={templateLang}
                onChange={(e) => setTemplateLang(e.target.value as TemplateLanguage)}
                className="rounded-md border border-border bg-surface-primary px-2 py-1.5 text-xs text-content-primary"
              >
                {TEMPLATE_LANGUAGES.map((code) => (
                  <option key={code} value={code}>
                    {languageName(code, i18n.language)}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="secondary"
                icon={templateBusy === 'xlsx' ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                disabled={templateBusy !== null}
                onClick={() => getTemplate('xlsx')}
              >
                {t('schedule.tabular_import.template_xlsx', { defaultValue: 'Excel template' })}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                icon={<Download size={14} />}
                disabled={templateBusy !== null}
                onClick={() => getTemplate('csv')}
              >
                {t('schedule.tabular_import.template_csv', { defaultValue: 'CSV template' })}
              </Button>
            </div>
          </div>
        </WideModalSection>

        {previewMut.isPending && (
          <p className="flex items-center gap-2 text-xs text-content-secondary" role="status">
            <Loader2 size={14} className="animate-spin" />
            {t('schedule.tabular_import.reading', { defaultValue: 'Reading the file...' })}
          </p>
        )}

        {error && (
          <div
            className="flex items-start gap-2 rounded-lg border border-semantic-error/40 bg-semantic-error-bg/40 px-3 py-2 text-xs text-content-primary"
            role="alert"
          >
            <XCircle size={14} className="mt-0.5 shrink-0 text-semantic-error" />
            <span>{error}</span>
          </div>
        )}

        {commitIssues.length > 0 && (
          <WideModalSection
            title={t('schedule.tabular_import.commit_errors_title', {
              defaultValue: 'Fix these rows in the file, then choose it again',
            })}
            columns={1}
          >
            <ImportIssuesList issues={commitIssues} columns={preview?.columns} hideInfo testId="tabular-commit-issues" />
          </WideModalSection>
        )}

        {preview && (
          <>
            {/* What was read */}
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-content-secondary">
              <Badge variant="blue">
                {t('schedule.tabular_import.n_activities', {
                  count: preview.activity_count,
                  defaultValue_one: '{{count}} activity',
                  defaultValue_other: '{{count}} activities',
                })}
              </Badge>
              <Badge variant="neutral">
                {t('schedule.tabular_import.n_links', {
                  count: preview.relationship_count,
                  defaultValue_one: '{{count}} link',
                  defaultValue_other: '{{count}} links',
                })}
              </Badge>
              {preview.sheet && (
                <span>
                  {t('schedule.tabular_import.read_sheet', { defaultValue: 'Sheet "{{sheet}}"', sheet: preview.sheet })}
                </span>
              )}
              {preview.header_row && (
                <span>
                  {t('schedule.tabular_import.read_header_row', {
                    defaultValue: 'Headers on row {{row}}',
                    row: preview.header_row,
                  })}
                </span>
              )}
              {preview.encoding && preview.file_format === 'csv' && (
                <span>
                  {t('schedule.tabular_import.read_encoding', {
                    defaultValue: 'Text encoding {{encoding}}',
                    encoding: preview.encoding,
                  })}
                </span>
              )}
            </div>

            {showDuplicate && (
              <div
                className="flex items-start gap-2 rounded-lg border border-semantic-warning bg-semantic-warning-bg/40 px-3 py-2 text-xs"
                data-testid="tabular-duplicate"
              >
                <Copy size={14} className="mt-0.5 shrink-0 text-semantic-warning" />
                <div className="space-y-1.5">
                  <p className="text-content-primary">
                    {t('schedule.tabular_import.duplicate_desc', {
                      defaultValue: 'This exact file was already imported into the project. Importing it again creates a second copy.',
                    })}
                  </p>
                  <label className="flex cursor-pointer items-center gap-2 font-medium text-content-primary">
                    <input
                      type="checkbox"
                      checked={allowDuplicate}
                      onChange={(e) => setAllowDuplicate(e.target.checked)}
                      className="h-3.5 w-3.5 accent-oe-blue"
                    />
                    {t('schedule.tabular_import.duplicate_allow', { defaultValue: 'Import it again anyway' })}
                  </label>
                </div>
              </div>
            )}

            <WideModalSection
              title={t('schedule.tabular_import.mapping_title', { defaultValue: 'Columns' })}
              description={t('schedule.tabular_import.mapping_desc', {
                defaultValue: 'Check what each column is read as. Change any that are wrong; the file is read again at once.',
              })}
              columns={1}
            >
              <ColumnMappingTable
                columns={preview.columns}
                chosen={chosen}
                onChoose={choose}
                sample={preview.sample_rows[0]?.values}
                disabled={busy}
              />
            </WideModalSection>

            {showDateOrder && (
              <DateOrderChoice
                value={dateOrder}
                onChange={pickDateOrder}
                suggested={suggestedOrder}
                suggestedBy={(unconfirmed?.params?.suggested_by as string | undefined) ?? null}
                example={dateExample}
                required={unconfirmed !== null}
                disabled={busy}
              />
            )}

            <WideModalSection
              title={t('schedule.tabular_import.issues_title', { defaultValue: 'Problems in the file' })}
              columns={1}
            >
              <ImportIssuesList issues={preview.issues} columns={preview.columns} testId="tabular-preview-issues" />
            </WideModalSection>

            {parsed && parsed.activities.length > 0 && (
              <WideModalSection
                title={t('schedule.tabular_import.client_title', { defaultValue: 'Visible to the client' })}
                columns={1}
              >
                <ClientMilestonePicker
                  activities={parsed.activities}
                  suggested={preview.client_visible_suggested}
                  selected={visible}
                  onChange={setVisible}
                  disabled={commitMut.isPending}
                />
              </WideModalSection>
            )}

            <WideModalSection
              title={t('schedule.tabular_import.target_title', { defaultValue: 'Import into' })}
              columns={1}
            >
              <div className="space-y-2 text-xs">
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="radio"
                    name="tabular-target"
                    checked={target === 'new'}
                    onChange={() => setTarget('new')}
                    className="accent-oe-blue"
                  />
                  <span className="font-medium text-content-primary">
                    {t('schedule.tabular_import.target_new', { defaultValue: 'A new schedule' })}
                  </span>
                </label>
                {target === 'new' && (
                  <div className="pl-6">
                    <Input
                      label={t('schedule.tabular_import.name_label', { defaultValue: 'Schedule name' })}
                      placeholder={parsed?.schedule.name ?? ''}
                      value={name}
                      maxLength={255}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </div>
                )}
                {schedule && (
                  <label
                    className={canReplace ? 'flex cursor-pointer items-start gap-2' : 'flex items-start gap-2 opacity-60'}
                  >
                    <input
                      type="radio"
                      name="tabular-target"
                      checked={target === 'replace'}
                      disabled={!canReplace}
                      onChange={() => setTarget('replace')}
                      className="mt-0.5 accent-oe-blue"
                    />
                    <span>
                      <span className="block font-medium text-content-primary">
                        {t('schedule.tabular_import.target_replace', {
                          defaultValue: 'Replace the contents of "{{name}}"',
                          name: schedule.name,
                        })}
                      </span>
                      <span className="block text-content-tertiary">
                        {canReplace
                          ? t('schedule.tabular_import.target_replace_hint', {
                              defaultValue:
                                'Only a draft without a baseline, recorded progress or work orders can be replaced. Its activities and links are deleted.',
                            })
                          : t('schedule.tabular_import.target_replace_not_draft', {
                              defaultValue: 'Only a draft schedule can be replaced.',
                            })}
                      </span>
                    </span>
                  </label>
                )}
              </div>
            </WideModalSection>
          </>
        )}
      </div>
    </WideModal>
  );
}

export default ScheduleSpreadsheetImportDialog;
