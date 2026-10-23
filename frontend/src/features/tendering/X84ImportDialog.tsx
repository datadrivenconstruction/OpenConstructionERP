// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Upload } from 'lucide-react';
import { Button, Badge, Input } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtList } from '@/shared/lib/formatters';
import { importX84Bid, type X84ImportPreview } from './api';

const FILE_ISSUE_TEXT: Record<string, string> = {
  not_x84: 'This is not a priced bid (GAEB X84) file.',
  currency_mismatch: 'The file is priced in a different currency than the tender.',
  no_bill: 'This package has no bill to compare against.',
  nothing_priced: 'No line of the file could be taken as a price.',
};

const LINE_ISSUE_TEXT: Record<string, string> = {
  unknown_position: 'Not in this tender',
  unit_mismatch: 'Unit changed',
  quantity_changed: 'Quantity changed',
  unpriced: 'No price',
  duplicate_position: 'Priced twice',
};

const ERROR_TEXT: Record<string, string> = {
  unreadable_file: 'The file could not be read as GAEB XML.',
  file_too_large: 'The file is too large (limit 20 MB).',
  x84_has_blocking_issues: 'The file still has blocking issues.',
};

/** Read a bidder's priced GAEB X84 file, check every line against the bill, then add it as a bid. */
export function X84ImportDialog({
  open,
  onClose,
  packageId,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  packageId: string;
  onImported: () => void;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<X84ImportPreview | null>(null);
  const [company, setCompany] = useState('');
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setFile(null);
    setPreview(null);
    setCompany('');
    setEmail('');
    setError(null);
    onClose();
  };
  const explain = (e: Error) =>
    e.message in ERROR_TEXT
      ? t(`tendering.x84_error_${e.message}`, { defaultValue: ERROR_TEXT[e.message] })
      : e.message;

  const previewMutation = useMutation({
    mutationFn: (f: File) => importX84Bid<X84ImportPreview>(packageId, f),
    onSuccess: (data) => {
      setPreview(data);
      setError(null);
    },
    onError: (e: Error) => {
      setPreview(null);
      setError(explain(e));
    },
  });

  const importMutation = useMutation({
    mutationFn: (f: File) => importX84Bid<unknown>(packageId, f, { name: company.trim(), email: email.trim() }),
    onSuccess: () => {
      onImported();
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

  const flagged = preview ? preview.lines.filter((l) => l.issues.length > 0) : [];

  return (
    <WideModal
      open={open}
      onClose={close}
      title={t('tendering.x84_title', { defaultValue: 'Import a priced GAEB X84 bid' })}
      footer={
        <>
          <Button variant="ghost" onClick={close}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            disabled={!file || !preview || preview.blocking || !company.trim() || importMutation.isPending}
            loading={importMutation.isPending}
            onClick={() => file && importMutation.mutate(file)}
            data-testid="x84-import-confirm"
          >
            {t('tendering.x84_confirm', { defaultValue: 'Add as bid' })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-content-secondary">
          {t('tendering.x84_hint', {
            defaultValue:
              'Upload the X84 file the bidder priced. Every line is matched to this tender by its position number; units and quantities must stay as issued.',
          })}
        </p>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary">
          <Upload size={14} />
          {file ? file.name : t('tendering.import_choose', { defaultValue: 'Choose file' })}
          <input
            type="file"
            accept=".x84,.xml"
            className="sr-only"
            data-testid="x84-import-file"
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
            <p className="text-sm font-medium text-content-primary" data-testid="x84-import-summary">
              {t('tendering.x84_summary', {
                defaultValue: '{{priced}} of {{total}} lines priced, total {{amount}} {{currency}}',
                priced: preview.priced,
                total: preview.lines.length,
                amount: preview.total_amount,
                currency: preview.tender_currency || preview.currency,
              })}
            </p>
            {preview.file_issues.map((code) => (
              <p key={code} role="alert" className="text-sm text-semantic-error">
                {t(`tendering.x84_file_issue_${code}`, { defaultValue: FILE_ISSUE_TEXT[code] ?? code })}
              </p>
            ))}
            {preview.missing_ordinals.length > 0 && (
              <p className="text-sm text-content-secondary">
                {t('tendering.x84_missing', {
                  defaultValue: 'Not in the file, left unpriced: {{list}}',
                  list: fmtList(preview.missing_ordinals.slice(0, 20)),
                })}
              </p>
            )}
            {flagged.length > 0 && (
              <div className="max-h-72 overflow-auto rounded-lg border border-border">
                <table className="w-full text-sm">
                  <thead className="bg-surface-secondary text-left text-xs text-content-secondary">
                    <tr>
                      <th className="px-3 py-2">{t('tendering.x84_col_ordinal', { defaultValue: 'Position' })}</th>
                      <th className="px-3 py-2">{t('tendering.x84_col_text', { defaultValue: 'Text' })}</th>
                      <th className="px-3 py-2">{t('tendering.import_col_status', { defaultValue: 'Status' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {flagged.map((l, i) => (
                      <tr key={`${l.ordinal}-${i}`} className="border-t border-border" data-testid="x84-import-row">
                        <td className="px-3 py-2 font-mono text-xs">{l.ordinal}</td>
                        <td className="px-3 py-2">{l.description}</td>
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap gap-1">
                            {l.issues.map((code) => (
                              <Badge key={code} variant={code === 'unpriced' ? 'warning' : 'error'}>
                                {t(`tendering.x84_issue_${code}`, { defaultValue: LINE_ISSUE_TEXT[code] ?? code })}
                              </Badge>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {!preview.blocking && (
              <div className="grid gap-3 sm:grid-cols-2">
                <Input
                  label={t('tendering.company_name', 'Company Name')}
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  data-testid="x84-import-company"
                />
                <Input
                  label={t('tendering.contact_email', 'Contact Email')}
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
            )}
          </>
        )}
      </div>
    </WideModal>
  );
}
