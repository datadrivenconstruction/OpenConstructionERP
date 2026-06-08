import { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { normalizeListResponse } from '@/shared/lib/apiHelpers';
import {
  ShieldAlert, Plus, ChevronRight, ArrowLeft, DollarSign,
  AlertTriangle, Shield, Trash2, X, Search, Filter, CalendarDays, TrendingUp,
  LayoutGrid, Activity,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, ConfirmDialog, DismissibleInfo, IntroRichText, RecoveryCard, SkeletonTable, SkeletonCard } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { MultiCurrencyTotal } from '@/shared/ui/MultiCurrencyTotal';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { PlanningCrossLinks } from '@/features/schedule/PlanningCrossLinks';
import SimilarItemsPanel from '@/shared/ui/SimilarItemsPanel';
import { UserSearchInput } from '@/shared/ui/UserSearchInput';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { MonteCarloTab } from './MonteCarloTab';

const RISK_TAB_IDS = ['register', 'montecarlo'] as const;
type RiskTab = (typeof RISK_TAB_IDS)[number];

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Project { id: string; name: string; currency: string }

interface RiskItem {
  id: string; project_id: string; code: string; title: string; description: string;
  category: string; probability: number; impact_cost: number; impact_schedule_days: number;
  impact_severity: string; risk_score: number; status: string; mitigation_strategy: string;
  contingency_plan: string; owner_name: string; owner_user_id?: string | null;
  response_cost: number; currency: string;
  probability_score?: number | null; impact_score_cost?: number | null;
  // Auto-escalation (TOP-30 #24): set server-side when the risk crosses the
  // escalation threshold or its review date lapses.
  escalated?: boolean;
  escalated_at?: string | null;
  escalation_trigger?: string | null;
  escalation_threshold?: number | null;
  metadata: Record<string, unknown>; created_at: string; updated_at: string;
}

interface RiskSummary {
  total_risks: number; by_status: Record<string, number>; by_category: Record<string, number>;
  high_critical_count: number; total_exposure: number; mitigated_count: number; currency: string;
  // Per-currency exposure breakdown. The backend deliberately returns
  // total_exposure = 0 when risks span more than one currency (it refuses
  // to sum unconverted amounts) and puts the real figures here. The UI
  // must read this instead of rendering a misleading "0".
  exposure_by_currency?: Record<string, number>;
}

interface MatrixCell { probability_level: string; impact_level: string; count: number; risk_ids: string[] }

/* ── Constants ─────────────────────────────────────────────────────────── */

// Must mirror the backend STATUS_VALUES vocabulary (schemas.py) exactly —
// seed/demo data uses 'open', 'monitoring' and 'mitigated', which were
// previously missing here, so seeded risks couldn't be filtered, their
// status badges fell back to neutral, and the edit <select> dropped the
// current value (silently changing it on save).
const STATUS_COLORS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  identified: 'blue', assessed: 'warning', mitigating: 'success', monitoring: 'warning',
  mitigated: 'success', open: 'blue', closed: 'neutral', occurred: 'error',
};
// Mirror the backend category set used by seed data (which includes
// 'procurement') so seeded risks remain filterable.
const CATEGORIES = ['technical', 'financial', 'schedule', 'regulatory', 'environmental', 'safety', 'procurement'];
const SEVERITIES = ['low', 'medium', 'high', 'critical'];
const STATUSES = ['identified', 'assessed', 'mitigating', 'monitoring', 'mitigated', 'open', 'closed', 'occurred'];
const PROB_LEVELS = ['0.9', '0.7', '0.5', '0.3', '0.1'];
function getProbLabels(t: (key: string, opts?: Record<string, unknown>) => string): Record<string, string> {
  return {
    '0.9': t('risk.probability_very_high', { defaultValue: 'Very High' }),
    '0.7': t('risk.probability_high', { defaultValue: 'High' }),
    '0.5': t('risk.probability_medium', { defaultValue: 'Medium' }),
    '0.3': t('risk.probability_low', { defaultValue: 'Low' }),
    '0.1': t('risk.probability_very_low', { defaultValue: 'Very Low' }),
  };
}
// Must mirror the backend `/matrix/` canonical impact axis exactly
// (service.py builds 5 levels: very_low..critical). Dropping `very_low`
// here silently hid every risk the backend bucketed into that column.
const IMPACT_LEVELS = ['very_low', 'low', 'medium', 'high', 'critical'];
const IMPACT_LABEL_FALLBACK: Record<string, string> = {
  very_low: 'Very Low', low: 'Low', medium: 'Medium', high: 'High', critical: 'Critical',
};

const selectCls = 'h-8 rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue transition-colors pr-7 appearance-none cursor-pointer';

function fmtCur(n: number, c = 'EUR') {
  const s = /^[A-Z]{3}$/.test(c) ? c : 'EUR';
  try { return new Intl.NumberFormat(getIntlLocale(), { style: 'currency', currency: s, minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n); }
  catch { return `${n.toFixed(0)} ${s}`; }
}

function matrixColor(prob: string, impact: string) {
  // Guard against missing/invalid probability — treat as 0 so the cell stays neutral
  const probNum = parseFloat(prob);
  const probValid = Number.isFinite(probNum) ? probNum : 0;
  // Guard against unknown impact values — default to 0 (not 1) so the cell is marked neutral
  // instead of silently treated as low-risk. Levels 1-5 mirror the backend
  // canonical impact axis (very_low..critical).
  const impactMap: Record<string, number> = {
    very_low: 1, low: 2, medium: 3, high: 4, critical: 5,
  };
  const impactNum = impactMap[impact] ?? 0;
  // score range: 0.1*1=0.1 .. 0.9*5=4.5
  const score = probValid * impactNum;
  if (score === 0) return 'bg-surface-secondary text-content-quaternary';
  if (score >= 2.7) return 'bg-red-500/80 text-white';
  if (score >= 1.5) return 'bg-orange-400/80 text-white';
  if (score >= 0.6) return 'bg-yellow-400/80 text-gray-900';
  return 'bg-green-400/70 text-gray-900';
}

/* ── Risk Matrix ──────────────────────────────────────────────────────── */

function RiskMatrix({ cells }: { cells: MatrixCell[] }) {
  const { t } = useTranslation();
  const map = useMemo(() => {
    const m: Record<string, MatrixCell> = {};
    for (const c of cells) m[`${c.probability_level}|${c.impact_level}`] = c;
    return m;
  }, [cells]);

  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold text-content-primary mb-3">{t('risk.matrix', { defaultValue: 'Risk Matrix' })}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className="p-1 text-left text-content-tertiary w-20">{t('risk.probability', { defaultValue: 'Probability' })}</th>
              {IMPACT_LEVELS.map((i) => <th key={i} className="p-1 text-center text-content-tertiary">{t(`risk.impact_${i}`, { defaultValue: IMPACT_LABEL_FALLBACK[i] ?? i })}</th>)}
            </tr>
          </thead>
          <tbody>
            {PROB_LEVELS.map((p) => (
              <tr key={p}>
                <td className="p-1 text-content-secondary font-medium">{getProbLabels(t)[p]}</td>
                {IMPACT_LEVELS.map((i) => {
                  const c = map[`${p}|${i}`]?.count || 0;
                  return <td key={i} className="p-1"><div className={`flex items-center justify-center h-10 rounded-md text-sm font-bold ${c > 0 ? matrixColor(p, i) : 'bg-surface-secondary text-content-quaternary'}`}>{c > 0 ? c : ''}</div></td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex items-center gap-4 text-2xs text-content-tertiary">
        {[['bg-green-400/70', t('risk.legend_low', { defaultValue: 'Low' })], ['bg-yellow-400/80', t('risk.legend_medium', { defaultValue: 'Medium' })], ['bg-orange-400/80', t('risk.legend_high', { defaultValue: 'High' })], ['bg-red-500/80', t('risk.legend_critical', { defaultValue: 'Critical' })]].map(([bg, l]) => (
          <span key={l} className="flex items-center gap-1"><span className={`inline-block w-3 h-3 rounded ${bg}`} />{l}</span>
        ))}
      </div>
    </Card>
  );
}

/* ── 5x5 Risk Heatmap ────────────────────────────────────────────────── */

function heatmapColor(score: number): string {
  if (score >= 16) return 'bg-red-500 text-white';
  if (score >= 11) return 'bg-orange-500 text-white';
  if (score >= 6) return 'bg-yellow-400 text-gray-900';
  if (score >= 1) return 'bg-green-500 text-white';
  return 'bg-surface-secondary text-content-quaternary';
}

function RiskMatrixHeatmap({ risks }: { risks: RiskItem[] }) {
  const { t } = useTranslation();

  // Build a 5x5 grid: key = "prob|impact", value = count
  const grid = useMemo(() => {
    const map = new Map<string, number>();
    for (const r of risks) {
      const p = r.probability_score;
      const i = r.impact_score_cost;
      if (p != null && i != null && p >= 1 && p <= 5 && i >= 1 && i <= 5) {
        const key = `${p}|${i}`;
        map.set(key, (map.get(key) ?? 0) + 1);
      }
    }
    return map;
  }, [risks]);

  const probLabels = ['5', '4', '3', '2', '1'];
  const impactLabels = ['1', '2', '3', '4', '5'];

  return (
    <Card className="p-4 mb-6">
      <h3 className="text-sm font-semibold text-content-primary mb-3">
        {t('risk.heatmap', { defaultValue: 'Risk Matrix' })}
      </h3>
      <div className="overflow-x-auto">
        <table className="text-xs mx-auto">
          <thead>
            <tr>
              <th className="p-1 text-right text-content-tertiary w-20 pr-2">
                {t('risk.probability', { defaultValue: 'Probability' })}
              </th>
              {impactLabels.map((il) => (
                <th key={il} className="p-1 text-center text-content-tertiary w-12">{il}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {probLabels.map((pl) => (
              <tr key={pl}>
                <td className="p-1 text-right text-content-secondary font-medium pr-2">{pl}</td>
                {impactLabels.map((il) => {
                  const p = parseInt(pl, 10);
                  const i = parseInt(il, 10);
                  const score = p * i;
                  const count = grid.get(`${p}|${i}`) ?? 0;
                  return (
                    <td key={il} className="p-1">
                      <div
                        className={`flex items-center justify-center h-10 w-12 rounded-md text-sm font-bold ${
                          count > 0 ? heatmapColor(score) : 'bg-surface-secondary text-content-quaternary'
                        }`}
                        title={`P=${p} x I=${i} = ${score}${count > 0 ? `, ${count} ${t('risk.risks_count', { defaultValue: 'risk(s)' })}` : ''}`}
                      >
                        {count > 0 ? count : '-'}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td />
              <td colSpan={5} className="text-center text-content-tertiary text-2xs pt-1">
                {t('risk.impact', { defaultValue: 'Impact' })}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <div className="flex gap-4 mt-2 text-2xs text-content-tertiary justify-center">
        <span className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-green-500" /> {t('risk.low', { defaultValue: 'Low (1-5)' })}</span>
        <span className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-yellow-400" /> {t('risk.medium', { defaultValue: 'Medium (6-10)' })}</span>
        <span className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-orange-500" /> {t('risk.high', { defaultValue: 'High (11-15)' })}</span>
        <span className="flex items-center gap-1"><div className="w-3 h-3 rounded bg-red-500" /> {t('risk.critical', { defaultValue: 'Critical (16-25)' })}</span>
      </div>
    </Card>
  );
}

/* ── Input helper ──────────────────────────────────────────────────────── */

const inputCls = 'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls = 'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Create Dialog ─────────────────────────────────────────────────────── */

const INITIAL_RISK_FORM = { title: '', description: '', category: 'technical', probability: 0.5, impactSeverity: 'medium', impactCost: 0, scheduleDays: 0, ownerName: '', ownerUserId: '' };

function CreateDialog({ projectId, currency, onClose, onCreated }: { projectId: string; currency: string; onClose: () => void; onCreated: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [f, setF] = useState(INITIAL_RISK_FORM);
  const set = (k: string, v: unknown) => setF((p) => ({ ...p, [k]: v }));

  const mut = useMutation({
    mutationFn: () => apiPost<RiskItem>('/v1/risk/', {
      project_id: projectId,
      title: f.title,
      description: f.description,
      category: f.category,
      probability: f.probability,
      impact_severity: f.impactSeverity,
      impact_cost: f.impactCost,
      impact_schedule_days: f.scheduleDays,
      owner_name: f.ownerName,
      owner_user_id: f.ownerUserId || undefined,
      currency,
    }),
    onSuccess: () => { onCreated(); onClose(); addToast({ type: 'success', title: t('risk.created', { defaultValue: 'Risk created' }) }); },
    onError: (e: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" role="dialog" aria-modal="true" aria-labelledby="risk-create-title" onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl bg-surface-primary p-6 shadow-xl border border-border max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 id="risk-create-title" className="text-lg font-semibold text-content-primary">{t('risk.new', { defaultValue: 'New Risk' })}</h2>
          <button onClick={onClose} aria-label={t('common.close', { defaultValue: 'Close' })} className="text-content-tertiary hover:text-content-primary"><X size={18} /></button>
        </div>
        <div className="space-y-4">
          <div>
            <label htmlFor="risk-title" className="block text-sm font-medium text-content-primary mb-1.5">{t('common.title', { defaultValue: 'Title' })} *</label>
            <input id="risk-title" value={f.title} onChange={(e) => set('title', e.target.value)} placeholder={t('risk.title_placeholder', { defaultValue: 'e.g. Foundation soil instability' })} className={inputCls} />
          </div>
          <div>
            <label htmlFor="risk-description" className="block text-sm font-medium text-content-primary mb-1.5">{t('common.description', { defaultValue: 'Description' })}</label>
            <textarea id="risk-description" value={f.description} onChange={(e) => set('description', e.target.value)} rows={2} className={textareaCls} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="risk-category" className="block text-sm font-medium text-content-primary mb-1.5">{t('risk.category', { defaultValue: 'Category' })}</label>
              <select id="risk-category" value={f.category} onChange={(e) => set('category', e.target.value)} className={inputCls}>
                {CATEGORIES.map((c) => <option key={c} value={c}>{t(`risk.cat_${c}`, { defaultValue: c })}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="risk-severity" className="block text-sm font-medium text-content-primary mb-1.5">{t('risk.severity', { defaultValue: 'Impact Severity' })}</label>
              <select id="risk-severity" value={f.impactSeverity} onChange={(e) => set('impactSeverity', e.target.value)} className={inputCls}>
                {SEVERITIES.map((s) => <option key={s} value={s}>{t(`risk.severity_${s}`, { defaultValue: s })}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label htmlFor="risk-probability" className="block text-sm font-medium text-content-primary mb-1.5">{t('risk.probability', { defaultValue: 'Probability' })}</label>
              <input id="risk-probability" type="number" min={0} max={1} step={0.1} value={f.probability} onChange={(e) => set('probability', parseFloat(e.target.value) || 0)} className={inputCls} />
            </div>
            <div>
              <label htmlFor="risk-impact-cost" className="block text-sm font-medium text-content-primary mb-1.5">{t('risk.impact_cost', { defaultValue: 'Cost Impact' })}</label>
              <input id="risk-impact-cost" type="number" min={0} step="any" value={f.impactCost} onChange={(e) => set('impactCost', parseFloat(e.target.value) || 0)} className={inputCls} />
            </div>
            <div>
              <label htmlFor="risk-schedule-days" className="block text-sm font-medium text-content-primary mb-1.5">{t('risk.schedule_days', { defaultValue: 'Days' })}</label>
              <input id="risk-schedule-days" type="number" min={0} value={f.scheduleDays} onChange={(e) => set('scheduleDays', parseInt(e.target.value) || 0)} className={inputCls} />
            </div>
          </div>
          <div>
            <label htmlFor="risk-owner" className="block text-sm font-medium text-content-primary mb-1.5">{t('risk.owner', { defaultValue: 'Risk Owner' })}</label>
            <UserSearchInput
              value={f.ownerUserId}
              displayValue={f.ownerName}
              onChange={(uid, name) => setF((p) => ({ ...p, ownerUserId: uid, ownerName: name }))}
              placeholder={t('risk.owner_placeholder', { defaultValue: 'Search team members...' })}
            />
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button variant="primary" disabled={!f.title.trim() || mut.isPending} onClick={() => mut.mutate()}>
            {mut.isPending ? t('common.creating', { defaultValue: 'Creating...' }) : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Detail View ───────────────────────────────────────────────────────── */

function DetailView({ riskId, onBack }: { riskId: string; onBack: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { data: risk, isLoading } = useQuery({ queryKey: ['risk', riskId], queryFn: () => apiGet<RiskItem>(`/v1/risk/${riskId}`) });

  const [editing, setEditing] = useState(false);
  const [ef, setEf] = useState({ status: '', mitigation: '', contingency: '' });

  const startEdit = useCallback(() => {
    if (!risk) return;
    setEf({ status: risk.status, mitigation: risk.mitigation_strategy, contingency: risk.contingency_plan });
    setEditing(true);
  }, [risk]);

  const upd = useMutation({
    mutationFn: (p: Record<string, unknown>) => apiPatch<RiskItem>(`/v1/risk/${riskId}`, p),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['risk'] }); qc.invalidateQueries({ queryKey: ['risks'] }); qc.invalidateQueries({ queryKey: ['risk-summary'] }); qc.invalidateQueries({ queryKey: ['risk-matrix'] }); setEditing(false); addToast({ type: 'success', title: t('risk.updated', { defaultValue: 'Risk updated' }) }); },
    onError: (e: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  if (isLoading || !risk) return <SkeletonCard className="my-6" />;

  return (
    <div>
      <div className="mb-6">
        <button onClick={onBack} aria-label={t('common.back', { defaultValue: 'Back' })} className="inline-flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary mb-3"><ArrowLeft size={14} />{t('common.back', { defaultValue: 'Back' })}</button>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold text-content-primary">{risk.code}</h2>
              <Badge variant={STATUS_COLORS[risk.status] || 'neutral'}>{t(`risk.status_${risk.status}`, { defaultValue: risk.status })}</Badge>
              <Badge variant="neutral">{t(`risk.cat_${risk.category}`, { defaultValue: risk.category })}</Badge>
              {risk.escalated && (
                <Badge variant="error">
                  <AlertTriangle size={12} className="mr-1 inline" />
                  {risk.escalation_trigger === 'review_lapsed'
                    ? t('risk.escalated_review', { defaultValue: 'Escalated: review lapsed' })
                    : t('risk.escalated_severity', { defaultValue: 'Escalated: severity' })}
                </Badge>
              )}
            </div>
            <h3 className="mt-1 text-lg text-content-secondary">{risk.title}</h3>
            {risk.description && <p className="mt-2 text-sm text-content-tertiary max-w-2xl">{risk.description}</p>}
          </div>
          {!editing && <Button variant="secondary" size="sm" onClick={startEdit}>{t('common.edit', { defaultValue: 'Edit' })}</Button>}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-6">
        {[
          [t('risk.probability', { defaultValue: 'Probability' }), `${(risk.probability * 100).toFixed(0)}%`],
          [t('risk.severity', { defaultValue: 'Severity' }), risk.impact_severity],
          [t('risk.score', { defaultValue: 'Score' }), risk.risk_score.toFixed(2)],
          [t('risk.impact_cost', { defaultValue: 'Cost Impact' }), fmtCur(risk.impact_cost, risk.currency)],
          [t('risk.owner', { defaultValue: 'Owner' }), risk.owner_name || '-'],
        ].map(([label, val]) => (
          <Card key={label} className="p-4">
            <p className="text-xs text-content-tertiary uppercase tracking-wide">{label}</p>
            <p className="mt-1 text-sm font-semibold text-content-primary capitalize">{val}</p>
          </Card>
        ))}
      </div>

      {/* Cross-module impact: a risk with schedule/cost impact ties back to
          the 4D Schedule (timeline buffer) and the 5D Cost Model
          (contingency). Make those relationships navigable. */}
      {(risk.impact_schedule_days > 0 || risk.impact_cost > 0) && (
        <Card className="p-4 mb-6">
          <p className="text-xs text-content-tertiary uppercase tracking-wide mb-2">
            {t('risk.cross_impact', { defaultValue: 'Project Impact' })}
          </p>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            {risk.impact_schedule_days > 0 && (
              <div className="flex items-center gap-2">
                <CalendarDays size={15} className="text-content-tertiary" />
                <span className="text-sm text-content-primary">
                  {t('risk.schedule_impact_value', {
                    defaultValue: '+{{days}} days schedule slip',
                    days: risk.impact_schedule_days,
                  })}
                </span>
                <button
                  type="button"
                  onClick={() => navigate('/schedule')}
                  className="text-xs font-medium text-oe-blue hover:underline"
                >
                  {t('risk.open_schedule', { defaultValue: 'View 4D Schedule' })}
                </button>
              </div>
            )}
            {risk.impact_cost > 0 && (
              <div className="flex items-center gap-2">
                <TrendingUp size={15} className="text-content-tertiary" />
                <span className="text-sm text-content-primary">
                  {t('risk.cost_impact_value', {
                    defaultValue: '{{amount}} cost exposure',
                    amount: fmtCur(risk.impact_cost, risk.currency),
                  })}
                </span>
                <button
                  type="button"
                  onClick={() => navigate('/5d')}
                  className="text-xs font-medium text-oe-blue hover:underline"
                >
                  {t('risk.open_5d', { defaultValue: 'Reflect in 5D contingency' })}
                </button>
              </div>
            )}
          </div>
        </Card>
      )}

      {editing ? (
        <Card className="p-5 space-y-4">
          <div>
            <label htmlFor="risk-edit-status" className="block text-sm font-medium text-content-primary mb-1.5">{t('risk.status', { defaultValue: 'Status' })}</label>
            <select id="risk-edit-status" value={ef.status} onChange={(e) => setEf((p) => ({ ...p, status: e.target.value }))} className={inputCls + ' max-w-xs'}>
              {STATUSES.map((s) => <option key={s} value={s}>{t(`risk.status_${s}`, { defaultValue: s })}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="risk-edit-mitigation" className="block text-sm font-medium text-content-primary mb-1.5">{t('risk.mitigation', { defaultValue: 'Mitigation Strategy' })}</label>
            <textarea id="risk-edit-mitigation" value={ef.mitigation} onChange={(e) => setEf((p) => ({ ...p, mitigation: e.target.value }))} rows={3} className={textareaCls} />
          </div>
          <div>
            <label htmlFor="risk-edit-contingency" className="block text-sm font-medium text-content-primary mb-1.5">{t('risk.contingency', { defaultValue: 'Contingency Plan' })}</label>
            <textarea id="risk-edit-contingency" value={ef.contingency} onChange={(e) => setEf((p) => ({ ...p, contingency: e.target.value }))} rows={3} className={textareaCls} />
          </div>
          <div className="flex gap-3">
            <Button variant="primary" size="sm" disabled={upd.isPending} onClick={() => upd.mutate({ status: ef.status, mitigation_strategy: ef.mitigation, contingency_plan: ef.contingency })}>
              {upd.isPending ? t('common.saving', { defaultValue: 'Saving...' }) : t('common.save', { defaultValue: 'Save' })}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Card className="p-4">
            <p className="text-xs text-content-tertiary uppercase tracking-wide mb-2">{t('risk.mitigation', { defaultValue: 'Mitigation Strategy' })}</p>
            <p className="text-sm text-content-primary whitespace-pre-wrap">{risk.mitigation_strategy || t('risk.no_mitigation', { defaultValue: 'No mitigation strategy defined' })}</p>
          </Card>
          <Card className="p-4">
            <p className="text-xs text-content-tertiary uppercase tracking-wide mb-2">{t('risk.contingency', { defaultValue: 'Contingency Plan' })}</p>
            <p className="text-sm text-content-primary whitespace-pre-wrap">{risk.contingency_plan || t('risk.no_contingency', { defaultValue: 'No contingency plan defined' })}</p>
          </Card>
        </div>
      )}

      {/* Cross-project lessons learned via semantic search.  Defaults to
          cross_project=true so the panel surfaces similar risks (and their
          mitigations) from EVERY project the user has access to. */}
      <div className="mt-6">
        <SimilarItemsPanel module="risks" id={risk.id} crossProject limit={6} />
      </div>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function RiskRegisterPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const [showCreate, setShowCreate] = useState(false);
  const [selectedRiskId, setSelectedRiskId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  // Quantitative Monte Carlo lives in its own tab next to the existing
  // qualitative register so the 5x5 matrix view stays the default — most
  // users land here to triage and edit risks, not to re-run simulations.
  const [activeTab, setActiveTab] = useState<RiskTab>('register');
  // Arrow-key navigation across the Register / Monte Carlo tabs (WCAG 2.1.1).
  const onTabKeyDown = useTabKeyboardNav<RiskTab>({
    ids: RISK_TAB_IDS,
    activeId: activeTab,
    onChange: setActiveTab,
    orientation: 'horizontal',
  });

  // Deep-link auto-select: Cmd+Shift+K global search lands here with
  // ?id=<risk_id> — open the matching risk detail view immediately and
  // strip the query param so a refresh doesn't reopen it forever.
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const deepLinkId = searchParams.get('id');
    if (deepLinkId && deepLinkId !== selectedRiskId) {
      setSelectedRiskId(deepLinkId);
      const next = new URLSearchParams(searchParams);
      next.delete('id');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, selectedRiskId, setSearchParams]);

  const { data: projects = [] } = useQuery({ queryKey: ['projects'], queryFn: () => apiGet<Project[]>('/v1/projects/'), staleTime: 5 * 60_000 });
  const projectId = activeProjectId || projects[0]?.id || '';
  const project = useMemo(() => projects.find((p) => p.id === projectId), [projects, projectId]);

  const { data: risks = [], isLoading, isError, error, refetch } = useQuery({ queryKey: ['risks', projectId], queryFn: () => apiGet<RiskItem[]>(`/v1/risk/?project_id=${projectId}`), select: (d): RiskItem[] => normalizeListResponse(d), enabled: !!projectId });
  const { data: summary } = useQuery({ queryKey: ['risk-summary', projectId], queryFn: () => apiGet<RiskSummary>(`/v1/risk/summary/?project_id=${projectId}`), enabled: !!projectId });
  const { data: matrixData } = useQuery({ queryKey: ['risk-matrix', projectId], queryFn: () => apiGet<{ cells: MatrixCell[] }>(`/v1/risk/matrix/?project_id=${projectId}`), enabled: !!projectId });

  const delMut = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/risk/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['risks'] }); qc.invalidateQueries({ queryKey: ['risk-summary'] }); qc.invalidateQueries({ queryKey: ['risk-matrix'] }); setDeleteTarget(null); addToast({ type: 'success', title: t('risk.deleted', { defaultValue: 'Risk deleted' }) }); },
    onError: (e: Error) => { setDeleteTarget(null); addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }); },
  });

  const refresh = useCallback(() => { qc.invalidateQueries({ queryKey: ['risks'] }); qc.invalidateQueries({ queryKey: ['risk-summary'] }); qc.invalidateQueries({ queryKey: ['risk-matrix'] }); }, [qc]);

  // Client-side filtering
  const filteredRisks = useMemo(() => {
    let result = risks;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter((r) => r.title.toLowerCase().includes(q) || r.code.toLowerCase().includes(q) || r.description.toLowerCase().includes(q));
    }
    if (filterCategory) result = result.filter((r) => r.category === filterCategory);
    if (filterStatus) result = result.filter((r) => r.status === filterStatus);
    return result;
  }, [risks, searchQuery, filterCategory, filterStatus]);

  if (selectedRiskId) return <div className="w-full"><DetailView riskId={selectedRiskId} onBack={() => setSelectedRiskId(null)} /></div>;

  const currency = project?.currency || summary?.currency || 'EUR';
  const hasRisks = (summary?.total_risks ?? 0) > 0;

  // Total Exposure must never render a misleading "0". The backend returns
  // total_exposure = 0 when risks span more than one currency (it refuses
  // to sum unconverted amounts) and puts the real numbers in
  // exposure_by_currency. When the breakdown holds more than one non-empty
  // currency we show an honest per-currency total via <MultiCurrencyTotal>;
  // otherwise the single-currency total_exposure is correct as-is.
  const exposureNode = useMemo(() => {
    const byCurrency = summary?.exposure_by_currency ?? {};
    const named = Object.entries(byCurrency).filter(([c, v]) => c && v > 0);
    if (named.length > 1) {
      return (
        <MultiCurrencyTotal
          variant="kpi"
          primaryCurrency={currency}
          items={named.map(([c, v]) => ({ amount: v, currency: c }))}
          className="text-lg font-semibold text-semantic-error"
        />
      );
    }
    return fmtCur(summary?.total_exposure ?? 0, currency);
  }, [summary, currency]);

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[
        ...(project ? [{ label: project.name, to: `/projects/${project.id}` }] : []),
        { label: t('nav.risk_register', { defaultValue: 'Risk Register' }) },
      ]} />

      <PageHeader
        srTitle={t('nav.risk_register', { defaultValue: 'Risk Register' })}
        subtitle={t('risk.subtitle', {
          defaultValue: 'Track project threats with probability x impact scoring, matrix and Monte Carlo analysis.',
        })}
        actions={
          <Button variant="primary" onClick={() => setShowCreate(true)} disabled={!projectId}>
            <Plus size={16} className="mr-1.5" />{t('risk.new', { defaultValue: 'Add Risk' })}
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="risks"
        title={t('risk.intro_title', {
          defaultValue: 'Surface risk before it costs money',
        })}
        more={t('risk.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('risk.intro_more')} /> : undefined}
        links={[
          { label: t('risk.intro_link_analysis', { defaultValue: 'Cost risk analysis' }), onClick: () => navigate('/risk-analysis') },
          { label: t('risk.intro_link_schedule', { defaultValue: '4D Schedule' }), onClick: () => navigate('/schedule') },
        ]}
      >
        {t('risk.intro_body', {
          defaultValue:
            'Log project risks with probability, cost and schedule impact and an owner, then read exposure on a probability-by-impact matrix and per-currency totals that refuse to blend currencies. A second tab runs a Monte Carlo simulation over the register, and the planning cross-links carry the project context into schedule and cost work.',
        })}
      </DismissibleInfo>

      {/* Cross-module navigation — connects the planning value chain */}
      <PlanningCrossLinks active="risks" />

      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { icon: ShieldAlert, label: t('risk.total', { defaultValue: 'Total Risks' }), value: summary.total_risks, cls: 'text-content-primary', bg: 'bg-surface-secondary' },
            { icon: AlertTriangle, label: t('risk.high_critical', { defaultValue: 'High / Critical' }), value: summary.high_critical_count, cls: 'text-semantic-error', bg: 'bg-red-50 dark:bg-red-950/30' },
            { icon: DollarSign, label: t('risk.exposure', { defaultValue: 'Total Exposure' }), value: exposureNode, cls: 'text-semantic-error', bg: 'bg-surface-secondary' },
            { icon: Shield, label: t('risk.mitigated', { defaultValue: 'Mitigated' }), value: summary.mitigated_count, cls: 'text-semantic-success', bg: 'bg-green-50 dark:bg-green-950/30' },
          ].map(({ icon: Icon, label, value, cls, bg }) => (
            <Card key={label} className="p-4">
              <div className="flex items-center gap-2">
                <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${bg}`}><Icon size={16} className={cls} /></div>
                <div>
                  <p className="text-2xs text-content-tertiary uppercase tracking-wide">{label}</p>
                  <p className={`text-lg font-semibold ${cls}`}>{value}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* ── Tabs: Register (qualitative) vs Monte Carlo (quantitative) ──
          The register tab keeps the existing 5x5 matrix + heatmap +
          filter table. The Monte Carlo tab adds enterprise-CPM-style PERT
          simulation with P50/P80/P95 confidence bands. */}
      {projectId && (
        <div
          role="tablist"
          aria-label={t('risk.tabs_aria', { defaultValue: 'Risk register tabs' })}
          onKeyDown={onTabKeyDown}
          className="flex items-center gap-1 border-b border-border-light"
        >
          <button
            type="button"
            role="tab"
            id="risk-tab-register"
            aria-selected={activeTab === 'register'}
            aria-controls="risk-panel-register"
            tabIndex={activeTab === 'register' ? 0 : -1}
            onClick={() => setActiveTab('register')}
            className={`inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${
              activeTab === 'register'
                ? 'border-oe-blue text-content-primary'
                : 'border-transparent text-content-tertiary hover:text-content-secondary'
            }`}
          >
            <LayoutGrid className="h-4 w-4" />
            {t('risk.tab_register', { defaultValue: 'Register' })}
          </button>
          <button
            type="button"
            role="tab"
            id="risk-tab-montecarlo"
            aria-selected={activeTab === 'montecarlo'}
            aria-controls="risk-panel-montecarlo"
            tabIndex={activeTab === 'montecarlo' ? 0 : -1}
            onClick={() => setActiveTab('montecarlo')}
            className={`inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${
              activeTab === 'montecarlo'
                ? 'border-oe-blue text-content-primary'
                : 'border-transparent text-content-tertiary hover:text-content-secondary'
            }`}
          >
            <Activity className="h-4 w-4" />
            {t('risk.tab_montecarlo', { defaultValue: 'Monte Carlo' })}
          </button>
        </div>
      )}

      {/* Monte Carlo tab content — render and stop here. */}
      {projectId && activeTab === 'montecarlo' && (
        <div>
          <MonteCarloTab projectId={projectId} currency={currency} />
        </div>
      )}

      {/* Only show matrix when there are actual risks */}
      {activeTab === 'register' && hasRisks && matrixData?.cells && <div><RiskMatrix cells={matrixData.cells} /></div>}

      {/* 5x5 Risk Heatmap (client-side, based on probability_score × impact_score_cost) */}
      {activeTab === 'register' && risks.length > 0 && risks.some((r) => r.probability_score != null && r.impact_score_cost != null) && (
        <div><RiskMatrixHeatmap risks={risks} /></div>
      )}

      {/* Search & filter bar (only when there are risks) */}
      {activeTab === 'register' && risks.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[200px] max-w-xs">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('risk.search', { defaultValue: 'Search risks...' })}
              aria-label={t('risk.search', { defaultValue: 'Search risks...' })}
              className="h-8 w-full rounded-lg border border-border bg-surface-primary pl-8 pr-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>
          <Button variant="ghost" size="sm" onClick={() => setShowFilters(!showFilters)} className={showFilters ? 'text-oe-blue' : ''} icon={<Filter size={14} />}>
            {t('common.filters', { defaultValue: 'Filters' })}
          </Button>
        </div>
      )}

      {activeTab === 'register' && showFilters && (
        <div className="flex items-center gap-2 flex-wrap animate-fade-in">
          <select value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)} aria-label={t('risk.filter_category', { defaultValue: 'Filter by category' })} className={selectCls + ' max-w-[150px]'}>
            <option value="">{t('risk.all_categories', { defaultValue: 'All Categories' })}</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{t(`risk.cat_${c}`, { defaultValue: c })}</option>)}
          </select>
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} aria-label={t('risk.filter_status', { defaultValue: 'Filter by status' })} className={selectCls + ' max-w-[150px]'}>
            <option value="">{t('risk.all_statuses', { defaultValue: 'All Statuses' })}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{t(`risk.status_${s}`, { defaultValue: s })}</option>)}
          </select>
          {(filterCategory || filterStatus) && (
            <button onClick={() => { setFilterCategory(''); setFilterStatus(''); }} className="text-xs text-oe-blue hover:underline">
              {t('risk.clear_filters', { defaultValue: 'Clear' })}
            </button>
          )}
        </div>
      )}

      {activeTab === 'register' && <div>
        {!projectId ? (
          <Card><RequiresProject
            emptyHint={t('risk.no_project_desc', { defaultValue: 'Open a project first to view and manage risks.' })}
          >{null}</RequiresProject></Card>
        ) : isLoading ? (
          <SkeletonTable rows={6} columns={5} />
        ) : isError ? (
          <Card className="py-12"><RecoveryCard error={error} onRetry={() => refetch()} /></Card>
        ) : filteredRisks.length === 0 ? (
          <Card><EmptyState
            icon={<ShieldAlert size={28} strokeWidth={1.5} />}
            title={searchQuery || filterCategory || filterStatus
              ? t('risk.no_match', { defaultValue: 'No matching risks' })
              : t('risk.empty', { defaultValue: 'No risks registered' })}
            description={searchQuery || filterCategory || filterStatus
              ? t('risk.no_match_desc', { defaultValue: 'Try adjusting your search or filters.' })
              : t('risk.empty_desc', { defaultValue: 'Add risks to track potential issues and mitigation strategies' })}
            action={searchQuery || filterCategory || filterStatus ? undefined : { label: t('risk.new', { defaultValue: 'Add Risk' }), onClick: () => setShowCreate(true) }}
          /></Card>
        ) : (
          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-surface-secondary/50">
                    {([['risk.code', 'Code', 'left'], ['common.title', 'Title', 'left'], ['risk.category', 'Category', 'left'], ['risk.probability_short', 'Prob.', 'center'], ['risk.impact', 'Impact', 'left'], ['risk.score', 'Score', 'center'], ['common.status', 'Status', 'left'], ['risk.owner', 'Owner', 'left']] as const).map(([key, dv, align]) => (
                      <th key={key} className={`px-4 py-3 text-${align} font-medium text-content-secondary`}>{t(key, { defaultValue: dv })}</th>
                    ))}
                    <th className="px-4 py-3 w-16" />
                  </tr>
                </thead>
                <tbody>
                  {filteredRisks.map((r) => (
                    <tr key={r.id} className="border-b border-border last:border-0 hover:bg-surface-secondary/30 cursor-pointer" onClick={() => setSelectedRiskId(r.id)}>
                      <td className="px-4 py-3 font-mono text-xs text-content-secondary">{r.code}</td>
                      <td className="px-4 py-3 text-content-primary font-medium max-w-[200px] truncate">
                        <span className="inline-flex items-center gap-1.5">
                          {r.escalated && (
                            <AlertTriangle
                              size={14}
                              className="text-semantic-error shrink-0"
                              aria-label={t('risk.escalated', { defaultValue: 'Escalated' })}
                            />
                          )}
                          <span className="truncate">{r.title}</span>
                        </span>
                      </td>
                      <td className="px-4 py-3"><Badge variant="neutral">{t(`risk.cat_${r.category}`, { defaultValue: r.category })}</Badge></td>
                      <td className="px-4 py-3 text-center text-content-secondary tabular-nums">{(r.probability * 100).toFixed(0)}%</td>
                      <td className="px-4 py-3"><Badge variant={r.impact_severity === 'critical' ? 'error' : r.impact_severity === 'high' ? 'warning' : r.impact_severity === 'medium' ? 'blue' : 'neutral'}>{r.impact_severity}</Badge></td>
                      <td className="px-4 py-3 text-center font-medium tabular-nums text-content-primary">{r.risk_score.toFixed(1)}</td>
                      <td className="px-4 py-3"><Badge variant={STATUS_COLORS[r.status] || 'neutral'}>{t(`risk.status_${r.status}`, { defaultValue: r.status })}</Badge></td>
                      <td className="px-4 py-3 text-content-secondary text-xs truncate max-w-[100px]">{r.owner_name || '-'}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          <button onClick={(e) => { e.stopPropagation(); setDeleteTarget(r.id); }} className="text-content-tertiary hover:text-semantic-error transition-colors p-1" title={t('common.delete', { defaultValue: 'Delete' })} aria-label={t('common.delete', { defaultValue: 'Delete' })}><Trash2 size={14} /></button>
                          <ChevronRight size={14} className="text-content-tertiary" />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>}

      {showCreate && projectId && <CreateDialog projectId={projectId} currency={currency} onClose={() => setShowCreate(false)} onCreated={refresh} />}

      {/* Delete confirmation dialog */}
      <ConfirmDialog
        open={deleteTarget !== null}
        onConfirm={() => deleteTarget && delMut.mutate(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
        title={t('risk.delete_title', { defaultValue: 'Delete Risk' })}
        message={t('risk.delete_message', { defaultValue: 'This risk will be permanently removed. This action cannot be undone.' })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        variant="danger"
        loading={delMut.isPending}
      />
    </div>
  );
}

export default RiskRegisterPage;
