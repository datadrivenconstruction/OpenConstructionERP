// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CodeListImportModal - upload a project's own code list from CSV or XLSX.
//
// Two steps: the file is first checked (a dry run that stores nothing and
// lists every row problem with a preview of the tree), and only a clean check
// unlocks the import. Changing the file, key or name throws the check away,
// so what is imported is always what was checked.

import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { CheckCircle2, AlertTriangle } from 'lucide-react';

import { Button, WideModal, WideModalSection, WideModalField } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { costStructureApi, problemOf, type CodeListImportResult } from './structureApi';
import { problemMessage } from './problemMessages';

export interface CodeListImportModalProps {
  open: boolean;
  projectId: string;
  onClose: () => void;
  /** Called with the key of the stored list after a successful import. */
  onImported?: (key: string) => void;
}

const PREVIEW_ROWS = 20;

/** A key suggestion from a list name: lowercase, dashes, starts with a letter. */
export function suggestKey(name: string): string {
  const slug = name
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40);
  return /^[a-z]/.test(slug) ? slug : slug ? `list-${slug}`.slice(0, 40) : '';
}

export function CodeListImportModal({ open, projectId, onClose, onImported }: CodeListImportModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [key, setKey] = useState('');
  const [keyTouched, setKeyTouched] = useState(false);
  const [checked, setChecked] = useState<CodeListImportResult | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const ids = useId();

  const reset = () => {
    setFile(null);
    setName('');
    setKey('');
    setKeyTouched(false);
    setChecked(null);
    setFileError(null);
  };

  // Counted words go through plural keys, so "1 level" is not "1 levels".
  const counts = (entries: number, depth: number) => ({
    codes: t('costmodel.import.codes_count', { count: entries, defaultValue_one: '{{count}} code', defaultValue_other: '{{count}} codes' }),
    levels: t('costmodel.import.levels_count', { count: depth, defaultValue_one: '{{count}} level', defaultValue_other: '{{count}} levels' }),
  });

  const describe = (err: unknown) => {
    const problem = problemOf(err);
    return problem ? problemMessage(t, problem.problem, problem.params) : getErrorMessage(err);
  };

  const run = useMutation({
    // The error is shown here in the user's language; the global toast would repeat it raw.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: (dryRun: boolean) =>
      costStructureApi.importCodeList(projectId, { file: file!, key, name, dryRun }),
    onSuccess: (result, dryRun) => {
      setFileError(null);
      if (dryRun || !result.ok) {
        setChecked(result);
        return;
      }
      addToast({
        type: 'success',
        title: t('costmodel.import.done_title', { defaultValue: 'Code list imported' }),
        message: t('costmodel.import.done_summary', {
          defaultValue: '{{name}} is stored with {{codes}} in {{levels}}.',
          name: result.name,
          ...counts(result.entry_count, result.depth),
        }),
      });
      onImported?.(result.key);
      reset();
      onClose();
    },
    onError: (err) => {
      setChecked(null);
      setFileError(describe(err));
    },
  });

  const invalidateCheck = () => {
    setChecked(null);
    setFileError(null);
  };

  const canCheck = !!file && !!name.trim() && !!key.trim() && !run.isPending;
  const canImport = canCheck && !!checked?.ok && checked.issues.length === 0;

  const close = () => {
    if (run.isPending) return;
    reset();
    onClose();
  };

  return (
    <WideModal
      open={open}
      onClose={close}
      busy={run.isPending}
      title={t('costmodel.import.title', { defaultValue: 'Import code list' })}
      subtitle={t('costmodel.import.subtitle', {
        defaultValue:
          'A CSV or XLSX file with the columns code and title, and optionally parent. The file is checked before anything is stored.',
      })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={close} disabled={run.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="secondary"
            disabled={!canCheck}
            loading={run.isPending && run.variables === true}
            onClick={() => run.mutate(true)}
          >
            {t('costmodel.import.check_cta', { defaultValue: 'Check file' })}
          </Button>
          <Button
            variant="primary"
            disabled={!canImport}
            loading={run.isPending && run.variables === false}
            onClick={() => run.mutate(false)}
          >
            {t('costmodel.import.import_cta', { defaultValue: 'Import' })}
          </Button>
        </div>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField label={t('costmodel.import.file', { defaultValue: 'File' })} required htmlFor={`${ids}-file`}>
          <input
            id={`${ids}-file`}
            type="file"
            accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            data-testid="code-list-file"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              invalidateCheck();
            }}
            className="text-xs"
          />
        </WideModalField>
      </WideModalSection>
      <WideModalSection columns={2}>
        <WideModalField label={t('costmodel.import.name', { defaultValue: 'Name' })} required htmlFor={`${ids}-name`}>
          <input
            id={`${ids}-name`}
            type="text"
            value={name}
            maxLength={120}
            onChange={(e) => {
              setName(e.target.value);
              if (!keyTouched) setKey(suggestKey(e.target.value));
              invalidateCheck();
            }}
            className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-sm"
          />
        </WideModalField>
        <WideModalField
          label={t('costmodel.import.key', { defaultValue: 'Key' })}
          required
          htmlFor={`${ids}-key`}
          hint={t('costmodel.import.key_hint', {
            defaultValue: 'Lowercase letters, digits, dashes or underscores. Positions use it to name their codes.',
          })}
        >
          <input
            id={`${ids}-key`}
            type="text"
            value={key}
            maxLength={40}
            onChange={(e) => {
              setKey(e.target.value);
              setKeyTouched(true);
              invalidateCheck();
            }}
            className="h-8 w-full rounded-md border border-border bg-surface-primary px-2 font-mono text-sm"
          />
        </WideModalField>
      </WideModalSection>

      {fileError && (
        <div className="mt-3 flex items-start gap-2 rounded-md bg-semantic-error/10 px-3 py-2 text-sm text-semantic-error" role="alert">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          {fileError}
        </div>
      )}

      {checked && (
        <div className="mt-3 space-y-3" data-testid="code-list-check">
          {checked.issues.length === 0 ? (
            <div className="flex items-center gap-2 rounded-md bg-semantic-success/10 px-3 py-2 text-sm text-semantic-success">
              <CheckCircle2 size={16} />
              {t('costmodel.import.check_ok_summary', {
                defaultValue: 'The file is fine: {{codes}} in {{levels}}.',
                ...counts(checked.entry_count, checked.depth),
              })}
            </div>
          ) : (
            <div>
              <p className="mb-1 text-sm font-medium text-semantic-error">
                {t('costmodel.import.check_issues', {
                  defaultValue: 'Rows to fix before the import: {{issues}}',
                  issues: checked.issues.length,
                })}
              </p>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-start text-2xs uppercase text-content-tertiary">
                    <th className="px-2 py-1">{t('costmodel.import.col_row', { defaultValue: 'Row' })}</th>
                    <th className="px-2 py-1">{t('costmodel.import.col_code', { defaultValue: 'Code' })}</th>
                    <th className="px-2 py-1">{t('costmodel.import.col_problem', { defaultValue: 'Problem' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {checked.issues.map((issue, i) => (
                    <tr key={`${issue.row ?? 'file'}-${issue.problem}-${i}`} className="border-t border-border-light">
                      <td className="px-2 py-1 tabular-nums">{issue.row ?? '-'}</td>
                      <td className="px-2 py-1 font-mono">{issue.code || '-'}</td>
                      <td className="px-2 py-1">{problemMessage(t, issue.problem, issue.params)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {checked.preview.length > 0 && (
            <div>
              <p className="mb-1 text-2xs font-medium uppercase text-content-tertiary">
                {t('costmodel.import.preview', { defaultValue: 'Preview' })}
              </p>
              <ul className="max-h-48 overflow-y-auto rounded-md border border-border-light p-1 text-xs">
                {checked.preview.slice(0, PREVIEW_ROWS).map((entry, i) => (
                  <li
                    // A rejected file can carry the same code twice.
                    key={`${entry.code}-${i}`}
                    className="flex gap-2 py-0.5"
                    style={{ paddingInlineStart: `${(Math.max(entry.level, 1) - 1) * 14 + 4}px` }}
                  >
                    <span className="font-mono text-content-tertiary">{entry.code}</span>
                    <span className="truncate text-content-primary">{entry.title}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </WideModal>
  );
}
