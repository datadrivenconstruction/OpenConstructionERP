// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Road and rail stake list inside setting-out: a LandXML alignment with its
 * profile gives stakes every N m with design level, and cut/fill once levels
 * are measured. Nothing is saved.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Calculator, FileUp } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fmtM } from './angles';
import { runStakeList, type StakeListIn } from './api';
import { Findings } from './CalcPage';

/** "chainage offset z" per line; offset may be left out (centreline). */
export function parseMeasured(text: string): StakeListIn['measured'] | null {
  const out: StakeListIn['measured'] = [];
  for (const line of text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)) {
    const nums = line.split(/[\s;,]+/).map(Number);
    if (nums.some((x) => !Number.isFinite(x)) || nums.length < 2 || nums.length > 3) return null;
    out.push(nums.length === 2 ? { chainage: nums[0], offset: 0, z: nums[1] } : { chainage: nums[0], offset: nums[1], z: nums[2] });
  }
  return out;
}

export function RoadStakePanel() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [xml, setXml] = useState('');
  const [fileName, setFileName] = useState('');
  const [interval, setInterval] = useState('20');
  const [offsets, setOffsets] = useState('0');
  const [crossfall, setCrossfall] = useState('0');
  const [measured, setMeasured] = useState('');
  const [mode, setMode] = useState<'stake' | 'as_built'>('stake');
  const run = useMutation({ mutationFn: runStakeList, onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }) });

  const offs = offsets.split(/[\s;,]+/).filter(Boolean).map(Number);
  const meas = parseMeasured(measured);
  const step = Number(interval);
  const ready = xml.trim() && step > 0 && offs.length > 0 && offs.every(Number.isFinite) && meas && Number.isFinite(Number(crossfall));
  const r = run.data;

  return (
    <div className="space-y-3" data-testid="road-stake-panel">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block text-sm sm:col-span-2">
          <span className="oe-label">{t('survey.road.file', { defaultValue: 'LandXML with alignment and profile' })}</span>
          <span className="flex items-center gap-2">
            <label className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-border-light px-2 py-1 text-sm hover:bg-surface-secondary">
              <FileUp size={14} />
              {t('survey.road.choose', { defaultValue: 'Choose file' })}
              <input type="file" accept=".xml,.landxml" className="sr-only"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFileName(f.name); void f.text().then(setXml); } }} />
            </label>
            <bdi dir="ltr" className="truncate text-content-secondary">{fileName}</bdi>
          </span>
        </label>
        <label className="block text-sm">
          <span className="oe-label">{t('survey.road.interval', { defaultValue: 'Every (m)' })}</span>
          <input className="oe-input w-full font-mono" dir="ltr" value={interval} onChange={(e) => setInterval(e.target.value)} />
        </label>
        <label className="block text-sm">
          <span className="oe-label">{t('survey.road.offsets', { defaultValue: 'Offsets (m), left negative' })}</span>
          <input className="oe-input w-full font-mono" dir="ltr" value={offsets} onChange={(e) => setOffsets(e.target.value)} />
        </label>
        <label className="block text-sm">
          <span className="oe-label">{t('survey.road.crossfall', { defaultValue: 'Crossfall (%)' })}</span>
          <input className="oe-input w-full font-mono" dir="ltr" value={crossfall} onChange={(e) => setCrossfall(e.target.value)} />
        </label>
        <label className="block text-sm">
          <span className="oe-label">{t('survey.road.mode', { defaultValue: 'Measured levels are' })}</span>
          <select className="oe-input w-full" value={mode} onChange={(e) => setMode(e.target.value as 'stake' | 'as_built')}
            title={t('survey.road.mode_tip', { defaultValue: 'Ground before work: above design is cut. Built surface: above design is fill.' })}>
            <option value="stake">{t('survey.road.mode_stake', { defaultValue: 'Ground before work' })}</option>
            <option value="as_built">{t('survey.road.mode_as_built', { defaultValue: 'Built surface' })}</option>
          </select>
        </label>
        <label className="block text-sm sm:col-span-2">
          <span className="oe-label">{t('survey.road.measured', { defaultValue: 'Measured levels: chainage offset Z per line (optional)' })}</span>
          <textarea className="oe-input w-full font-mono" rows={2} dir="ltr" value={measured} onChange={(e) => setMeasured(e.target.value)} />
        </label>
      </div>
      <Button icon={<Calculator size={14} />} disabled={!ready} loading={run.isPending}
        onClick={() => meas && run.mutate({ landxml: xml, interval: step, offsets: offs, crossfall_pct: Number(crossfall), measured: meas, mode })}>
        {t('survey.road.compute', { defaultValue: 'Make stake list' })}
      </Button>
      {r && (
        <div className="space-y-2">
          <p className="text-sm text-content-secondary">
            {t('survey.road.summary', { defaultValue: 'Alignment {{l}} m from chainage {{s}}, {{n}} stakes', l: fmtM(r.alignment_length), s: fmtM(r.start_chainage), n: r.rows.length })}
          </p>
          <Findings items={r.findings} />
          <div className="max-h-96 overflow-auto">
            <table className="oe-table w-full text-sm">
              <thead>
                <tr>
                  <th className="text-right">{t('survey.setting_out.col.chainage', { defaultValue: 'Chainage (m)' })}</th>
                  <th className="text-right">{t('survey.setting_out.col.offset', { defaultValue: 'Offset (m)' })}</th>
                  <th className="text-right">E</th>
                  <th className="text-right">N</th>
                  <th className="text-right">{t('survey.road.col.design_z', { defaultValue: 'Design level' })}</th>
                  <th className="text-right">{t('survey.road.col.measured_z', { defaultValue: 'Measured' })}</th>
                  <th className="text-right">{t('survey.setting_out.col.dz', { defaultValue: 'dZ' })}</th>
                  <th>{t('survey.road.col.cut_fill', { defaultValue: 'Cut / fill' })}</th>
                </tr>
              </thead>
              <tbody>
                {r.rows.map((row) => (
                  <tr key={`${row.chainage}:${row.offset}`}>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(row.chainage)}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(row.offset, 2)}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(row.e)}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(row.n)}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(row.design_z)}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{fmtM(row.measured_z)}</bdi></td>
                    <td className="text-right"><bdi dir="ltr" className="font-mono">{row.dz_mm == null ? '' : row.dz_mm.toFixed(0)}</bdi></td>
                    <td>{row.cut_fill ? t(`survey.road.${row.cut_fill}`, { defaultValue: row.cut_fill === 'on_grade' ? 'On grade' : row.cut_fill === 'cut' ? 'Cut' : 'Fill' }) : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
