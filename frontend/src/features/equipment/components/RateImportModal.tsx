// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Three steps: file, column mapping (layout from the active pack), check and create. */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Button } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  importRateTable,
  previewRateImport,
  type RateImportPreview,
  type RateImportResult,
} from '../ratesApi';

interface Props {
  onClose: () => void;
  onDone: (catalogueId: string) => void;
}

export function RateImportModal({ onClose, onDone }: Props) {
  const { t } = useTranslation();
  const toast = useToastStore((s) => s.addToast);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<RateImportPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [decimalComma, setDecimalComma] = useState(false);
  const [name, setName] = useState('');
  const [licence, setLicence] = useState('');
  const [check, setCheck] = useState<RateImportResult | null>(null);

  const options = (dryRun: boolean) => ({
    mapping,
    decimalComma,
    dryRun,
    name,
    validFrom: '',
    licenceNote: licence,
    currency: '',
    interestConvention: 'average_value',
  });
  const read = useMutation({
    mutationFn: (f: File) => previewRateImport(f),
    onSuccess: (p) => {
      setPreview(p);
      setMapping(p.suggested_mapping);
    },
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });
  const dry = useMutation({
    mutationFn: () => importRateTable(file as File, options(true)),
    onSuccess: setCheck,
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });
  const create = useMutation({
    mutationFn: () => importRateTable(file as File, options(false)),
    onSuccess: (r) => r.catalogue_id && onDone(r.catalogue_id),
    onError: (e) => toast({ type: 'error', title: getErrorMessage(e) }),
  });

  const layoutLabel = (key: string) => t(key, { defaultValue: t('equipment.rates.layout_own', { defaultValue: 'My own layout' }) });

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('equipment.rates.import', { defaultValue: 'Import table' })}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {!check && preview && (
            <Button loading={dry.isPending} onClick={() => dry.mutate()}>
              {t('equipment.rates.check', { defaultValue: 'Check' })}
            </Button>
          )}
          {check && check.ready > 0 && (
            <Button loading={create.isPending} disabled={!name.trim()} onClick={() => create.mutate()}>
              {t('equipment.rates.create_version', { defaultValue: 'Create catalogue version' })}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4 p-1">
        <p className="rounded border border-border-light p-2 text-sm" data-testid="rate-import-notice">
          {t('equipment.rates.import_notice', {
            defaultValue:
              'Bring the rate table your company licenses. We do not ship national equipment lists or their values.',
          })}
        </p>
        <input
          type="file"
          accept=".csv,.xlsx"
          aria-label={t('equipment.rates.import', { defaultValue: 'Import table' })}
          onChange={(e) => {
            const f = e.target.files?.[0] ?? null;
            setFile(f);
            setCheck(null);
            if (f) read.mutate(f);
          }}
        />
        {preview && (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span>{t('equipment.rates.layout', { defaultValue: 'Layout' })}</span>
              <select
                className="oe-input"
                defaultValue=""
                onChange={(e) => {
                  const layout = preview.layouts.find((l) => l.key === e.target.value);
                  if (layout) {
                    setMapping(layout.mapping);
                    setDecimalComma(layout.decimal_comma);
                  }
                }}
              >
                <option value="">{t('equipment.rates.layout_own', { defaultValue: 'My own layout' })}</option>
                {preview.layouts.map((l) => (
                  <option key={l.key} value={l.key}>
                    {layoutLabel(l.label_key)}
                  </option>
                ))}
              </select>
            </div>
            <table className="oe-table w-full text-sm">
              <tbody>
                {preview.fields.map((field) => (
                  <tr key={field}>
                    <td>
                      {field}
                      {preview.required_fields.includes(field) ? ' *' : ''}
                    </td>
                    <td>
                      <select
                        className="oe-input w-full"
                        aria-label={field}
                        value={mapping[field] ?? ''}
                        onChange={(e) => setMapping((m) => ({ ...m, [field]: e.target.value }))}
                      >
                        <option value="" />
                        {preview.headers.map((h) => (
                          <option key={h} value={h}>
                            {h}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={decimalComma} onChange={(e) => setDecimalComma(e.target.checked)} />
              {t('equipment.rates.decimal_comma', { defaultValue: 'Numbers use a decimal comma' })}
            </label>
          </>
        )}
        {check && (
          <div className="space-y-2" data-testid="rate-import-check">
            <p className="text-sm">
              {t('equipment.rates.ready_count', { n: check.ready, defaultValue: 'Ready: {{n}}' })},{' '}
              {t('equipment.rates.error_count', { n: check.error_rows, defaultValue: 'With errors: {{n}}' })}
            </p>
            <ul className="max-h-40 overflow-auto text-xs text-semantic-error">
              {check.issues.slice(0, 50).map((i, idx) => (
                <li key={idx}>{i.row ? `${i.row}: ` : ''}{i.message}</li>
              ))}
            </ul>
            <input
              className="oe-input w-full"
              placeholder={t('equipment.rates.name', { defaultValue: 'Catalogue name' })}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <input
              className="oe-input w-full"
              placeholder={t('equipment.rates.licence_note', { defaultValue: 'Licence note' })}
              value={licence}
              onChange={(e) => setLicence(e.target.value)}
            />
          </div>
        )}
      </div>
    </WideModal>
  );
}
