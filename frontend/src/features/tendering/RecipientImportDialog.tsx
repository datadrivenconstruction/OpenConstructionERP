// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Upload } from 'lucide-react';
import { Button, Badge } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import {
  importRecipients,
  type RecipientImportPreview,
  type RecipientImportResult,
} from './api';

const ERROR_TEXT: Record<string, string> = {
  unsupported_type: 'Use a CSV or XLSX file.',
  empty_file: 'The file is empty.',
  missing_columns: 'The file needs at least the columns company and email.',
  too_many_rows: 'The file has too many rows (limit 1000).',
  file_too_large: 'The file is too large (limit 2 MB).',
  unreadable_file: 'The file could not be read.',
};

const ISSUE_TEXT: Record<string, string> = {
  company_missing: 'Company missing',
  email_invalid: 'Invalid email',
  duplicate_in_file: 'Repeated in file',
  already_invited: 'Already invited',
};

/** Upload a CSV/XLSX list of firms, see every row checked, then add the valid ones. */
export function RecipientImportDialog({
  open,
  onClose,
  packageId,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  packageId: string;
  onImported: (result: RecipientImportResult) => void;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<RecipientImportPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setFile(null);
    setPreview(null);
    setError(null);
  };
  const close = () => {
    reset();
    onClose();
  };
  const explain = (e: Error) =>
    e.message in ERROR_TEXT
      ? t(`tendering.import_error_${e.message}`, { defaultValue: ERROR_TEXT[e.message] })
      : e.message;

  const previewMutation = useMutation({
    mutationFn: (f: File) => importRecipients<RecipientImportPreview>(packageId, f, false),
    onSuccess: (data) => {
      setPreview(data);
      setError(null);
    },
    onError: (e: Error) => {
      setPreview(null);
      setError(explain(e));
    },
  });

  const confirmMutation = useMutation({
    mutationFn: (f: File) => importRecipients<RecipientImportResult>(packageId, f, true),
    onSuccess: (data) => {
      onImported(data);
      close();
    },
    onError: (e: Error) => setError(explain(e)),
  });

  const pick = (f: File | null) => {
    setFile(f);
    setPreview(null);
    setError(null);
    if (f) previewMutation.mutate(f);
  };

  return (
    <WideModal
      open={open}
      onClose={close}
      title={t('tendering.import_title', { defaultValue: 'Import recipients from a file' })}
      footer={
        <>
          <Button variant="ghost" onClick={close}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            disabled={!file || !preview || preview.valid === 0 || confirmMutation.isPending}
            loading={confirmMutation.isPending}
            onClick={() => file && confirmMutation.mutate(file)}
          >
            {t('tendering.import_confirm', { defaultValue: 'Add valid rows' })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-content-secondary">
          {t('tendering.import_hint', {
            defaultValue:
              'Upload a CSV or XLSX file with the columns company, contact name, email, trade and, optionally, VAT ID.',
          })}
        </p>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary">
          <Upload size={14} />
          {file ? file.name : t('tendering.import_choose', { defaultValue: 'Choose file' })}
          <input
            type="file"
            accept=".csv,.xlsx"
            className="sr-only"
            data-testid="recipient-import-file"
            onChange={(e) => pick(e.target.files?.[0] ?? null)}
          />
        </label>

        {error && (
          <p role="alert" className="text-sm text-semantic-error">
            {error}
          </p>
        )}

        {preview && (
          <>
            <p className="text-sm font-medium text-content-primary">
              {t('tendering.import_summary', {
                defaultValue: '{{valid}} of {{total}} rows can be added',
                valid: preview.valid,
                total: preview.total,
              })}
            </p>
            <div className="max-h-96 overflow-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
                  <tr>
                    <th className="px-3 py-2">{t('tendering.import_col_row', { defaultValue: 'Row' })}</th>
                    <th className="px-3 py-2">{t('tendering.company_name', 'Company Name')}</th>
                    <th className="px-3 py-2">
                      {t('tendering.import_col_contact', { defaultValue: 'Contact name' })}
                    </th>
                    <th className="px-3 py-2">{t('tendering.contact_email', 'Contact Email')}</th>
                    <th className="px-3 py-2">{t('tendering.import_col_trade', { defaultValue: 'Trade' })}</th>
                    <th className="px-3 py-2">{t('tendering.import_col_status', { defaultValue: 'Status' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((r) => (
                    <tr key={r.line} className="border-t border-border" data-testid="recipient-import-row">
                      <td className="px-3 py-2 text-content-tertiary">{r.line}</td>
                      <td className="px-3 py-2">{r.company}</td>
                      <td className="px-3 py-2">{r.contact_name}</td>
                      <td className="px-3 py-2">{r.email}</td>
                      <td className="px-3 py-2">{r.trade}</td>
                      <td className="px-3 py-2">
                        {r.valid ? (
                          <Badge variant="success">
                            {t('tendering.import_row_ok', { defaultValue: 'Ready' })}
                          </Badge>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {r.issues.map((code) => (
                              <Badge key={code} variant="error">
                                {t(`tendering.import_issue_${code}`, { defaultValue: ISSUE_TEXT[code] ?? code })}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </WideModal>
  );
}
