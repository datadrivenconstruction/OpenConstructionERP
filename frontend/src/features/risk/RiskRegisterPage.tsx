import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ShieldAlert,
  Plus,
  ChevronRight,
  ArrowLeft,
  DollarSign,
  AlertTriangle,
  Shield,
  Trash2,
  X,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  currency: string;
}

interface RiskItem {
  id: string;
  project_id: string;
  code: string;
  title: string;
  description: string;
  category: string;
  probability: number;
  impact_cost: number;
  impact_schedule_days: number;
  impact_severity: string;
  risk_score: number;
  status: string;
  mitigation_strategy: string;
  contingency_plan: string;
  owner_name: string;
  response_cost: number;
  currency: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface RiskSummary {
  total_risks: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  high_critical_count: number;
  total_exposure: number;
  mitigated_count: number;
  currency: string;
}

interface MatrixCell {
  probability_level: string;
  impact_level: string;
  count: number;
  risk_ids: string[];
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

const STATUS_COLORS: Record<string, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  identified: 'blue',
  assessed: 'warning',
  mitigating: 'success',
  closed: 'neutral',
  occurred: 'error',
};

const CATEGORY_LABELS: Record<string, string> = {
  technical: 'Technical',
  financial: 'Financial',
  schedule: 'Schedule',
  regulatory: 'Regulatory',
  environmental: 'Environmental',
  safety: 'Safety',
};

const SEVERITY_LABELS: Record<string, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
};

function formatCurrency(amount: number, currency: string = 'EUR'): string {
  const safe = /^[A-Z]{3}$/.test(currency) ? currency : 'EUR';
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: safe,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${amount.toFixed(0)} ${safe}`;
  }
}

/* ── Risk Matrix ──────────────────────────────────────────────────────── */

const PROB_LEVELS = ['0.9', '0.7', '0.5', '0.3', '0.1'];
const PROB_LABELS: Record<string, string> = {
  '0.9': 'Very High',
  '0.7': 'High',
  '0.5': 'Medium',
  '0.3': 'Low',
  '0.1': 'Very Low',
};
const IMPACT_LEVELS = ['low', 'medium', 'high', 'critical'];

function getMatrixColor(prob: string, impact: string): string {
  const p = parseFloat(prob);
  const iMap: Record<string, number> = { low: 1, medium: 2, high: 3, critical: 4 };
  const score = p * (iMap[impact] || 1);
  if (score >= 2.0) return 'bg-red-500/80 text-white';
  if (score >= 1.2) return 'bg-orange-400/80 text-white';
  if (score >= 0.6) return 'bg-yellow-400/80 text-gray-900';
  return 'bg-green-400/70 text-gray-900';
}

function RiskMatrix({ cells }: { cells: MatrixCell[] }) {
  const { t } = useTranslation();
  const cellMap = useMemo(() => {
    const map: Record<string, MatrixCell> = {};
    for (const c of cells) {
      map[`${c.probability_level}|${c.impact_level}`] = c;
    }
    return map;
  }, [cells]);

  return (
    <Card className="p-4">
      <h3 className="text-sm font-semibold text-content-primary mb-3">
        {t('risk.matrix', { defaultValue: 'Risk Matrix' })}
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className="p-1 text-left text-content-tertiary w-20">
                {t('risk.probability', { defaultValue: 'Probability' })}
              </th>
              {IMPACT_LEVELS.map((imp) => (
                <th key={imp} className="p-1 text-center text-content-tertiary capitalize">
                  {t(`risk.impact_${imp}`, { defaultValue: SEVERITY_LABELS[imp] || imp })}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PROB_LEVELS.map((prob) => (
              <tr key={prob}>
                <td className="p-1 text-content-secondary font-medium text-xs">
                  {t(`risk.prob_${prob}`, { defaultValue: PROB_LABELS[prob] || prob })}
                </td>
                {IMPACT_LEVELS.map((imp) => {
                  const cell = cellMap[`${prob}|${imp}`];
                  const count = cell?.count || 0;
                  return (
                    <td key={imp} className="p-1">
                      <div
                        className={`flex items-center justify-center h-10 rounded-md text-sm font-bold ${
                          count > 0 ? getMatrixColor(prob, imp) : 'bg-surface-secondary text-content-quaternary'
                        }`}
                      >
                        {count > 0 ? count : ''}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex items-center gap-4 text-2xs text-content-tertiary">
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded bg-green-400/70" /> {t('risk.level_low', { defaultValue: 'Low' })}</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded bg-yellow-400/80" /> {t('risk.level_medium', { defaultValue: 'Medium' })}</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded bg-orange-400/80" /> {t('risk.level_high', { defaultValue: 'High' })}</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded bg-red-500/80" /> {t('risk.level_critical', { defaultValue: 'Critical' })}</span>
      </div>
    </Card>
  );
}

/* ── Create Dialog ─────────────────────────────────────────────────────── */

function CreateDialog({
  projectId,
  currency,
  onClose,
  onCreated,
}: {
  projectId: string;
  currency: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('technical');
  const [probability, setProbability] = useState(0.5);
  const [impactSeverity, setImpactSeverity] = useState('medium');
  const [impactCost, setImpactCost] = useState(0);
  const [scheduleDays, setScheduleDays] = useState(0);
  const [ownerName, setOwnerName] = useState('');
  const addToast = useToastStore((s) => s.addToast);

  const mutation = useMutation({
    mutationFn: () =>
      apiPost<RiskItem>('/v1/risk/', {
        project_id: projectId,
        title,
        description,
        category,
        probability,
        impact_severity: impactSeverity,
        impact_cost: impactCost,
        impact_schedule_days: scheduleDays,
        owner_name: ownerName,
        currency,
      }),
    onSuccess: () => {
      onCreated();
      onClose();
      addToast({
        type: 'success',
        title: t('risk.created', { defaultValue: 'Risk created' }),
      });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-xl bg-surface-primary p-6 shadow-xl border border-border max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('risk.new', { defaultValue: 'New Risk' })}
          </h2>
          <button onClick={onClose} className="text-content-tertiary hover:text-content-primary">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('common.title', { defaultValue: 'Title' })} *
            </label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t('risk.title_placeholder', { defaultValue: 'e.g. Foundation soil instability' })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('common.description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('risk.category', { defaultValue: 'Category' })}
              </label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              >
                {Object.entries(CATEGORY_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {t(`risk.cat_${k}`, { defaultValue: v })}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('risk.severity', { defaultValue: 'Impact Severity' })}
              </label>
              <select
                value={impactSeverity}
                onChange={(e) => setImpactSeverity(e.target.value)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              >
                {Object.entries(SEVERITY_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {t(`risk.severity_${k}`, { defaultValue: v })}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('risk.probability', { defaultValue: 'Probability' })}
              </label>
              <input
                type="number"
                min={0}
                max={1}
                step={0.1}
                value={probability}
                onChange={(e) => setProbability(parseFloat(e.target.value) || 0)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('risk.impact_cost', { defaultValue: 'Cost Impact' })}
              </label>
              <input
                type="number"
                min={0}
                step="any"
                value={impactCost}
                onChange={(e) => setImpactCost(parseFloat(e.target.value) || 0)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('risk.schedule_days', { defaultValue: 'Schedule (days)' })}
              </label>
              <input
                type="number"
                min={0}
                value={scheduleDays}
                onChange={(e) => setScheduleDays(parseInt(e.target.value) || 0)}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('risk.owner', { defaultValue: 'Risk Owner' })}
            </label>
            <input
              value={ownerName}
              onChange={(e) => setOwnerName(e.target.value)}
              placeholder={t('risk.owner_placeholder', { defaultValue: 'Person responsible' })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            disabled={!title.trim() || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending
              ? t('common.creating', { defaultValue: 'Creating...' })
              : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Detail View ───────────────────────────────────────────────────────── */

function DetailView({
  riskId,
  onBack,
}: {
  riskId: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const { data: risk, isLoading } = useQuery({
    queryKey: ['risk', riskId],
    queryFn: () => apiGet<RiskItem>(`/v1/risk/${riskId}`),
  });

  const [editing, setEditing] = useState(false);
  const [mitigation, setMitigation] = useState('');
  const [contingency, setContingency] = useState('');
  const [editStatus, setEditStatus] = useState('');

  const startEditing = useCallback(() => {
    if (!risk) return;
    setMitigation(risk.mitigation_strategy);
    setContingency(risk.contingency_plan);
    setEditStatus(risk.status);
    setEditing(true);
  }, [risk]);

  const updateMut = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiPatch<RiskItem>(`/v1/risk/${riskId}`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['risk', riskId] });
      queryClient.invalidateQueries({ queryKey: ['risks'] });
      queryClient.invalidateQueries({ queryKey: ['risk-summary'] });
      queryClient.invalidateQueries({ queryKey: ['risk-matrix'] });
      setEditing(false);
      addToast({ type: 'success', title: t('risk.updated', { defaultValue: 'Risk updated' }) });
    },
    onError: (err: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message }),
  });

  if (isLoading || !risk) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary mb-3"
        >
          <ArrowLeft size={14} />
          {t('common.back', { defaultValue: 'Back' })}
        </button>

        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold text-content-primary">{risk.code}</h2>
              <Badge variant={STATUS_COLORS[risk.status] || 'neutral'}>{risk.status}</Badge>
              <Badge variant="neutral">
                {t(`risk.cat_${risk.category}`, { defaultValue: CATEGORY_LABELS[risk.category] || risk.category })}
              </Badge>
            </div>
            <h3 className="mt-1 text-lg text-content-secondary">{risk.title}</h3>
            {risk.description && (
              <p className="mt-2 text-sm text-content-tertiary max-w-2xl">{risk.description}</p>
            )}
          </div>
          {!editing && (
            <Button variant="secondary" size="sm" onClick={startEditing}>
              {t('common.edit', { defaultValue: 'Edit' })}
            </Button>
          )}
        </div>
      </div>

      {/* Info cards */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-4 mb-6">
        <Card className="p-4">
          <p className="text-xs text-content-tertiary uppercase tracking-wide">
            {t('risk.probability', { defaultValue: 'Probability' })}
          </p>
          <p className="mt-1 text-sm font-semibold text-content-primary">{(risk.probability * 100).toFixed(0)}%</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-content-tertiary uppercase tracking-wide">
            {t('risk.severity', { defaultValue: 'Impact Severity' })}
          </p>
          <p className="mt-1 text-sm font-semibold text-content-primary capitalize">{risk.impact_severity}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-content-tertiary uppercase tracking-wide">
            {t('risk.score', { defaultValue: 'Risk Score' })}
          </p>
          <p className="mt-1 text-sm font-semibold text-content-primary">{risk.risk_score.toFixed(2)}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-content-tertiary uppercase tracking-wide">
            {t('risk.impact_cost', { defaultValue: 'Cost Impact' })}
          </p>
          <p className="mt-1 text-sm font-semibold text-semantic-error">
            {formatCurrency(risk.impact_cost, risk.currency)}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-content-tertiary uppercase tracking-wide">
            {t('risk.owner', { defaultValue: 'Risk Owner' })}
          </p>
          <p className="mt-1 text-sm font-medium text-content-primary">{risk.owner_name || '-'}</p>
        </Card>
      </div>

      {/* Editable section */}
      {editing ? (
        <Card className="p-5 space-y-4">
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('risk.status', { defaultValue: 'Status' })}
            </label>
            <select
              value={editStatus}
              onChange={(e) => setEditStatus(e.target.value)}
              className="h-10 w-full max-w-xs rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            >
              {['identified', 'assessed', 'mitigating', 'closed', 'occurred'].map((s) => (
                <option key={s} value={s}>
                  {t(`risk.status_${s}`, { defaultValue: s })}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('risk.mitigation', { defaultValue: 'Mitigation Strategy' })}
            </label>
            <textarea
              value={mitigation}
              onChange={(e) => setMitigation(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('risk.contingency', { defaultValue: 'Contingency Plan' })}
            </label>
            <textarea
              value={contingency}
              onChange={(e) => setContingency(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
            />
          </div>
          <div className="flex gap-3">
            <Button
              variant="primary"
              size="sm"
              disabled={updateMut.isPending}
              onClick={() =>
                updateMut.mutate({
                  status: editStatus,
                  mitigation_strategy: mitigation,
                  contingency_plan: contingency,
                })
              }
            >
              {updateMut.isPending
                ? t('common.saving', { defaultValue: 'Saving...' })
                : t('common.save', { defaultValue: 'Save' })}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </Card>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Card className="p-4">
            <p className="text-xs text-content-tertiary uppercase tracking-wide mb-2">
              {t('risk.mitigation', { defaultValue: 'Mitigation Strategy' })}
            </p>
            <p className="text-sm text-content-primary whitespace-pre-wrap">
              {risk.mitigation_strategy || t('risk.no_mitigation', { defaultValue: 'No mitigation strategy defined' })}
            </p>
          </Card>
          <Card className="p-4">
            <p className="text-xs text-content-tertiary uppercase tracking-wide mb-2">
              {t('risk.contingency', { defaultValue: 'Contingency Plan' })}
            </p>
            <p className="text-sm text-content-primary whitespace-pre-wrap">
              {risk.contingency_plan || t('risk.no_contingency', { defaultValue: 'No contingency plan defined' })}
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function RiskRegisterPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [showCreate, setShowCreate] = useState(false);
  const [selectedRiskId, setSelectedRiskId] = useState<string | null>(null);

  // Fetch projects
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const projectId = activeProjectId || projects[0]?.id || '';
  const project = useMemo(() => projects.find((p) => p.id === projectId), [projects, projectId]);

  // Fetch risks
  const { data: risks = [], isLoading } = useQuery({
    queryKey: ['risks', projectId],
    queryFn: () => apiGet<RiskItem[]>(`/v1/risk/?project_id=${projectId}`),
    enabled: !!projectId,
  });

  // Fetch summary
  const { data: summary } = useQuery({
    queryKey: ['risk-summary', projectId],
    queryFn: () => apiGet<RiskSummary>(`/v1/risk/summary?project_id=${projectId}`),
    enabled: !!projectId,
  });

  // Fetch matrix
  const { data: matrixData } = useQuery({
    queryKey: ['risk-matrix', projectId],
    queryFn: () => apiGet<{ cells: MatrixCell[] }>(`/v1/risk/matrix?project_id=${projectId}`),
    enabled: !!projectId,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/risk/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['risks'] });
      queryClient.invalidateQueries({ queryKey: ['risk-summary'] });
      queryClient.invalidateQueries({ queryKey: ['risk-matrix'] });
      addToast({ type: 'success', title: t('risk.deleted', { defaultValue: 'Risk deleted' }) });
    },
    onError: (err: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message }),
  });

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['risks'] });
    queryClient.invalidateQueries({ queryKey: ['risk-summary'] });
    queryClient.invalidateQueries({ queryKey: ['risk-matrix'] });
  }, [queryClient]);

  // Detail view
  if (selectedRiskId) {
    return (
      <div className="mx-auto max-w-5xl px-6 py-6">
        <DetailView riskId={selectedRiskId} onBack={() => setSelectedRiskId(null)} />
      </div>
    );
  }

  const currency = project?.currency || summary?.currency || 'EUR';

  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('nav.risk_register', { defaultValue: 'Risk Register' }) },
        ]}
      />

      {/* Header */}
      <div className="mt-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('nav.risk_register', { defaultValue: 'Risk Register' })}
          </h1>
          {project && <p className="mt-1 text-sm text-content-secondary">{project.name}</p>}
        </div>
        <Button variant="primary" onClick={() => setShowCreate(true)} disabled={!projectId}>
          <Plus size={16} className="mr-1.5" />
          {t('risk.new', { defaultValue: 'Add Risk' })}
        </Button>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Card className="p-4">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary">
                <ShieldAlert size={16} className="text-content-tertiary" />
              </div>
              <div>
                <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                  {t('risk.total', { defaultValue: 'Total Risks' })}
                </p>
                <p className="text-lg font-semibold text-content-primary">{summary.total_risks}</p>
              </div>
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-50 dark:bg-red-950/30">
                <AlertTriangle size={16} className="text-semantic-error" />
              </div>
              <div>
                <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                  {t('risk.high_critical', { defaultValue: 'High / Critical' })}
                </p>
                <p className="text-lg font-semibold text-semantic-error">{summary.high_critical_count}</p>
              </div>
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary">
                <DollarSign size={16} className="text-content-tertiary" />
              </div>
              <div>
                <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                  {t('risk.exposure', { defaultValue: 'Total Exposure' })}
                </p>
                <p className="text-lg font-semibold text-semantic-error">
                  {formatCurrency(summary.total_exposure, currency)}
                </p>
              </div>
            </div>
          </Card>
          <Card className="p-4">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-green-50 dark:bg-green-950/30">
                <Shield size={16} className="text-[#15803d]" />
              </div>
              <div>
                <p className="text-2xs text-content-tertiary uppercase tracking-wide">
                  {t('risk.mitigated', { defaultValue: 'Mitigated' })}
                </p>
                <p className="text-lg font-semibold text-[#15803d]">{summary.mitigated_count}</p>
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* Risk Matrix */}
      {matrixData?.cells && matrixData.cells.length > 0 && (
        <div className="mt-6">
          <RiskMatrix cells={matrixData.cells} />
        </div>
      )}

      {/* Risk list table */}
      <div className="mt-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
          </div>
        ) : risks.length === 0 ? (
          <Card>
            <EmptyState
              icon={<ShieldAlert size={24} />}
              title={t('risk.empty', { defaultValue: 'No risks registered' })}
              description={t('risk.empty_desc', {
                defaultValue: 'Add risks to track potential issues and mitigation strategies',
              })}
              action={{
                label: t('risk.new', { defaultValue: 'Add Risk' }),
                onClick: () => setShowCreate(true),
              }}
            />
          </Card>
        ) : (
          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-surface-secondary/50">
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('risk.code', { defaultValue: 'Code' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('common.title', { defaultValue: 'Title' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('risk.category', { defaultValue: 'Category' })}
                    </th>
                    <th className="px-4 py-3 text-center font-medium text-content-secondary">
                      {t('risk.probability_short', { defaultValue: 'Prob.' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('risk.impact', { defaultValue: 'Impact' })}
                    </th>
                    <th className="px-4 py-3 text-center font-medium text-content-secondary">
                      {t('risk.score', { defaultValue: 'Score' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('common.status', { defaultValue: 'Status' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-secondary">
                      {t('risk.owner', { defaultValue: 'Owner' })}
                    </th>
                    <th className="px-4 py-3 w-16" />
                  </tr>
                </thead>
                <tbody>
                  {risks.map((risk) => (
                    <tr
                      key={risk.id}
                      className="border-b border-border last:border-0 hover:bg-surface-secondary/30 cursor-pointer"
                      onClick={() => setSelectedRiskId(risk.id)}
                    >
                      <td className="px-4 py-3 font-mono text-xs text-content-secondary">{risk.code}</td>
                      <td className="px-4 py-3 text-content-primary font-medium max-w-[200px] truncate">
                        {risk.title}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant="neutral">
                          {t(`risk.cat_${risk.category}`, { defaultValue: CATEGORY_LABELS[risk.category] || risk.category })}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-center text-content-secondary tabular-nums">
                        {(risk.probability * 100).toFixed(0)}%
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant={
                            risk.impact_severity === 'critical'
                              ? 'error'
                              : risk.impact_severity === 'high'
                                ? 'warning'
                                : risk.impact_severity === 'medium'
                                  ? 'blue'
                                  : 'neutral'
                          }
                        >
                          {t(`risk.severity_${risk.impact_severity}`, {
                            defaultValue: SEVERITY_LABELS[risk.impact_severity] || risk.impact_severity,
                          })}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-center font-medium tabular-nums text-content-primary">
                        {risk.risk_score.toFixed(1)}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={STATUS_COLORS[risk.status] || 'neutral'}>
                          {t(`risk.status_${risk.status}`, { defaultValue: risk.status })}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-content-secondary text-xs truncate max-w-[100px]">
                        {risk.owner_name || '-'}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              deleteMut.mutate(risk.id);
                            }}
                            className="text-content-tertiary hover:text-semantic-error transition-colors p-1"
                            title={t('common.delete', { defaultValue: 'Delete' })}
                          >
                            <Trash2 size={14} />
                          </button>
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

      {showCreate && projectId && (
        <CreateDialog
          projectId={projectId}
          currency={currency}
          onClose={() => setShowCreate(false)}
          onCreated={handleRefresh}
        />
      )}
    </div>
  );
}

export default RiskRegisterPage;
