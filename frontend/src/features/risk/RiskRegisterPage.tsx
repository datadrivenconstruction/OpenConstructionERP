import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ShieldAlert, Plus, ChevronRight, ArrowLeft, DollarSign,
  AlertTriangle, Shield, Trash2, X,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Project { id: string; name: string; currency: string }

interface RiskItem {
  id: string; project_id: string; code: string; title: string; description: string;
  category: string; probability: number; impact_cost: number; impact_schedule_days: number;
  impact_severity: string; risk_score: number; status: string; mitigation_strategy: string;
  contingency_plan: string; owner_name: string; response_cost: number; currency: string;
  metadata: Record<string, unknown>; created_at: string; updated_at: string;
}

interface RiskSummary {
  total_risks: number; by_status: Record<string, number>; by_category: Record<string, number>;
  high_critical_count: number; total_exposure: number; mitigated_count: number; currency: string;
}

interface MatrixCell { probability_level: string; impact_level: string; count: number; risk_ids: string[] }

/* ── Constants ─────────────────────────────────────────────────────────── */

const STATUS_COLORS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  identified: 'blue', assessed: 'warning', mitigating: 'success', closed: 'neutral', occurred: 'error',
};
const CATEGORIES = ['technical', 'financial', 'schedule', 'regulatory', 'environmental', 'safety'];
const SEVERITIES = ['low', 'medium', 'high', 'critical'];
const STATUSES = ['identified', 'assessed', 'mitigating', 'closed', 'occurred'];
const PROB_LEVELS = ['0.9', '0.7', '0.5', '0.3', '0.1'];
const PROB_LABELS: Record<string, string> = { '0.9': 'Very High', '0.7': 'High', '0.5': 'Medium', '0.3': 'Low', '0.1': 'Very Low' };
const IMPACT_LEVELS = ['low', 'medium', 'high', 'critical'];

function fmtCur(n: number, c = 'EUR') {
  const s = /^[A-Z]{3}$/.test(c) ? c : 'EUR';
  try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: s, minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n); }
  catch { return `${n.toFixed(0)} ${s}`; }
}

function matrixColor(prob: string, impact: string) {
  const score = parseFloat(prob) * ({ low: 1, medium: 2, high: 3, critical: 4 }[impact] || 1);
  if (score >= 2.0) return 'bg-red-500/80 text-white';
  if (score >= 1.2) return 'bg-orange-400/80 text-white';
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
              {IMPACT_LEVELS.map((i) => <th key={i} className="p-1 text-center text-content-tertiary capitalize">{i}</th>)}
            </tr>
          </thead>
          <tbody>
            {PROB_LEVELS.map((p) => (
              <tr key={p}>
                <td className="p-1 text-content-secondary font-medium">{PROB_LABELS[p]}</td>
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
        {[['bg-green-400/70', 'Low'], ['bg-yellow-400/80', 'Medium'], ['bg-orange-400/80', 'High'], ['bg-red-500/80', 'Critical']].map(([bg, l]) => (
          <span key={l} className="flex items-center gap-1"><span className={`inline-block w-3 h-3 rounded ${bg}`} />{l}</span>
        ))}
      </div>
    </Card>
  );
}

/* ── Input helper ──────────────────────────────────────────────────────── */

const inputCls = 'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls = 'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Create Dialog ─────────────────────────────────────────────────────── */

function CreateDialog({ projectId, currency, onClose, onCreated }: { projectId: string; currency: string; onClose: () => void; onCreated: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [f, setF] = useState({ title: '', description: '', category: 'technical', probability: 0.5, impactSeverity: 'medium', impactCost: 0, scheduleDays: 0, ownerName: '' });
  const set = (k: string, v: unknown) => setF((p) => ({ ...p, [k]: v }));

  const mut = useMutation({
    mutationFn: () => apiPost<RiskItem>('/v1/risk/', { project_id: projectId, title: f.title, description: f.description, category: f.category, probability: f.probability, impact_severity: f.impactSeverity, impact_cost: f.impactCost, impact_schedule_days: f.scheduleDays, owner_name: f.ownerName, currency }),
    onSuccess: () => { onCreated(); onClose(); addToast({ type: 'success', title: t('risk.created', { defaultValue: 'Risk created' }) }); },
    onError: (e: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-full max-w-lg rounded-xl bg-surface-primary p-6 shadow-xl border border-border max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-content-primary">{t('risk.new', { defaultValue: 'New Risk' })}</h2>
          <button onClick={onClose} className="text-content-tertiary hover:text-content-primary"><X size={18} /></button>
        </div>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">{t('common.title', { defaultValue: 'Title' })} *</label>
            <input value={f.title} onChange={(e) => set('title', e.target.value)} placeholder={t('risk.title_placeholder', { defaultValue: 'e.g. Foundation soil instability' })} className={inputCls} />
          </div>
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">{t('common.description', { defaultValue: 'Description' })}</label>
            <textarea value={f.description} onChange={(e) => set('description', e.target.value)} rows={2} className={textareaCls} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">{t('risk.category', { defaultValue: 'Category' })}</label>
              <select value={f.category} onChange={(e) => set('category', e.target.value)} className={inputCls}>
                {CATEGORIES.map((c) => <option key={c} value={c}>{t(`risk.cat_${c}`, { defaultValue: c })}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">{t('risk.severity', { defaultValue: 'Impact Severity' })}</label>
              <select value={f.impactSeverity} onChange={(e) => set('impactSeverity', e.target.value)} className={inputCls}>
                {SEVERITIES.map((s) => <option key={s} value={s}>{t(`risk.severity_${s}`, { defaultValue: s })}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">{t('risk.probability', { defaultValue: 'Probability' })}</label>
              <input type="number" min={0} max={1} step={0.1} value={f.probability} onChange={(e) => set('probability', parseFloat(e.target.value) || 0)} className={inputCls} />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">{t('risk.impact_cost', { defaultValue: 'Cost Impact' })}</label>
              <input type="number" min={0} step="any" value={f.impactCost} onChange={(e) => set('impactCost', parseFloat(e.target.value) || 0)} className={inputCls} />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">{t('risk.schedule_days', { defaultValue: 'Days' })}</label>
              <input type="number" min={0} value={f.scheduleDays} onChange={(e) => set('scheduleDays', parseInt(e.target.value) || 0)} className={inputCls} />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">{t('risk.owner', { defaultValue: 'Risk Owner' })}</label>
            <input value={f.ownerName} onChange={(e) => set('ownerName', e.target.value)} className={inputCls} />
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

  if (isLoading || !risk) return <div className="flex items-center justify-center py-20"><div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" /></div>;

  return (
    <div>
      <div className="mb-6">
        <button onClick={onBack} className="inline-flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary mb-3"><ArrowLeft size={14} />{t('common.back', { defaultValue: 'Back' })}</button>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold text-content-primary">{risk.code}</h2>
              <Badge variant={STATUS_COLORS[risk.status] || 'neutral'}>{risk.status}</Badge>
              <Badge variant="neutral">{t(`risk.cat_${risk.category}`, { defaultValue: risk.category })}</Badge>
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

      {editing ? (
        <Card className="p-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">{t('risk.status', { defaultValue: 'Status' })}</label>
            <select value={ef.status} onChange={(e) => setEf((p) => ({ ...p, status: e.target.value }))} className={inputCls + ' max-w-xs'}>
              {STATUSES.map((s) => <option key={s} value={s}>{t(`risk.status_${s}`, { defaultValue: s })}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">{t('risk.mitigation', { defaultValue: 'Mitigation Strategy' })}</label>
            <textarea value={ef.mitigation} onChange={(e) => setEf((p) => ({ ...p, mitigation: e.target.value }))} rows={3} className={textareaCls} />
          </div>
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">{t('risk.contingency', { defaultValue: 'Contingency Plan' })}</label>
            <textarea value={ef.contingency} onChange={(e) => setEf((p) => ({ ...p, contingency: e.target.value }))} rows={3} className={textareaCls} />
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
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function RiskRegisterPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const [showCreate, setShowCreate] = useState(false);
  const [selectedRiskId, setSelectedRiskId] = useState<string | null>(null);

  const { data: projects = [] } = useQuery({ queryKey: ['projects'], queryFn: () => apiGet<Project[]>('/v1/projects/') });
  const projectId = activeProjectId || projects[0]?.id || '';
  const project = useMemo(() => projects.find((p) => p.id === projectId), [projects, projectId]);

  const { data: risks = [], isLoading } = useQuery({ queryKey: ['risks', projectId], queryFn: () => apiGet<RiskItem[]>(`/v1/risk/?project_id=${projectId}`), enabled: !!projectId });
  const { data: summary } = useQuery({ queryKey: ['risk-summary', projectId], queryFn: () => apiGet<RiskSummary>(`/v1/risk/summary?project_id=${projectId}`), enabled: !!projectId });
  const { data: matrixData } = useQuery({ queryKey: ['risk-matrix', projectId], queryFn: () => apiGet<{ cells: MatrixCell[] }>(`/v1/risk/matrix?project_id=${projectId}`), enabled: !!projectId });

  const delMut = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/risk/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['risks'] }); qc.invalidateQueries({ queryKey: ['risk-summary'] }); qc.invalidateQueries({ queryKey: ['risk-matrix'] }); addToast({ type: 'success', title: t('risk.deleted', { defaultValue: 'Risk deleted' }) }); },
    onError: (e: Error) => addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const refresh = useCallback(() => { qc.invalidateQueries({ queryKey: ['risks'] }); qc.invalidateQueries({ queryKey: ['risk-summary'] }); qc.invalidateQueries({ queryKey: ['risk-matrix'] }); }, [qc]);

  if (selectedRiskId) return <div className="mx-auto max-w-5xl px-6 py-6"><DetailView riskId={selectedRiskId} onBack={() => setSelectedRiskId(null)} /></div>;

  const currency = project?.currency || summary?.currency || 'EUR';

  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <Breadcrumb items={[{ label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' }, { label: t('nav.risk_register', { defaultValue: 'Risk Register' }) }]} />

      <div className="mt-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{t('nav.risk_register', { defaultValue: 'Risk Register' })}</h1>
          {project && <p className="mt-1 text-sm text-content-secondary">{project.name}</p>}
        </div>
        <Button variant="primary" onClick={() => setShowCreate(true)} disabled={!projectId}>
          <Plus size={16} className="mr-1.5" />{t('risk.new', { defaultValue: 'Add Risk' })}
        </Button>
      </div>

      {summary && (
        <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { icon: ShieldAlert, label: t('risk.total', { defaultValue: 'Total Risks' }), value: summary.total_risks, cls: 'text-content-primary', bg: 'bg-surface-secondary' },
            { icon: AlertTriangle, label: t('risk.high_critical', { defaultValue: 'High / Critical' }), value: summary.high_critical_count, cls: 'text-semantic-error', bg: 'bg-red-50 dark:bg-red-950/30' },
            { icon: DollarSign, label: t('risk.exposure', { defaultValue: 'Total Exposure' }), value: fmtCur(summary.total_exposure, currency), cls: 'text-semantic-error', bg: 'bg-surface-secondary' },
            { icon: Shield, label: t('risk.mitigated', { defaultValue: 'Mitigated' }), value: summary.mitigated_count, cls: 'text-[#15803d]', bg: 'bg-green-50 dark:bg-green-950/30' },
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

      {matrixData?.cells && matrixData.cells.length > 0 && <div className="mt-6"><RiskMatrix cells={matrixData.cells} /></div>}

      <div className="mt-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-20"><div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" /></div>
        ) : risks.length === 0 ? (
          <Card><EmptyState icon={<ShieldAlert size={24} />} title={t('risk.empty', { defaultValue: 'No risks registered' })} description={t('risk.empty_desc', { defaultValue: 'Add risks to track potential issues and mitigation strategies' })} action={{ label: t('risk.new', { defaultValue: 'Add Risk' }), onClick: () => setShowCreate(true) }} /></Card>
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
                  {risks.map((r) => (
                    <tr key={r.id} className="border-b border-border last:border-0 hover:bg-surface-secondary/30 cursor-pointer" onClick={() => setSelectedRiskId(r.id)}>
                      <td className="px-4 py-3 font-mono text-xs text-content-secondary">{r.code}</td>
                      <td className="px-4 py-3 text-content-primary font-medium max-w-[200px] truncate">{r.title}</td>
                      <td className="px-4 py-3"><Badge variant="neutral">{t(`risk.cat_${r.category}`, { defaultValue: r.category })}</Badge></td>
                      <td className="px-4 py-3 text-center text-content-secondary tabular-nums">{(r.probability * 100).toFixed(0)}%</td>
                      <td className="px-4 py-3"><Badge variant={r.impact_severity === 'critical' ? 'error' : r.impact_severity === 'high' ? 'warning' : r.impact_severity === 'medium' ? 'blue' : 'neutral'}>{r.impact_severity}</Badge></td>
                      <td className="px-4 py-3 text-center font-medium tabular-nums text-content-primary">{r.risk_score.toFixed(1)}</td>
                      <td className="px-4 py-3"><Badge variant={STATUS_COLORS[r.status] || 'neutral'}>{t(`risk.status_${r.status}`, { defaultValue: r.status })}</Badge></td>
                      <td className="px-4 py-3 text-content-secondary text-xs truncate max-w-[100px]">{r.owner_name || '-'}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          <button onClick={(e) => { e.stopPropagation(); delMut.mutate(r.id); }} className="text-content-tertiary hover:text-semantic-error transition-colors p-1" title={t('common.delete', { defaultValue: 'Delete' })}><Trash2 size={14} /></button>
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
      </div>

      {showCreate && projectId && <CreateDialog projectId={projectId} currency={currency} onClose={() => setShowCreate(false)} onCreated={refresh} />}
    </div>
  );
}

export default RiskRegisterPage;
