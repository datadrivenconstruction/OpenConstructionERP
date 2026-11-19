// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Export menu for survey points and design stakes: CSV in a column preset,
 * GeoJSON, GSI-16, LandXML and DXF. Self-contained so any survey page can
 * mount it: it reads the project's local grid itself and words the server's
 * rule ids (SRV-110 when the file is written in another system).
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { FileDown } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  CSV_PRESETS,
  EXPORT_FORMATS,
  downloadSurveyExport,
  getGeodesy,
  registerExportUrl,
  stakeExportUrl,
  type ExportFormat,
} from './api';

export type ExportTarget =
  | { kind: 'register'; projectId: string; pointKind?: string; setId?: string }
  | { kind: 'stakes'; projectId: string; requestId: string; code?: string };

const FORMAT_NAMES: Record<ExportFormat, string> = { csv: 'CSV', geojson: 'GeoJSON', gsi: 'GSI-16', landxml: 'LandXML 1.2', dxf: 'DXF' };
const EXT: Record<ExportFormat, string> = { csv: 'csv', geojson: 'geojson', gsi: 'gsi', landxml: 'xml', dxf: 'dxf' };
const DELIMITERS: { value: string; key: string; label: string }[] = [
  { value: ',', key: 'comma', label: 'Comma' },
  { value: ';', key: 'semicolon', label: 'Semicolon' },
  { value: '\\t', key: 'tab', label: 'Tab' },
  { value: ' ', key: 'space', label: 'Space' },
];

/** Formats the server writes; the label names the format, never a device. */
export function formatLabelKey(f: ExportFormat): string {
  return `survey.export.format.${f}`;
}

export function SurveyExportMenu({ target, disabled }: { target: ExportTarget; disabled?: boolean }) {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<ExportFormat>('csv');
  const [preset, setPreset] = useState<string>('PNEZD');
  const [delimiter, setDelimiter] = useState(',');
  const [local, setLocal] = useState(false);
  const [epsg, setEpsg] = useState('');
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const register = target.kind === 'register';

  const geo = useQuery({
    queryKey: ['survey', 'geodesy', target.projectId],
    queryFn: () => getGeodesy(target.projectId),
    enabled: open && register,
  });
  const hasLocal = register && !!geo.data?.solution;

  useEffect(() => {
    if (!open) return undefined;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const targetEpsg = /^\d{4,6}$/.test(epsg.trim()) ? Number(epsg.trim()) : null;

  const run = async () => {
    setBusy(true);
    try {
      const opts = {
        format,
        preset,
        delimiter,
        locale: i18n.language,
        local: register && local && hasLocal,
        target_epsg: register ? targetEpsg : null,
        kind: register ? target.pointKind : undefined,
        set_id: register ? target.setId : undefined,
      };
      const url = target.kind === 'register' ? registerExportUrl(target.projectId, opts) : stakeExportUrl(target.requestId, opts);
      const base = target.kind === 'register' ? 'survey_points' : `setting-out-${target.code ?? ''}`;
      const warnings = await downloadSurveyExport(url, `${base}.${EXT[format]}`);
      if (warnings.includes('SRV-110')) {
        addToast({
          type: 'warning',
          title: t('survey.export.crs_warning', {
            defaultValue: 'Written in EPSG {{code}}, not the project system: coordinates were transformed.',
            code: targetEpsg ?? '',
          }),
        });
      }
      setOpen(false);
    } catch (e) {
      addToast({ type: 'error', title: getErrorMessage(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative" ref={box}>
      <Button
        variant="secondary"
        icon={<FileDown size={16} />}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        disabled={disabled}
        data-testid={register ? 'survey-export' : 'stakes-export'}
      >
        {t('survey.export.button', { defaultValue: 'Export' })}
      </Button>
      {open && (
        <div
          role="dialog"
          aria-label={t('survey.export.button', { defaultValue: 'Export' })}
          className="absolute end-0 z-20 mt-1 w-72 space-y-3 rounded-md border border-border-light bg-surface-primary p-3 shadow-lg"
          data-testid="survey-export-panel"
        >
          <fieldset>
            <legend className="mb-1 text-xs font-medium text-content-secondary">
              {t('survey.export.format_label', { defaultValue: 'Format' })}
            </legend>
            <div className="space-y-1">
              {EXPORT_FORMATS.map((f) => (
                <label key={f} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="survey-export-format" checked={format === f} onChange={() => setFormat(f)} />
                  {t(formatLabelKey(f), { defaultValue: FORMAT_NAMES[f] })}
                </label>
              ))}
            </div>
          </fieldset>
          {format === 'csv' && (
            <div className="grid grid-cols-2 gap-2">
              <label className="text-xs text-content-secondary">
                {t('survey.export.preset', { defaultValue: 'Columns' })}
                <select className="oe-input mt-1 w-full" value={preset} onChange={(e) => setPreset(e.target.value)}>
                  {CSV_PRESETS.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-content-secondary">
                {t('survey.export.delimiter', { defaultValue: 'Delimiter' })}
                <select className="oe-input mt-1 w-full" value={delimiter} onChange={(e) => setDelimiter(e.target.value)}>
                  {DELIMITERS.map((d) => (
                    <option key={d.key} value={d.value}>
                      {t(`survey.export.delimiter_${d.key}`, { defaultValue: d.label })}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          {register && hasLocal && (
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-0.5" checked={local} onChange={(e) => setLocal(e.target.checked)} />
              <span>
                {t('survey.export.local', { defaultValue: 'Site grid coordinates' })}
                <span className="block text-xs text-content-tertiary">
                  {t('survey.export.local_hint', { defaultValue: 'Back through the local grid tie, as the site plans read.' })}
                </span>
              </span>
            </label>
          )}
          {register && !local && (
            <label className="block text-xs text-content-secondary">
              {t('survey.export.target_epsg', { defaultValue: 'Write in another system (EPSG, optional)' })}
              <input
                className="oe-input mt-1 w-full font-mono"
                inputMode="numeric"
                value={epsg}
                onChange={(e) => setEpsg(e.target.value)}
                placeholder={t('survey.export.target_placeholder', { defaultValue: 'Project system' })}
              />
            </label>
          )}
          <div className="flex justify-end">
            <Button variant="primary" size="sm" loading={busy} onClick={() => void run()} data-testid="survey-export-run">
              {t('survey.export.download', { defaultValue: 'Download' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
