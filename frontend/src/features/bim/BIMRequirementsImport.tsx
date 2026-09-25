// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BIMRequirementsImport -- import/export panel for BIM requirement files.
 *
 * Supports: IDS XML, COBie Excel, generic Excel/CSV, Revit Shared Parameters,
 * BIMQ JSON. Auto-detects format on upload. Shows imported sets with
 * expand/collapse and export buttons.
 */

import { useCallback, useRef, useState, type DragEvent, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Upload,
  Download,
  FileSpreadsheet,
  FileCode,
  Trash2,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  AlertCircle,
  Loader2,
  CheckCircle2,
  ShieldCheck,
  XCircle,
  MinusCircle,
} from 'lucide-react';
import clsx from 'clsx';

import { fmtList } from '@/shared/lib/formatters';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  importBIMRequirements,
  fetchBIMRequirementSets,
  fetchBIMRequirementSetDetail,
  deleteBIMRequirementSet,
  downloadBIMRequirementsTemplate,
  exportBIMRequirementSetExcel,
  exportBIMRequirementSetIds,
  fetchBIMModels,
  validateBIMRequirementSet,
  type BIMRequirementSetResponse,
  type BIMRequirementImportResult,
  type BIMRequirementValidationResult,
} from './api';

const ACCEPTED_EXTENSIONS = '.ids,.xml,.xlsx,.xls,.csv,.txt,.json';

/* ── Main component ──────────────────────────────────────────────────── */

export default function BIMRequirementsImport() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [importResult, setImportResult] = useState<BIMRequirementImportResult | null>(null);
  const [expandedSet, setExpandedSet] = useState<string | null>(null);

  // Fetch existing sets
  const { data: sets = [], isLoading: setsLoading } = useQuery({
    queryKey: ['bim-requirement-sets', projectId],
    queryFn: () => (projectId ? fetchBIMRequirementSets(projectId) : Promise.resolve([])),
    enabled: !!projectId,
  });

  // Import mutation
  const importMutation = useMutation({
    mutationFn: (file: File) =>
      importBIMRequirements(projectId!, file),
    onSuccess: (result) => {
      setImportResult(result);
      addToast({
        type: 'success',
        title: t('bim.requirements.importSuccessTitle', { defaultValue: 'Import complete' }),
        message: t('bim.requirements.importSuccess', {
          defaultValue: `Imported {{count}} requirements ({{format}})`,
          count: result.total_requirements,
          format: result.source_format,
        }),
      });
      queryClient.invalidateQueries({ queryKey: ['bim-requirement-sets'] });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (setId: string) => deleteBIMRequirementSet(setId),
    onSuccess: () => {
      addToast({ type: 'success', title: t('bim.requirements.deletedTitle', { defaultValue: 'Deleted' }), message: t('bim.requirements.deleted', { defaultValue: 'Requirement set deleted' }) });
      queryClient.invalidateQueries({ queryKey: ['bim-requirement-sets'] });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  // Template download mutation — fetches the Excel template blob with the
  // Bearer token (a bare <a href> to this auth-guarded GET endpoint 401s).
  const templateMutation = useMutation({
    mutationFn: () => downloadBIMRequirementsTemplate(),
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  // Drag and drop handlers
  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => setIsDragging(false), []);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) {
        setImportResult(null);
        importMutation.mutate(file);
      }
    },
    [importMutation],
  );

  const handleFileChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        setImportResult(null);
        importMutation.mutate(file);
      }
      // Reset input so the same file can be selected again
      e.target.value = '';
    },
    [importMutation],
  );

  if (!projectId) {
    return (
      <div className="text-sm text-zinc-500 dark:text-zinc-400 p-4">
        {t('bim.requirements.noProject', { defaultValue: 'Select a project first' })}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Upload zone ──────────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-semibold mb-2 text-zinc-700 dark:text-zinc-200">
          {t('bim.requirements.importTitle', { defaultValue: 'Import BIM Requirements' })}
        </h3>

        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={clsx(
            'border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors',
            isDragging
              ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
              : 'border-zinc-300 dark:border-zinc-600 hover:border-blue-400',
          )}
        >
          {importMutation.isPending ? (
            <div className="flex flex-col items-center gap-2">
              <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
              <span className="text-sm text-zinc-500">
                {t('bim.requirements.importing', { defaultValue: 'Importing...' })}
              </span>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <Upload className="w-8 h-8 text-zinc-400" />
              <span className="text-sm text-zinc-600 dark:text-zinc-300">
                {t('bim.requirements.dropzone', {
                  defaultValue: 'Drop a file here or click to browse',
                })}
              </span>
              <span className="text-xs text-zinc-400">
                {t('bim.requirements.formats', {
                  defaultValue: 'IDS XML, COBie Excel, Excel/CSV, RVT shared-parameter (.txt), BIMQ JSON',
                })}
              </span>
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS}
            onChange={handleFileChange}
            className="hidden"
          />
        </div>

        {/* Download template button */}
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={() => templateMutation.mutate()}
            disabled={templateMutation.isPending}
            title={t('bim_requirements.downloadTemplateHint', {
              defaultValue:
                'Download a blank Excel workbook with the expected columns to fill in and re-import.',
            })}
            className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 disabled:opacity-50"
          >
            {templateMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Download className="w-3.5 h-3.5" />
            )}
            {t('bim.requirements.downloadTemplate', { defaultValue: 'Download Excel template' })}
          </button>
        </div>
      </div>

      {/* ── Import result ────────────────────────────────────────── */}
      {importResult && (
        <ImportResultBanner result={importResult} onDismiss={() => setImportResult(null)} />
      )}

      {/* ── Imported sets ────────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-semibold mb-2 text-zinc-700 dark:text-zinc-200">
          {t('bim.requirements.importedSets', { defaultValue: 'Imported Requirement Sets' })}
          {sets.length > 0 && (
            <span className="ml-1 text-zinc-400 font-normal">({sets.length})</span>
          )}
        </h3>

        {setsLoading ? (
          <div className="text-sm text-zinc-400 flex items-center gap-1">
            <Loader2 className="w-4 h-4 animate-spin" />
            {t('common.loading', { defaultValue: 'Loading...' })}
          </div>
        ) : sets.length === 0 ? (
          <div className="rounded-lg border border-dashed border-zinc-200 dark:border-zinc-700 p-4 text-center">
            <p className="text-sm text-zinc-400">
              {t('bim.requirements.noSets', { defaultValue: 'No requirement sets imported yet.' })}
            </p>
            <p className="mt-1 text-xs text-zinc-400">
              {t('bim_requirements.noSetsHint', {
                defaultValue:
                  'Import an IDS, COBie, Excel/CSV, RVT shared-parameter or BIMQ file above, then export it or validate a BIM model against it here.',
              })}
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {sets.map((s) => (
              <RequirementSetCard
                key={s.id}
                set={s}
                projectId={projectId}
                isExpanded={expandedSet === s.id}
                onToggle={() => setExpandedSet(expandedSet === s.id ? null : s.id)}
                onDelete={() => deleteMutation.mutate(s.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Import result banner ──────────────────────────────────────────── */

function ImportResultBanner({
  result,
  onDismiss,
}: {
  result: BIMRequirementImportResult;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/20 p-4">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-green-600" />
          <span className="text-sm font-medium text-green-800 dark:text-green-200">
            {t('bim.requirements.importedCount', {
              defaultValue: 'Imported {{count}} requirements',
              count: result.total_requirements,
            })}
          </span>
          <span className="text-xs text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-800 px-1.5 py-0.5 rounded">
            {result.source_format}
          </span>
        </div>
        <button onClick={onDismiss} className="text-zinc-400 hover:text-zinc-600 text-sm">
          x
        </button>
      </div>

      {result.warnings.length > 0 && (
        <div className="mt-2 text-xs text-amber-700 dark:text-amber-300">
          <div className="flex items-center gap-1 font-medium">
            <AlertTriangle className="w-3.5 h-3.5" />
            {t('bim.requirements.warnings_count', {
              count: result.warnings.length,
              defaultValue_one: '{{count}} warning',
              defaultValue: '{{count}} warnings',
            })}
          </div>
          {result.warnings.slice(0, 3).map((w, i) => (
            <div key={`warn-${(w.msg ?? '').slice(0, 30)}-${i}`} className="ml-5 mt-0.5">
              {w.msg}
            </div>
          ))}
        </div>
      )}

      {result.errors.length > 0 && (
        <div className="mt-2 text-xs text-red-700 dark:text-red-300">
          <div className="flex items-center gap-1 font-medium">
            <AlertCircle className="w-3.5 h-3.5" />
            {result.errors.length} {t('bim.requirements.errors', { defaultValue: 'error(s)' })}
          </div>
          {result.errors.slice(0, 3).map((e, i) => (
            <div key={`err-${(e.msg ?? '').slice(0, 30)}-${i}`} className="ml-5 mt-0.5">
              {e.msg}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Requirement set card ──────────────────────────────────────────── */

function RequirementSetCard({
  set,
  projectId,
  isExpanded,
  onToggle,
  onDelete,
}: {
  set: BIMRequirementSetResponse;
  projectId: string;
  isExpanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [validateOpen, setValidateOpen] = useState(false);

  // Export-as-Excel — authenticated POST → blob → download. A plain anchor
  // would 405 (POST-only endpoint) / 401 (no Bearer header).
  const exportExcelMutation = useMutation({
    mutationFn: () => exportBIMRequirementSetExcel(set.id, set.name),
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  // Export-as-IDS-XML — same authenticated POST → blob → download path.
  const exportIdsMutation = useMutation({
    mutationFn: () => exportBIMRequirementSetIds(set.id, set.name),
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  return (
    <div className="border rounded-lg border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800">
      {/* Header */}
      <div
        className="flex items-center justify-between p-3 cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-700/50"
        onClick={onToggle}
      >
        <div className="flex items-center gap-2">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-zinc-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-zinc-400" />
          )}
          <span className="text-sm font-medium text-zinc-800 dark:text-zinc-100">{set.name}</span>
          <span className="text-xs text-zinc-400 bg-zinc-100 dark:bg-zinc-700 px-1.5 py-0.5 rounded">
            {set.source_format}
          </span>
        </div>
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            onClick={() => setValidateOpen(true)}
            className="p-1.5 text-zinc-400 hover:text-indigo-600 rounded"
            title={t('bim_requirements.validateAgainstModel', {
              defaultValue: 'Validate a BIM model against this requirement set',
            })}
          >
            <ShieldCheck className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={() => exportExcelMutation.mutate()}
            disabled={exportExcelMutation.isPending}
            className="p-1.5 text-zinc-400 hover:text-green-600 rounded disabled:opacity-50"
            title={t('bim.requirements.exportExcel', { defaultValue: 'Export as Excel' })}
          >
            {exportExcelMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <FileSpreadsheet className="w-4 h-4" />
            )}
          </button>
          <button
            type="button"
            onClick={() => exportIdsMutation.mutate()}
            disabled={exportIdsMutation.isPending}
            className="p-1.5 text-zinc-400 hover:text-blue-600 rounded disabled:opacity-50"
            title={t('bim.requirements.exportIDS', { defaultValue: 'Export as IDS XML' })}
          >
            {exportIdsMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <FileCode className="w-4 h-4" />
            )}
          </button>
          <button
            onClick={onDelete}
            className="p-1.5 text-zinc-400 hover:text-red-600 rounded"
            title={t('common.delete', { defaultValue: 'Delete' })}
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Expanded detail */}
      {isExpanded && <RequirementSetDetail setId={set.id} />}

      {/* Validate-against-model modal */}
      {validateOpen && (
        <ValidateAgainstModelModal
          set={set}
          projectId={projectId}
          onClose={() => setValidateOpen(false)}
        />
      )}
    </div>
  );
}

/* ── Validate against BIM model ────────────────────────────────────── */

function ValidateAgainstModelModal({
  set,
  projectId,
  onClose,
}: {
  set: BIMRequirementSetResponse;
  projectId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [modelId, setModelId] = useState<string>('');
  const [report, setReport] = useState<BIMRequirementValidationResult | null>(null);

  // Models for the picker — scoped to the active project.
  const { data: modelsResp, isLoading: modelsLoading } = useQuery({
    queryKey: ['bim-models', projectId],
    queryFn: () => fetchBIMModels(projectId),
  });
  const models = modelsResp?.items ?? [];

  const validateMutation = useMutation({
    mutationFn: () => validateBIMRequirementSet(set.id, modelId),
    onSuccess: (result) => setReport(result),
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-lg bg-white dark:bg-zinc-800 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-700 p-4">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-indigo-600" />
            <h3 className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
              {t('bim_requirements.validateModalTitle', {
                defaultValue: 'Validate model against "{{name}}"',
                name: set.name,
              })}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="text-zinc-400 hover:text-zinc-600 text-sm"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            x
          </button>
        </div>

        <div className="p-4 space-y-4">
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            {t('bim_requirements.validateHint', {
              defaultValue:
                'Pick an imported BIM model. Each requirement is checked against the matching elements and you get a pass / fail / not-applicable report.',
            })}
          </p>

          <div className="flex items-end gap-2">
            <label className="flex-1 text-xs text-zinc-600 dark:text-zinc-300">
              <span className="block mb-1 font-medium">
                {t('bim_requirements.validateModelPicker', { defaultValue: 'BIM model' })}
              </span>
              <select
                value={modelId}
                onChange={(e) => {
                  setModelId(e.target.value);
                  setReport(null);
                }}
                disabled={modelsLoading || models.length === 0}
                className="w-full rounded-md border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-900 px-2 py-1.5 text-sm disabled:opacity-50"
              >
                <option value="">
                  {t('bim_requirements.validateSelectModel', { defaultValue: 'Select a model…' })}
                </option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => validateMutation.mutate()}
              disabled={!modelId || validateMutation.isPending}
              className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {validateMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <ShieldCheck className="w-4 h-4" />
              )}
              {t('bim_requirements.runValidation', { defaultValue: 'Validate' })}
            </button>
          </div>

          {!modelsLoading && models.length === 0 && (
            <p className="text-sm text-zinc-400">
              {t('bim_requirements.noModels', {
                defaultValue: 'No BIM models in this project yet. Upload a model first.',
              })}
            </p>
          )}

          {report && <ValidationReportView report={report} />}
        </div>
      </div>
    </div>
  );
}

function ValidationReportView({ report }: { report: BIMRequirementValidationResult }) {
  const { t } = useTranslation();
  const compliancePct = Math.round((report.compliance_ratio || 0) * 100);

  return (
    <div className="space-y-3">
      {/* Traffic-light summary */}
      <div className="grid grid-cols-4 gap-2">
        <SummaryChip
          tone="zinc"
          label={t('bim_requirements.summaryTotal', { defaultValue: 'Total' })}
          value={report.total_requirements}
        />
        <SummaryChip
          tone="green"
          label={t('bim_requirements.summaryPassed', { defaultValue: 'Passed' })}
          value={report.passed}
        />
        <SummaryChip
          tone="red"
          label={t('bim_requirements.summaryFailed', { defaultValue: 'Failed' })}
          value={report.failed}
        />
        <SummaryChip
          tone="amber"
          label={t('bim_requirements.summaryNA', { defaultValue: 'N/A' })}
          value={report.not_applicable}
        />
      </div>
      <div className="text-xs text-zinc-500 dark:text-zinc-400">
        {t('bim_requirements.complianceRatio', {
          defaultValue: 'Compliance: {{pct}}%',
          pct: compliancePct,
        })}
      </div>

      {report.results.length === 0 ? (
        <p className="text-sm text-zinc-400">
          {t('bim_requirements.noResults', {
            defaultValue: 'No active requirements to evaluate in this set.',
          })}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-zinc-100 dark:border-zinc-700">
          <table className="w-full text-xs">
            <thead className="bg-zinc-50 dark:bg-zinc-700/50">
              <tr>
                <th className="px-3 py-1.5 text-left font-medium text-zinc-500">
                  {t('bim_requirements.colStatus', { defaultValue: 'Status' })}
                </th>
                <th className="px-3 py-1.5 text-left font-medium text-zinc-500">
                  {t('bim.requirements.col.property', { defaultValue: 'Property' })}
                </th>
                <th className="px-3 py-1.5 text-left font-medium text-zinc-500">
                  {t('bim_requirements.colDetails', { defaultValue: 'Details' })}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-700">
              {report.results.map((r) => (
                <tr key={r.requirement_id} className="hover:bg-zinc-50 dark:hover:bg-zinc-700/30">
                  <td className="px-3 py-1.5 whitespace-nowrap">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-3 py-1.5 text-zinc-800 dark:text-zinc-200 font-medium">
                    {r.property_group ? `${r.property_group} · ` : ''}
                    {r.property_name}
                  </td>
                  <td className="px-3 py-1.5 text-zinc-500 dark:text-zinc-400">{r.details}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SummaryChip({
  tone,
  label,
  value,
}: {
  tone: 'zinc' | 'green' | 'red' | 'amber';
  label: string;
  value: number;
}) {
  const toneClass = {
    zinc: 'bg-zinc-50 dark:bg-zinc-700/40 text-zinc-700 dark:text-zinc-200',
    green: 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300',
    red: 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300',
    amber: 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300',
  }[tone];
  return (
    <div className={clsx('rounded-md p-2 text-center', toneClass)}>
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-[10px] uppercase tracking-wide opacity-80">{label}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  if (status === 'pass') {
    return (
      <span className="inline-flex items-center gap-1 text-green-700 dark:text-green-300">
        <CheckCircle2 className="w-3.5 h-3.5" />
        {t('bim_requirements.statusPass', { defaultValue: 'Pass' })}
      </span>
    );
  }
  if (status === 'fail') {
    return (
      <span className="inline-flex items-center gap-1 text-red-700 dark:text-red-300">
        <XCircle className="w-3.5 h-3.5" />
        {t('bim_requirements.statusFail', { defaultValue: 'Fail' })}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-300">
      <MinusCircle className="w-3.5 h-3.5" />
      {t('bim_requirements.statusNA', { defaultValue: 'N/A' })}
    </span>
  );
}

/* ── Expanded detail view ──────────────────────────────────────────── */

function RequirementSetDetail({ setId }: { setId: string }) {
  const { t } = useTranslation();

  const { data, isLoading } = useQuery({
    queryKey: ['bim-requirement-set-detail', setId],
    queryFn: () => fetchBIMRequirementSetDetail(setId),
  });

  if (isLoading) {
    return (
      <div className="p-3 border-t border-zinc-100 dark:border-zinc-700 text-sm text-zinc-400 flex items-center gap-1">
        <Loader2 className="w-4 h-4 animate-spin" />
        {t('common.loading', { defaultValue: 'Loading...' })}
      </div>
    );
  }

  if (!data || data.requirements.length === 0) {
    return (
      <div className="p-3 border-t border-zinc-100 dark:border-zinc-700 text-sm text-zinc-400">
        {t('bim.requirements.empty', { defaultValue: 'No requirements in this set.' })}
      </div>
    );
  }

  return (
    <div className="border-t border-zinc-100 dark:border-zinc-700 overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-zinc-50 dark:bg-zinc-700/50">
          <tr>
            <th className="px-3 py-1.5 text-left font-medium text-zinc-500">
              {t('bim.requirements.col.element', { defaultValue: 'Element' })}
            </th>
            <th className="px-3 py-1.5 text-left font-medium text-zinc-500">
              {t('bim.requirements.col.pset', { defaultValue: 'Property Set' })}
            </th>
            <th className="px-3 py-1.5 text-left font-medium text-zinc-500">
              {t('bim.requirements.col.property', { defaultValue: 'Property' })}
            </th>
            <th className="px-3 py-1.5 text-left font-medium text-zinc-500">
              {t('bim.requirements.col.constraint', { defaultValue: 'Constraint' })}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-700">
          {data.requirements.slice(0, 50).map((req) => (
            <tr key={req.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-700/30">
              <td className="px-3 py-1.5 text-zinc-700 dark:text-zinc-300">
                {(req.element_filter as Record<string, string>).ifc_class || '-'}
              </td>
              <td className="px-3 py-1.5 text-zinc-600 dark:text-zinc-400">
                {req.property_group || '-'}
              </td>
              <td className="px-3 py-1.5 text-zinc-800 dark:text-zinc-200 font-medium">
                {req.property_name}
              </td>
              <td className="px-3 py-1.5 text-zinc-500 dark:text-zinc-400">
                {formatConstraint(req.constraint_def as Record<string, unknown>)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.requirements.length > 50 && (
        <div className="p-2 text-xs text-zinc-400 text-center">
          {t('bim.requirements.showingFirst', {
            defaultValue: 'Showing first 50 of {{total}} requirements',
            total: data.requirements.length,
          })}
        </div>
      )}
    </div>
  );
}

/** Format a constraint_def object for display. */
function formatConstraint(cd: Record<string, unknown>): string {
  const parts: string[] = [];
  if (cd.cardinality) parts.push(String(cd.cardinality));
  if (cd.datatype) parts.push(String(cd.datatype));
  if (Array.isArray(cd.enum)) parts.push(fmtList((cd.enum as unknown[]).map(String)));
  if (cd.min !== undefined || cd.max !== undefined) {
    const min = cd.min !== undefined ? String(cd.min) : '';
    const max = cd.max !== undefined ? String(cd.max) : '';
    parts.push(`${min}..${max}`);
  }
  if (cd.pattern) parts.push(`/${cd.pattern}/`);
  if (cd.value && !Array.isArray(cd.enum)) parts.push(String(cd.value));
  if (cd.unit) parts.push(String(cd.unit));
  return parts.join(' | ') || '-';
}
