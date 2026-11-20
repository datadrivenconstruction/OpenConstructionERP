// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Grid against ground (combined scale factor) and the local site grid tie.
 * The chip says how far a taped distance differs from the grid one; the
 * dialog solves the site grid from common points and shows each residual
 * before anything is saved.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Ruler, Trash2 } from 'lucide-react';
import { Button, WideModal } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fmtNumber } from '@/shared/lib/formatters';
import {
  getGeodesy,
  getScaleFactor,
  setGeodesy,
  solveLocalGrid,
  type Geodesy,
  type LocalGridPoint,
  type LocalGridSolution,
  type ScaleFactor,
} from './api';

/** Grid/ground line in plain numbers; the format is fixed so a sheet and the screen read the same. */
export function gridGroundText(sf: ScaleFactor): { csf: string; grid: string; ground: string; mm: string } {
  return {
    csf: fmtNumber(sf.csf, 8),
    grid: fmtNumber(sf.distance_m, 3),
    ground: fmtNumber(sf.ground_m, 3),
    mm: Math.round(sf.diff_mm).toString(),
  };
}

export function GridGroundChip({ projectId, distance }: { projectId: string; distance?: number }) {
  const { t } = useTranslation();
  const sf = useQuery({
    queryKey: ['survey', 'scale-factor', projectId, distance ?? 0],
    queryFn: () => getScaleFactor(projectId, distance),
    enabled: !!projectId,
  });
  if (!sf.data) return null;
  const v = gridGroundText(sf.data);
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-border-light px-2.5 py-0.5 text-xs"
      data-testid="survey-grid-ground"
      title={t('survey.geodesy.csf_tip', {
        defaultValue: 'Combined scale factor {{csf}} (k {{k}}, h {{h}} m). Distances taped on site are ground; plans and stake sheets are grid.',
        csf: v.csf,
        k: fmtNumber(sf.data.k, 8),
        h: fmtNumber(sf.data.height_m, 1),
      })}
    >
      <Ruler size={12} aria-hidden />
      <bdi dir="ltr">
        {t('survey.geodesy.grid_ground', {
          defaultValue: '{{grid}} m grid = {{ground}} m ground ({{mm}} mm)',
          grid: v.grid,
          ground: v.ground,
          mm: v.mm,
        })}
      </bdi>
    </span>
  );
}

interface Row {
  point_id: string;
  x: string;
  y: string;
  e: string;
  n: string;
  use: boolean;
}

const EMPTY_ROW: Row = { point_id: '', x: '', y: '', e: '', n: '', use: true };
const NUM = 'oe-input w-full font-mono text-xs';

function num(value: string): number {
  const v = Number(value.trim().replace(',', '.'));
  return Number.isFinite(v) ? v : 0;
}

/** Rows with an id become common points; coordinates accept a decimal comma. */
export function rowsToPoints(rows: Row[]): LocalGridPoint[] {
  return rows
    .filter((r) => r.point_id.trim())
    .map((r) => ({ point_id: r.point_id.trim(), x: num(r.x), y: num(r.y), e: num(r.e), n: num(r.n), use: r.use }));
}

const toRow = (p: LocalGridPoint): Row => ({ point_id: p.point_id, x: String(p.x), y: String(p.y), e: String(p.e), n: String(p.n), use: p.use });

export function LocalGridDialog({ open, projectId, onClose }: { open: boolean; projectId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const geo = useQuery({ queryKey: ['survey', 'geodesy', projectId], queryFn: () => getGeodesy(projectId), enabled: open });
  const [rows, setRows] = useState<Row[]>([]);
  const [apply, setApply] = useState(false);
  const [tol, setTol] = useState('');
  const [solution, setSolution] = useState<LocalGridSolution | null>(null);

  useEffect(() => {
    if (!open || !geo.data) return;
    const g = geo.data;
    setRows(g.local_points.length ? g.local_points.map(toRow) : [{ ...EMPTY_ROW }, { ...EMPTY_ROW }]);
    setApply(g.apply_local_grid);
    setTol(g.residual_tol_mm != null ? String(g.residual_tol_mm) : '');
    setSolution(g.solution);
  }, [open, geo.data]);

  const filled = rowsToPoints(rows);
  const solve = useMutation({
    mutationFn: () => solveLocalGrid(filled),
    onSuccess: setSolution,
    onError: (e) => {
      setSolution(null);
      addToast({ type: 'error', title: getErrorMessage(e) });
    },
  });
  const save = useMutation({
    mutationFn: () => {
      const g = geo.data as Geodesy;
      return setGeodesy(projectId, {
        linear_unit: g.linear_unit,
        local_grid_epsg: g.local_grid_epsg,
        local_points: filled,
        apply_local_grid: apply,
        residual_tol_mm: tol.trim() ? num(tol) : null,
        scale_tol_ppm: g.scale_tol_ppm,
        csf_height_m: g.csf_height_m,
        reference_distance_m: g.reference_distance_m,
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['survey'] });
      addToast({ type: 'success', title: t('survey.geodesy.saved', { defaultValue: 'Local grid saved' }) });
      onClose();
    },
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });

  const edit = (i: number, patch: Partial<Row>) => {
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    setSolution(null);
  };
  const tolValue = tol.trim() ? num(tol) : null;
  const residual = (id: string) => solution?.residuals.find((r) => r.point_id === id.trim());

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="survey-local-grid"
      title={t('survey.geodesy.local_title', { defaultValue: 'Local site grid' })}
      subtitle={t('survey.geodesy.local_subtitle', {
        defaultValue: 'Points known in both the site grid (X, Y) and the national grid (E, N). Two fix the grid; three or more show how well it fits.',
      })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="secondary" loading={solve.isPending} disabled={filled.length < 2} onClick={() => solve.mutate()}>
            {t('survey.geodesy.solve', { defaultValue: 'Solve' })}
          </Button>
          <Button variant="primary" loading={save.isPending} disabled={!geo.data || (filled.length > 0 && filled.length < 2)} onClick={() => save.mutate()}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-content-secondary">
              <th className="text-start font-medium">{t('survey.geodesy.col_id', { defaultValue: 'Point' })}</th>
              <th className="text-start font-medium">X</th>
              <th className="text-start font-medium">Y</th>
              <th className="text-start font-medium">E</th>
              <th className="text-start font-medium">N</th>
              <th className="text-start font-medium">{t('survey.geodesy.col_use', { defaultValue: 'Fit' })}</th>
              <th className="text-end font-medium">{t('survey.geodesy.col_residual', { defaultValue: 'Residual, mm' })}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const res = residual(r.point_id);
              const over = res && tolValue != null && res.r_mm > tolValue;
              return (
                <tr key={i}>
                  <td className="pe-1 py-0.5">
                    <input className={NUM} value={r.point_id} onChange={(e) => edit(i, { point_id: e.target.value })} aria-label="ID" />
                  </td>
                  {(['x', 'y', 'e', 'n'] as const).map((k) => (
                    <td key={k} className="pe-1 py-0.5">
                      <input
                        className={NUM}
                        inputMode="decimal"
                        value={r[k]}
                        onChange={(e) => edit(i, { [k]: e.target.value })}
                        aria-label={k.toUpperCase()}
                      />
                    </td>
                  ))}
                  <td className="text-center">
                    <input type="checkbox" checked={r.use} onChange={(e) => edit(i, { use: e.target.checked })} />
                  </td>
                  <td className={`text-end font-mono text-xs ${over ? 'text-semantic-warning' : ''}`}>{res ? fmtNumber(res.r_mm, 1) : '-'}</td>
                  <td className="text-end">
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={<Trash2 size={14} />}
                      aria-label={t('common.delete', { defaultValue: 'Delete' })}
                      onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <Button size="sm" variant="ghost" icon={<Plus size={14} />} onClick={() => setRows((rs) => [...rs, { ...EMPTY_ROW }])}>
          {t('survey.geodesy.add_point', { defaultValue: 'Add point' })}
        </Button>

        {solution && (
          <p className="text-sm" data-testid="survey-local-solution">
            {t('survey.geodesy.solution', {
              defaultValue: 'Scale {{ppm}} ppm, rotation {{rot}}°, RMS {{rms}} mm, fitted points: {{n}}.',
              ppm: fmtNumber(solution.scale_ppm, 1),
              rot: fmtNumber(solution.rotation_deg, 4),
              rms: fmtNumber(solution.rms_mm, 1),
              n: solution.fitted,
            })}
          </p>
        )}

        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs text-content-secondary">
            {t('survey.geodesy.tolerance', { defaultValue: 'Residual tolerance, mm (optional)' })}
            <input className="oe-input mt-1 w-full" inputMode="decimal" value={tol} onChange={(e) => setTol(e.target.value)} />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={apply} onChange={(e) => setApply(e.target.checked)} />
            {t('survey.geodesy.apply', { defaultValue: 'Use for imports and exports in site coordinates' })}
          </label>
        </div>
      </div>
    </WideModal>
  );
}
