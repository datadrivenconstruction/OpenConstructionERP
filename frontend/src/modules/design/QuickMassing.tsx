// Design module (ERP side of the design editor link).
/**
 * Quick estimate from a short brief: type, GFA and storeys give a first massing, a priced elemental breakdown in the
 * project currency and the programme phases in one screen. Every number names its source (brief, generator, country
 * data, benchmark, formula); a value no source gives stays empty and flagged. Nothing is stored.
 */
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Calculator, Loader2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { fmtCurrency, fmtNumber, fmtQuantity } from '@/shared/lib/formatters';
import { tr } from './BriefFields';
import { fetchQuickTypes, runQuick, type Provenance, type Quality, type QuickBrief, type QuickResult } from './startApi';

function provText(t: ReturnType<typeof useTranslation>['t'], p: Provenance): string {
  return [tr(t, `design.quick.src.${p.source}`), p.ref, p.formula, p.note].filter(Boolean).join(' · ');
}

const QUALITIES: Quality[] = ['economy', 'standard', 'high'];
const OPTIONAL = ['floor_height_m', 'depth_m', 'grid_m', 'wwr', 'slab_zone_m', 'plot_area_m2', 'max_height_m'] as const;

function num(s: string): number | undefined {
  const v = Number(s.replace(',', '.'));
  return s.trim() && Number.isFinite(v) ? v : undefined;
}

/** Fields the brief cannot be run without, or whose value is not a positive number; empty optional fields are fine. */
function invalidFields(form: Record<string, string>): string[] {
  const bad: string[] = [];
  for (const k of ['gfa_m2', 'storeys']) { const v = num(form[k] ?? ''); if (v === undefined || v <= 0) bad.push(k); }
  for (const k of [...OPTIONAL, 'fx_rate']) {
    const s = form[k] ?? '';
    if (!s.trim()) continue;
    const v = num(s);
    if (v === undefined || v < 0 || (v === 0 && k !== 'wwr' && k !== 'slab_zone_m')) bad.push(k);
  }
  return bad;
}

/** A 422 from request validation names the fields; anything else is shown through its coded message. */
function serverFields(err: unknown): string[] {
  if (!(err instanceof ApiError) || err.status !== 422) return [];
  const detail = (err.body as { detail?: unknown } | null)?.detail;
  if (!Array.isArray(detail)) return [];
  return detail.map((d) => (Array.isArray(d?.loc) ? String(d.loc[d.loc.length - 1]) : '')).filter(Boolean);
}

export function QuickMassing({ projectId, country }: { projectId: string; country?: string | null }) {
  const { t } = useTranslation();
  const types = useQuery({ queryKey: ['design-quick-types'], queryFn: fetchQuickTypes });
  const [form, setForm] = useState<Record<string, string>>({ building_type: 'office', gfa_m2: '2400', storeys: '4', quality: 'standard' });
  const run = useMutation({ mutationFn: (b: QuickBrief) => runQuick(projectId, b) });
  const [bad, setBad] = useState<string[]>([]);
  const set = (k: string, v: string) => { setForm((f) => ({ ...f, [k]: v })); setBad((b) => b.filter((x) => x !== k)); };

  const submit = () => {
    const wrong = invalidFields(form);
    setBad(wrong);
    if (wrong.length) return;
    const brief: QuickBrief = {
      building_type: form.building_type!, gfa_m2: num(form.gfa_m2!)!, storeys: Math.trunc(num(form.storeys!)!),
      quality: (form.quality as Quality) ?? 'standard', country: country ?? undefined,
      fx_rate: form.fx_rate?.trim() || undefined,
    };
    for (const k of OPTIONAL) { const v = num(form[k] ?? ''); if (v !== undefined) brief[k] = v; }
    run.mutate(brief);
  };

  const wrongFields = [...bad, ...serverFields(run.error)];
  const field = (k: string, input: React.ReactNode) => (
    <label key={k} className="flex flex-col gap-1 text-xs text-content-secondary">
      {tr(t, `design.quick.field.${k}`)}{input}
      {wrongFields.includes(k) && <span role="alert" className="text-semantic-error">{tr(t, 'design.quick.field_invalid')}</span>}
    </label>
  );
  const box = 'rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary';
  const r = run.data;

  return (
    <section className="rounded-xl border border-border bg-surface-elevated p-5 flex flex-col gap-4" aria-labelledby="quick-title">
      <div>
        <h2 id="quick-title" className="text-base font-semibold text-content-primary">{tr(t, 'design.quick.title')}</h2>
        <p className="text-sm text-content-secondary">{tr(t, 'design.quick.subtitle')}</p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {field('building_type', (
          <select className={box} value={form.building_type} onChange={(e) => set('building_type', e.target.value)}>
            {(types.data?.types ?? [{ id: 'office' }]).map((x) => (
              <option key={x.id} value={x.id}>{tr(t, `design.quick.type.${x.id}`)}</option>
            ))}
          </select>
        ))}
        {field('gfa_m2', <input className={box} inputMode="decimal" value={form.gfa_m2} onChange={(e) => set('gfa_m2', e.target.value)} />)}
        {field('storeys', <input className={box} inputMode="numeric" value={form.storeys} onChange={(e) => set('storeys', e.target.value)} />)}
        {field('quality', (
          <select className={box} value={form.quality} onChange={(e) => set('quality', e.target.value)}>
            {QUALITIES.map((q) => <option key={q} value={q}>{tr(t, `design.quick.quality.${q}`)}</option>)}
          </select>
        ))}
        {OPTIONAL.map((k) => field(k, <input className={box} inputMode="decimal" value={form[k] ?? ''} onChange={(e) => set(k, e.target.value)} />))}
        {field('fx_rate', (
          <input className={box} inputMode="decimal" value={form.fx_rate ?? ''}
            placeholder={r?.cost?.band_currency && r.cost.currency ? `1 ${r.cost.band_currency} = ? ${r.cost.currency}` : undefined}
            onChange={(e) => set('fx_rate', e.target.value)} />
        ))}
      </div>
      <div>
        <Button onClick={submit} disabled={run.isPending}
          icon={run.isPending ? <Loader2 size={14} className="animate-spin" /> : <Calculator size={14} />}>
          {tr(t, 'design.quick.run')}
        </Button>
      </div>
      {run.isError && (
        <p role="alert" className="text-sm text-semantic-error">
          {serverFields(run.error).length ? tr(t, 'design.quick.fields_invalid') : getErrorMessage(run.error)}
        </p>
      )}
      {r && <QuickResultView r={r} onUse={(k, v) => set(k, String(v))} />}
    </section>
  );
}

function QuickResultView({ r, onUse }: { r: QuickResult; onUse: (k: string, v: number | string) => void }) {
  const { t } = useTranslation();
  const cur = r.cost?.currency ?? undefined;
  return (
    <div className="flex flex-col gap-4">
      {r.issues.length > 0 && (
        <ul role="alert" className="flex flex-col gap-1 text-sm">
          {r.issues.map((i) => (
            <li key={i.code} className={i.severity === 'error' ? 'text-semantic-error' : 'text-semantic-warning'}>
              {tr(t, `design.quick.issue.${i.code}`, i.params)}
            </li>
          ))}
        </ul>
      )}
      {r.model && (
        <>
          {r.generator === false && <p className="text-xs text-content-tertiary">{tr(t, 'design.quick.no_generator')}</p>}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="quick-kpis">
            <Kpi label={tr(t, 'design.quick.kpi.footprint')}
              value={`${fmtNumber(r.model.footprint.width_m, 1)} × ${fmtNumber(r.model.footprint.depth_m, 1)} ${tr(t, 'design.quick.unit_m')}`} />
            <Kpi label={tr(t, 'design.quick.kpi.height')} value={`${fmtNumber(r.model.height_m, 1)} ${tr(t, 'design.quick.unit_m')}`} />
            <Kpi label={tr(t, 'design.quick.kpi.total')} value={r.cost?.total ? fmtCurrency(r.cost.total, cur) : '—'}
              hint={r.cost?.per_m2 ? tr(t, 'design.quick.per_m2', { value: fmtCurrency(r.cost.per_m2, cur) }) : undefined} />
            <Kpi label={tr(t, 'design.quick.kpi.programme')}
              value={r.schedule?.total_days != null ? tr(t, 'design.quick.days', { count: r.schedule.total_days }) : '—'} />
          </div>
          {r.cost?.reason && <p className="text-sm text-content-secondary">{tr(t, `design.quick.reason.${r.cost.reason}`)}</p>}
          {r.cost?.benchmark && (
            <p className="text-sm text-content-secondary" title={r.cost.benchmark.ref}>
              {tr(t, 'design.quick.band_range', {
                low: fmtCurrency(r.cost.benchmark.low, cur), high: fmtCurrency(r.cost.benchmark.high, cur) })}
              {r.cost.needs_expert_review && ` ${tr(t, 'design.quick.review')}`}
            </p>
          )}
          <div className="grid md:grid-cols-2 gap-4">
            <table className="text-sm">
              <caption className="text-left text-xs font-semibold text-content-secondary pb-1">{tr(t, 'design.quick.quantities')}</caption>
              <tbody>
                {r.model.quantities.map((q) => (
                  <tr key={q.code} className="border-t border-border-light" title={provText(t, q.provenance)}>
                    <td className="py-1">{tr(t, `design.quick.q.${q.code}`)}</td>
                    <td className="py-1 text-right tabular-nums">
                      {q.value == null ? <span className="text-semantic-warning">{tr(t, 'design.quick.no_source')}</span> : `${fmtQuantity(q.value)} ${q.unit}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {r.cost?.lines && r.cost.lines.length > 0 && (
              <table className="text-sm">
                <caption className="text-left text-xs font-semibold text-content-secondary pb-1">{tr(t, 'design.quick.cost_lines')}</caption>
                <tbody>
                  {r.cost.lines.map((l) => (
                    <tr key={l.code} className="border-t border-border-light" title={provText(t, l.provenance)}>
                      <td className="py-1">{`KG ${l.code}`}</td>
                      <td className="py-1 text-right tabular-nums">{l.quantity == null ? '—' : `${fmtQuantity(l.quantity)} ${l.unit}`}</td>
                      <td className="py-1 text-right tabular-nums">{fmtCurrency(l.amount, cur)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
      {r.schedule && (
        <div className="text-sm">
          <p className="text-xs font-semibold text-content-secondary">{tr(t, 'design.quick.kpi.programme')}</p>
          {r.schedule.reason === 'rate_missing' && <p className="text-xs text-semantic-warning">{tr(t, 'design.quick.rate_missing')}</p>}
          <ul className="mt-1 flex flex-col gap-0.5">
            {r.schedule.phases.map((p) => (
              <li key={p.code}>{tr(t, `design.quick.phase.${p.code}`)}: {p.days == null || p.start_day == null
                ? tr(t, 'design.quick.no_source') : tr(t, 'design.quick.phase_span', { start: p.start_day, days: p.days })}</li>
            ))}
          </ul>
        </div>
      )}
      {r.suggestions.length > 0 && (
        <div className="text-sm">
          <p className="text-xs font-semibold text-content-secondary">{tr(t, 'design.quick.suggestions')}</p>
          <ul className="mt-1 flex flex-col gap-1">
            {r.suggestions.map((s) => (
              <li key={s.pointer} className="flex items-center gap-2">
                <span>{tr(t, `design.quick.s.${s.pointer}`)}: {String(s.value)}</span>
                <span className="text-xs text-content-tertiary">{provText(t, s.provenance)}</span>
                {['floor_height_m', 'depth_m', 'grid_m'].includes(s.pointer) && (
                  <Button size="sm" variant="ghost" onClick={() => onUse(s.pointer, String(s.value))}>{tr(t, 'design.quick.use')}</Button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border-light p-3">
      <div className="text-xs text-content-tertiary">{label}</div>
      <div className="text-lg font-semibold tabular-nums text-content-primary">{value}</div>
      {hint && <div className="text-xs text-content-secondary">{hint}</div>}
    </div>
  );
}
