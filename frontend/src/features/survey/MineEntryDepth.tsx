// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The expanded period line: the actual split into ore, waste and low grade at
 * each material's density, and for a drive the advance and over/underbreak.
 */
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Layers, Upload } from 'lucide-react';
import { Button } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { fmtFixed } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { importMaterials, splitByMaterial, type MineEntry } from './mineApi';

const n = (v: number | null | undefined, d: number) => (v == null ? '-' : fmtFixed(v, d));

export function MineEntryDepth({ entry, canWrite }: { entry: MineEntry; canWrite: boolean }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const file = useRef<HTMLInputElement>(null);
  const onError = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });
  const split = useMutation({
    mutationFn: () => splitByMaterial(entry.id, i18n.language),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mine'] }),
    onError,
  });
  const upload = useMutation({
    mutationFn: async (f: File) => importMaterials(entry.unit_id, await f.text(), f.name),
    onSuccess: (r) => {
      if (r.problems.length) addToast({ type: 'warning', title: r.problems.slice(0, 3).join('; ') });
      split.mutate();
    },
    onError,
  });
  const s = entry.material_split;
  const drive = entry.drive;
  const locked = !!entry.claim_entry_id;

  return (
    <div className="space-y-3 pt-2" data-testid="mine-entry-depth">
      {entry.truck_ratio_pct != null && (
        <p className="text-xs text-content-secondary">
          {t('mine.split.truck_ratio', { defaultValue: 'Trucks against survey: {{p}} %', p: n(entry.truck_ratio_pct, 2) })}
        </p>
      )}
      {s ? (
        <table className="oe-table w-full max-w-xl text-sm" data-testid="mine-split">
          <thead>
            <tr>
              <th>{t('mine.split.material', { defaultValue: 'Material' })}</th>
              <th className="text-end">m³</th>
              <th className="text-end">{t('mine.split.density', { defaultValue: 'Density (t/m³)' })}</th>
              <th className="text-end">t</th>
            </tr>
          </thead>
          <tbody>
            {s.parts.map((p, i) => (
              <tr key={`${p.material}-${i}`}>
                <td>{p.name || t(`mine.material.${p.material}`, { defaultValue: p.material })}</td>
                <td className="text-end tabular-nums">{n(p.volume_m3, 1)}</td>
                <td className="text-end tabular-nums">{n(p.density_t_m3, 2)}</td>
                <td className="text-end tabular-nums">{n(p.tonnes, 2)}</td>
              </tr>
            ))}
            {s.unassigned_m3 > 0 && (
              <tr>
                <td className="text-content-secondary">{t('mine.split.unassigned', { defaultValue: 'Outside every polygon' })}</td>
                <td className="text-end tabular-nums">{n(s.unassigned_m3, 1)}</td>
                <td />
                <td />
              </tr>
            )}
            <tr className="font-medium">
              <td>{t('mine.split.total', { defaultValue: 'Total' })}</td>
              <td className="text-end tabular-nums">{n(s.total_m3, 1)}</td>
              <td />
              <td className="text-end tabular-nums">{n(s.tonnes, 2)}</td>
            </tr>
          </tbody>
        </table>
      ) : null}
      {canWrite && !locked && entry.actual && (
        <div className="flex flex-wrap gap-2">
          <input
            ref={file}
            type="file"
            accept=".geojson,.json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload.mutate(f);
              e.target.value = '';
            }}
          />
          <Button size="sm" variant="secondary" icon={<Upload size={14} />} loading={upload.isPending} onClick={() => file.current?.click()}>
            {t('mine.split.import', { defaultValue: 'Import material polygons (GeoJSON)' })}
          </Button>
          <Button size="sm" variant="ghost" icon={<Layers size={14} />} loading={split.isPending} onClick={() => split.mutate()}>
            {t('mine.split.run', { defaultValue: 'Split by material' })}
          </Button>
        </div>
      )}
      {drive && (drive.faces > 0 || drive.profiles > 0) && (
        <p className="text-sm" data-testid="mine-drive">
          {t('mine.drive.summary', {
            defaultValue: 'Advance {{a}} m from {{f}} face pickups · {{p}} profiles, mean {{mean}} m² against design {{design}} m², overbreak {{o}} %',
            a: n(drive.advance_m, 1),
            f: drive.faces,
            p: drive.profiles,
            mean: n(drive.mean_actual_m2, 1),
            design: n(drive.design_area_m2, 1),
            o: n(drive.overbreak_pct, 1),
          })}
        </p>
      )}
    </div>
  );
}
