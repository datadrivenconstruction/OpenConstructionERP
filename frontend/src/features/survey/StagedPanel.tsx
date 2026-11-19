// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Staged volumes: a chain of surfaces over time (or a strip of a set depth),
 * cut and fill for each step, with loose and compacted factors per material.
 * Nothing is saved; the numbers are worked out on request.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Plus, Trash2, TrendingUp } from 'lucide-react';
import { Button, Card, EmptyState } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { CUT_COLOUR, FILL_COLOUR } from './SurveyPlan';
import { computeStaged, formatM3, type MaterialFactors, type StageInput, type StagedResult, type Surface } from './volumesApi';

export interface StageRow {
  label: string;
  kind: 'surface' | 'strip';
  surface_id: string;
  depth: string;
  date: string;
  material: string;
}

const num = (v: string) => (v.trim() === '' ? null : Number(v.replace(',', '.')));

/** Rows to the request, or null while a row is incomplete. The first stage must be a surface. */
export function stagesBody(rows: StageRow[]): StageInput[] | null {
  if (rows.length < 2 || rows[0]?.kind !== 'surface') return null;
  const out: StageInput[] = [];
  for (const [i, r] of rows.entries()) {
    const label = r.label.trim() || `#${i + 1}`;
    if (r.kind === 'surface') {
      if (!r.surface_id) return null;
      out.push({ label, surface_id: r.surface_id, surveyed_on: r.date, material: r.material.trim() });
    } else {
      const d = num(r.depth);
      if (d == null || !Number.isFinite(d) || d <= 0) return null;
      out.push({ label, strip_depth_m: d, surveyed_on: r.date, material: r.material.trim() });
    }
  }
  return out;
}

/** Factor inputs to the request: blank or invalid entries are left out, never sent as zero. */
export function factorsBody(input: Record<string, { loose: string; compacted: string }>): Record<string, MaterialFactors> {
  const out: Record<string, MaterialFactors> = {};
  for (const [material, f] of Object.entries(input)) {
    const loose = num(f.loose);
    const compacted = num(f.compacted);
    const item: MaterialFactors = {};
    if (loose != null && loose > 0) item.loose = loose;
    if (compacted != null && compacted > 0) item.compacted = compacted;
    if (Object.keys(item).length) out[material] = item;
  }
  return out;
}

const blank = (kind: StageRow['kind']): StageRow => ({ label: '', kind, surface_id: '', depth: '', date: '', material: '' });

export function StagedPanel({ projectId, surfaces }: { projectId: string; surfaces: Surface[] }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const addToast = useToastStore((s) => s.addToast);
  const [rows, setRows] = useState<StageRow[]>([blank('surface'), blank('surface')]);
  const [factors, setFactors] = useState<Record<string, { loose: string; compacted: string }>>({});
  const [result, setResult] = useState<StagedResult | null>(null);
  const materials = [...new Set(rows.slice(1).map((r) => r.material.trim()).filter(Boolean))];
  const body = stagesBody(rows);

  const run = useMutation({
    mutationFn: () => computeStaged(projectId, { stages: body!, factors: factorsBody(factors) }, lang),
    onSuccess: setResult,
    onError: (e) => addToast({ type: 'error', title: getErrorMessage(e) }),
  });
  const patch = (i: number, p: Partial<StageRow>) => setRows((rs) => rs.map((r, k) => (k === i ? { ...r, ...p } : r)));

  if (surfaces.length === 0) {
    return (
      <EmptyState
        icon={<TrendingUp size={24} />}
        title={t('volumes.staged.empty', { defaultValue: 'Staged volumes need at least one surface: the ground before work starts.' })}
      />
    );
  }
  const peak = Math.max(1, ...(result?.steps ?? []).flatMap((s) => [s.cut_m3, s.fill_m3]));

  return (
    <div className="space-y-4" data-testid="volumes-staged">
      <Card className="p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="oe-table w-full text-sm">
            <thead>
              <tr>
                <th>#</th>
                <th>{t('volumes.staged.stage', { defaultValue: 'Stage' })}</th>
                <th>{t('volumes.staged.source', { defaultValue: 'Surface or strip' })}</th>
                <th>{t('volumes.staged.date', { defaultValue: 'Surveyed on' })}</th>
                <th title={t('volumes.staged.material_tip', { defaultValue: 'What is dug or placed between the previous stage and this one.' })}>
                  {t('volumes.field.material', { defaultValue: 'Material' })}
                </th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="text-content-tertiary">{i + 1}</td>
                  <td>
                    <input className="oe-input w-36" value={r.label} onChange={(e) => patch(i, { label: e.target.value })} />
                  </td>
                  <td>
                    <div className="flex gap-1">
                      {i > 0 && (
                        <select className="oe-input w-28" value={r.kind} onChange={(e) => patch(i, { kind: e.target.value as StageRow['kind'] })}>
                          <option value="surface">{t('volumes.staged.kind_surface', { defaultValue: 'Surface' })}</option>
                          <option value="strip">{t('volumes.staged.kind_strip', { defaultValue: 'Strip (m)' })}</option>
                        </select>
                      )}
                      {r.kind === 'surface' ? (
                        <select className="oe-input w-48" value={r.surface_id} onChange={(e) => patch(i, { surface_id: e.target.value })}>
                          <option value="">-</option>
                          {surfaces.map((s) => (
                            <option key={s.id} value={s.id}>{`${s.code} ${s.name}`}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          className="oe-input w-24"
                          inputMode="decimal"
                          dir="ltr"
                          value={r.depth}
                          onChange={(e) => patch(i, { depth: e.target.value })}
                          placeholder="0.30"
                        />
                      )}
                    </div>
                  </td>
                  <td>
                    <input type="date" className="oe-input w-40" value={r.date} onChange={(e) => patch(i, { date: e.target.value })} />
                  </td>
                  <td>
                    {i > 0 && <input className="oe-input w-32" value={r.material} onChange={(e) => patch(i, { material: e.target.value })} />}
                  </td>
                  <td className="text-right">
                    {rows.length > 2 && (
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Trash2 size={14} />}
                        onClick={() => setRows((rs) => rs.filter((_, k) => k !== i))}
                        aria-label={t('common.delete', { defaultValue: 'Delete' })}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap gap-2 border-t border-border-light p-3">
          <Button size="sm" variant="secondary" icon={<Plus size={14} />} disabled={rows.length >= 24} onClick={() => setRows((rs) => [...rs, blank('surface')])}>
            {t('volumes.staged.add_stage', { defaultValue: 'Add stage' })}
          </Button>
          <Button size="sm" variant="secondary" icon={<Plus size={14} />} disabled={rows.length >= 24} onClick={() => setRows((rs) => [...rs, blank('strip')])}>
            {t('volumes.staged.add_strip', { defaultValue: 'Add strip' })}
          </Button>
          <Button variant="primary" className="ms-auto" disabled={!body} loading={run.isPending} onClick={() => run.mutate()} data-testid="staged-compute">
            {t('volumes.staged.compute', { defaultValue: 'Work out volumes' })}
          </Button>
        </div>
      </Card>

      {materials.length > 0 && (
        <Card className="p-3">
          <div className="mb-2 text-sm font-medium">{t('volumes.staged.factors', { defaultValue: 'Factors per material' })}</div>
          <p className="mb-2 text-xs text-content-tertiary">
            {t('volumes.staged.factors_hint', {
              defaultValue: 'From your geotechnical report or contract. Loose factor turns cut into truck volume; compacted factor turns fill into bank volume needed.',
            })}
          </p>
          <table className="oe-table text-sm">
            <thead>
              <tr>
                <th>{t('volumes.field.material', { defaultValue: 'Material' })}</th>
                <th>{t('volumes.staged.loose', { defaultValue: 'Loose factor' })}</th>
                <th>{t('volumes.staged.compacted', { defaultValue: 'Compacted factor' })}</th>
              </tr>
            </thead>
            <tbody>
              {materials.map((m) => (
                <tr key={m}>
                  <td>{m}</td>
                  {(['loose', 'compacted'] as const).map((k) => (
                    <td key={k}>
                      <input
                        className="oe-input w-24"
                        inputMode="decimal"
                        dir="ltr"
                        value={factors[m]?.[k] ?? ''}
                        onChange={(e) =>
                          setFactors((f) => ({ ...f, [m]: { loose: f[m]?.loose ?? '', compacted: f[m]?.compacted ?? '', [k]: e.target.value } }))
                        }
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {result && (
        <Card className="p-0 overflow-hidden" data-testid="staged-result">
          {result.findings.length > 0 && (
            <ul className="space-y-1 border-b border-border-light p-3 text-sm">
              {result.findings.map((f, i) => (
                <li key={i}>
                  <span className="font-mono text-xs text-content-tertiary">{f.rule_id}</span> {f.message}
                  {f.suggestion && <span className="text-content-secondary"> {f.suggestion}</span>}
                </li>
              ))}
            </ul>
          )}
          <div className="overflow-x-auto">
            <table className="oe-table w-full text-sm">
              <thead>
                <tr>
                  <th>{t('volumes.staged.step', { defaultValue: 'Step' })}</th>
                  <th>{t('volumes.field.material', { defaultValue: 'Material' })}</th>
                  <th className="text-right">{t('volumes.field.cut', { defaultValue: 'Cut' })} (m³)</th>
                  <th className="text-right">{t('volumes.field.fill', { defaultValue: 'Fill' })} (m³)</th>
                  <th className="text-right">{t('volumes.staged.loose_cut', { defaultValue: 'Loose cut' })} (m³)</th>
                  <th className="text-right">{t('volumes.staged.bank_needed', { defaultValue: 'Bank fill needed' })} (m³)</th>
                  <th className="text-right">{t('volumes.staged.cumulative', { defaultValue: 'Cumulative cut / fill' })}</th>
                  <th className="w-48" />
                </tr>
              </thead>
              <tbody>
                {result.steps.map((s) => (
                  <tr key={s.index}>
                    <td>{`${s.from_label} → ${s.to_label}`}</td>
                    <td>{s.material}</td>
                    <td className="text-right font-mono"><bdi dir="ltr">{formatM3(s.cut_m3, lang)}</bdi></td>
                    <td className="text-right font-mono"><bdi dir="ltr">{formatM3(s.fill_m3, lang)}</bdi></td>
                    <td className="text-right font-mono"><bdi dir="ltr">{s.cut_loose_m3 == null ? '-' : formatM3(s.cut_loose_m3, lang)}</bdi></td>
                    <td className="text-right font-mono">
                      <bdi dir="ltr">{s.fill_bank_needed_m3 == null ? '-' : formatM3(s.fill_bank_needed_m3, lang)}</bdi>
                    </td>
                    <td className="text-right font-mono">
                      <bdi dir="ltr">{`${formatM3(s.cumulative_cut_m3, lang)} / ${formatM3(s.cumulative_fill_m3, lang)}`}</bdi>
                    </td>
                    <td aria-hidden>
                      <div className="h-2 rounded-sm" style={{ width: `${(100 * s.cut_m3) / peak}%`, backgroundColor: CUT_COLOUR }} />
                      <div className="mt-0.5 h-2 rounded-sm" style={{ width: `${(100 * s.fill_m3) / peak}%`, backgroundColor: FILL_COLOUR }} />
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="font-medium">
                  <td colSpan={2}>{t('volumes.staged.total', { defaultValue: 'Total' })}</td>
                  <td className="text-right font-mono"><bdi dir="ltr">{formatM3(result.total_cut_m3, lang)}</bdi></td>
                  <td className="text-right font-mono"><bdi dir="ltr">{formatM3(result.total_fill_m3, lang)}</bdi></td>
                  <td colSpan={4} />
                </tr>
              </tfoot>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
