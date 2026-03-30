/**
 * AISmartPanel — LLM-powered AI actions for BOQ positions.
 *
 * Features:
 * - Enhance Description: improve short descriptions with technical specs
 * - Suggest Prerequisites: find missing related positions
 * - Escalate Rate: adjust rates for inflation/time
 * - Check Scope: analyze full BOQ for completeness (global action)
 *
 * Works with any LLM provider (Anthropic, OpenAI, Gemini) via user's API key.
 */

import { useCallback, useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowUpRight,
  Brain,
  ChevronDown,
  ChevronRight,
  FileText,
  Layers,
  Plus,
  Settings,
  Sparkles,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react';

import { Button } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { fmtWithCurrency } from './boqHelpers';
import {
  boqApi,
  type CheckScopeResponse,
  type CreatePositionData,
  type EnhanceDescriptionResponse,
  type EscalateRateResponse,
  type Position,
  type PrerequisiteItem,
  type SuggestPrerequisitesResponse,
} from './api';

/* ── Props ─────────────────────────────────────────────────────────── */

interface AISmartPanelProps {
  boqId: string;
  isOpen: boolean;
  onClose: () => void;
  selectedPosition: Position | null;
  allPositions: Position[];
  onUpdatePosition: (positionId: string, data: { description?: string; unit_rate?: number }) => void;
  onAddPosition: (data: CreatePositionData) => void;
  currencyCode?: string;
  locale?: string;
  projectRegion?: string;
}

/* ── Component ─────────────────────────────────────────────────────── */

export function AISmartPanel({
  boqId,
  isOpen,
  onClose,
  selectedPosition,
  allPositions,
  onUpdatePosition,
  onAddPosition,
  currencyCode = 'EUR',
  locale = 'de-DE',
  projectRegion,
}: AISmartPanelProps) {
  const { t, i18n } = useTranslation();

  /* ── AI configuration check ─────────────────────────────────────── */
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null);
  const [aiProvider, setAiProvider] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    apiGet<Record<string, unknown>>('/v1/ai/settings')
      .then((s) => {
        const hasKey =
          !!s.anthropic_api_key_set || !!s.openai_api_key_set || !!s.gemini_api_key_set ||
          !!s.openrouter_api_key_set || !!s.mistral_api_key_set || !!s.groq_api_key_set ||
          !!s.deepseek_api_key_set;
        setAiConfigured(hasKey);
        setAiProvider((s.provider as string) || '');
      })
      .catch(() => setAiConfigured(false));
  }, [isOpen]);

  /* ── Loading states ──────────────────────────────────────────────── */
  const [enhanceLoading, setEnhanceLoading] = useState(false);
  const [enhanceResult, setEnhanceResult] = useState<EnhanceDescriptionResponse | null>(null);
  const [prereqLoading, setPrereqLoading] = useState(false);
  const [prereqResult, setPrereqResult] = useState<SuggestPrerequisitesResponse | null>(null);
  const [escalateLoading, setEscalateLoading] = useState(false);
  const [escalateResult, setEscalateResult] = useState<EscalateRateResponse | null>(null);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [scopeResult, setScopeResult] = useState<CheckScopeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedSection, setExpandedSection] = useState<string | null>(null);

  const toggleSection = (section: string) =>
    setExpandedSection((prev) => (prev === section ? null : section));

  /* ── Enhance Description ─────────────────────────────────────────── */
  const handleEnhance = useCallback(async () => {
    if (!selectedPosition?.description) return;
    setEnhanceLoading(true);
    setError(null);
    setEnhanceResult(null);
    try {
      const res = await boqApi.enhanceDescription({
        description: selectedPosition.description,
        unit: selectedPosition.unit,
        classification: selectedPosition.classification,
        locale: i18n.language,
      });
      setEnhanceResult(res);
      setExpandedSection('enhance');
    } catch (e: unknown) {
      setError((e as Error).message || 'Enhancement failed');
    } finally {
      setEnhanceLoading(false);
    }
  }, [selectedPosition]);

  const applyEnhancedDescription = useCallback(() => {
    if (!selectedPosition || !enhanceResult) return;
    onUpdatePosition(selectedPosition.id, {
      description: enhanceResult.enhanced_description,
    });
    setEnhanceResult(null);
  }, [selectedPosition, enhanceResult, onUpdatePosition]);

  /* ── Suggest Prerequisites ───────────────────────────────────────── */
  const handleSuggestPrereqs = useCallback(async () => {
    if (!selectedPosition?.description) return;
    setPrereqLoading(true);
    setError(null);
    setPrereqResult(null);
    try {
      const existing = allPositions
        .filter((p) => p.description && p.description !== selectedPosition.description)
        .map((p) => p.description)
        .slice(0, 30);
      const res = await boqApi.suggestPrerequisites({
        description: selectedPosition.description,
        unit: selectedPosition.unit,
        classification: selectedPosition.classification,
        existing_descriptions: existing,
        locale: i18n.language,
      });
      setPrereqResult(res);
      setExpandedSection('prereqs');
    } catch (e: unknown) {
      setError((e as Error).message || 'Suggestion failed');
    } finally {
      setPrereqLoading(false);
    }
  }, [selectedPosition, allPositions]);

  const addPrereqAsPosition = useCallback(
    (item: PrerequisiteItem) => {
      onAddPosition({
        boq_id: boqId,
        ordinal: '',
        description: item.description,
        unit: item.unit,
        quantity: 1,
        unit_rate: item.typical_rate_eur,
      });
    },
    [boqId, onAddPosition],
  );

  /* ── Escalate Rate ───────────────────────────────────────────────── */
  const handleEscalate = useCallback(async () => {
    if (!selectedPosition?.description || !selectedPosition.unit_rate) return;
    setEscalateLoading(true);
    setError(null);
    setEscalateResult(null);
    try {
      const res = await boqApi.escalateRate({
        description: selectedPosition.description,
        unit: selectedPosition.unit,
        rate: selectedPosition.unit_rate,
        region: projectRegion || 'DACH',
        locale: i18n.language,
      });
      setEscalateResult(res);
      setExpandedSection('escalate');
    } catch (e: unknown) {
      setError((e as Error).message || 'Escalation failed');
    } finally {
      setEscalateLoading(false);
    }
  }, [selectedPosition, projectRegion]);

  const applyEscalatedRate = useCallback(() => {
    if (!selectedPosition || !escalateResult) return;
    onUpdatePosition(selectedPosition.id, {
      unit_rate: escalateResult.escalated_rate,
    });
    setEscalateResult(null);
  }, [selectedPosition, escalateResult, onUpdatePosition]);

  /* ── Check Scope ─────────────────────────────────────────────────── */
  const handleCheckScope = useCallback(async () => {
    setScopeLoading(true);
    setError(null);
    setScopeResult(null);
    try {
      const res = await boqApi.checkScope(boqId, {
        project_type: 'general',
        region: projectRegion || 'DACH',
        locale: i18n.language,
      });
      setScopeResult(res);
      setExpandedSection('scope');
    } catch (e: unknown) {
      setError((e as Error).message || 'Scope check failed');
    } finally {
      setScopeLoading(false);
    }
  }, [boqId, projectRegion]);

  const addScopeMissingItem = useCallback(
    (item: { description: string; unit: string; estimated_rate: number }) => {
      onAddPosition({
        boq_id: boqId,
        ordinal: '',
        description: item.description,
        unit: item.unit,
        quantity: 1,
        unit_rate: item.estimated_rate,
      });
    },
    [boqId, onAddPosition],
  );

  /* ── Render ──────────────────────────────────────────────────────── */
  return (
    <div
      className={`fixed right-0 top-0 z-50 h-full w-[400px] bg-surface-elevated border-l border-border-light shadow-xl flex flex-col transition-transform duration-300 ease-in-out ${
        isOpen ? 'translate-x-0' : 'translate-x-full'
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-light shrink-0">
        <div className="flex items-center gap-2">
          <Brain size={16} className="text-primary" />
          <span className="font-semibold text-sm">
            {t('boq.ai_smart_panel', { defaultValue: 'AI Smart Actions' })}
          </span>
        </div>
        <button onClick={onClose} className="p-1 rounded hover:bg-surface-hover transition-colors">
          <X size={16} />
        </button>
      </div>

      {/* Selected position info */}
      <div className="px-4 py-2 border-b border-border-light bg-surface-secondary/50 shrink-0">
        {selectedPosition ? (
          <div>
            <p className="text-xs text-text-muted">
              {t('boq.ai_selected_position', { defaultValue: 'Selected Position' })}
            </p>
            <p className="text-sm font-medium truncate">{selectedPosition.description || '—'}</p>
            <p className="text-xs text-text-muted">
              {selectedPosition.unit} | {fmtWithCurrency(selectedPosition.unit_rate, locale, currencyCode)}
            </p>
          </div>
        ) : (
          <p className="text-xs text-text-muted italic">
            {t('boq.ai_no_selection', { defaultValue: 'Select a position in the grid for per-position AI actions' })}
          </p>
        )}
      </div>

      {/* AI not configured warning */}
      {aiConfigured === false && (
        <div className="mx-4 mt-3 px-3 py-3 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-medium text-amber-800 dark:text-amber-300">
                {t('boq.ai_not_configured', { defaultValue: 'AI not configured' })}
              </p>
              <p className="text-[11px] text-amber-700 dark:text-amber-400/80 mt-0.5">
                {t('boq.ai_not_configured_desc', { defaultValue: 'Add your API key in Settings to use AI Smart Actions.' })}
              </p>
              <Link
                to="/settings"
                className="inline-flex items-center gap-1 mt-1.5 text-[11px] font-medium text-amber-700 dark:text-amber-300 hover:underline"
              >
                <Settings size={11} />
                {t('boq.go_to_settings', { defaultValue: 'Configure AI' })}
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* Connected indicator */}
      {aiConfigured === true && (
        <div className="mx-4 mt-2 flex items-center gap-1.5 text-[11px] text-semantic-success font-medium">
          <span className="h-1.5 w-1.5 rounded-full bg-semantic-success animate-pulse" />
          {t('boq.ai_connected_via', { defaultValue: 'Connected via {{provider}}', provider: aiProvider || 'AI' })}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mx-4 mt-2 px-3 py-2 rounded-md bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-xs">
          {error}
        </div>
      )}

      {/* Actions */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {/* ── Per-position actions ─────────────────────────────────────── */}
        <div className="text-xs font-semibold text-text-muted uppercase tracking-wider">
          {t('boq.ai_position_actions', { defaultValue: 'Position Actions' })}
        </div>

        {/* Enhance Description */}
        <ActionCard
          icon={<FileText size={15} />}
          title={t('boq.ai_enhance_title', { defaultValue: 'Enhance Description' })}
          subtitle={t('boq.ai_enhance_subtitle', { defaultValue: 'Add technical specs, standards, material grades' })}
          loading={enhanceLoading}
          disabled={!selectedPosition?.description}
          onClick={handleEnhance}
          expanded={expandedSection === 'enhance'}
          onToggle={() => toggleSection('enhance')}
          hasResult={!!enhanceResult}
        >
          {enhanceResult && (
            <div className="space-y-2">
              <div className="p-2 rounded bg-green-50 dark:bg-green-900/20 text-sm">
                {enhanceResult.enhanced_description}
              </div>
              {enhanceResult.specifications.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-text-muted mb-1">
                    {t('boq.ai_specs', { defaultValue: 'Specifications' })}
                  </p>
                  <ul className="text-xs space-y-0.5">
                    {enhanceResult.specifications.map((s, i) => (
                      <li key={i} className="text-text-secondary">• {s}</li>
                    ))}
                  </ul>
                </div>
              )}
              {enhanceResult.standards.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {enhanceResult.standards.map((s, i) => (
                    <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400">
                      {s}
                    </span>
                  ))}
                </div>
              )}
              <Button size="sm" variant="primary" icon={<Zap size={13} />} onClick={applyEnhancedDescription}>
                {t('boq.ai_apply_description', { defaultValue: 'Apply Enhanced Description' })}
              </Button>
            </div>
          )}
        </ActionCard>

        {/* Suggest Prerequisites */}
        <ActionCard
          icon={<Layers size={15} />}
          title={t('boq.ai_prereqs_title', { defaultValue: 'Suggest Related Items' })}
          subtitle={t('boq.ai_prereqs_subtitle', { defaultValue: 'Find missing prerequisites, companions, successors' })}
          loading={prereqLoading}
          disabled={!selectedPosition?.description}
          onClick={handleSuggestPrereqs}
          expanded={expandedSection === 'prereqs'}
          onToggle={() => toggleSection('prereqs')}
          hasResult={!!prereqResult}
        >
          {prereqResult && prereqResult.suggestions.length > 0 && (
            <div className="space-y-2">
              {prereqResult.suggestions.map((item, i) => (
                <div key={i} className="p-2 rounded border border-border-light bg-surface">
                  <div className="flex items-start gap-2">
                    <span className={`shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded ${
                      item.relationship === 'prerequisite'
                        ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                        : item.relationship === 'successor'
                        ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
                        : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
                    }`}>
                      {item.relationship}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium leading-tight">{item.description}</p>
                      <p className="text-[10px] text-text-muted mt-0.5">
                        {item.unit} | {fmtWithCurrency(item.typical_rate_eur, locale, currencyCode)}
                      </p>
                      <p className="text-[10px] text-text-muted italic mt-0.5">{item.reason}</p>
                    </div>
                  </div>
                  <button
                    onClick={() => addPrereqAsPosition(item)}
                    className="flex items-center gap-1 mt-1.5 px-2 py-1 text-xs font-medium rounded bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                  >
                    <Plus size={12} />
                    {t('boq.ai_add_to_boq', { defaultValue: 'Add to BOQ' })}
                  </button>
                </div>
              ))}
            </div>
          )}
          {prereqResult && prereqResult.suggestions.length === 0 && (
            <p className="text-xs text-text-muted italic">
              {t('boq.ai_no_prereqs', { defaultValue: 'No missing items found — BOQ looks complete for this position.' })}
            </p>
          )}
        </ActionCard>

        {/* Escalate Rate */}
        <ActionCard
          icon={<TrendingUp size={15} />}
          title={t('boq.ai_escalate_title', { defaultValue: 'Escalate Rate' })}
          subtitle={t('boq.ai_escalate_subtitle', { defaultValue: 'Adjust rate for inflation and market changes' })}
          loading={escalateLoading}
          disabled={!selectedPosition?.unit_rate}
          onClick={handleEscalate}
          expanded={expandedSection === 'escalate'}
          onToggle={() => toggleSection('escalate')}
          hasResult={!!escalateResult}
        >
          {escalateResult && (
            <div className="space-y-2">
              <div className="flex items-center gap-3 p-2 rounded bg-surface-secondary">
                <div className="text-center">
                  <p className="text-[10px] text-text-muted">{t('boq.ai_original', { defaultValue: 'Original' })}</p>
                  <p className="text-sm font-mono">{fmtWithCurrency(escalateResult.original_rate, locale, currencyCode)}</p>
                </div>
                <ArrowUpRight size={16} className="text-green-500 shrink-0" />
                <div className="text-center">
                  <p className="text-[10px] text-text-muted">{t('boq.ai_escalated', { defaultValue: 'Escalated' })}</p>
                  <p className="text-sm font-mono font-bold text-green-600 dark:text-green-400">
                    {fmtWithCurrency(escalateResult.escalated_rate, locale, currencyCode)}
                  </p>
                </div>
                <span className="ml-auto text-xs font-bold text-green-600 dark:text-green-400">
                  +{escalateResult.escalation_percent}%
                </span>
              </div>
              {/* Factors */}
              <div className="grid grid-cols-3 gap-1 text-center">
                <FactorBadge label={t('boq.ai_factor_material', { defaultValue: 'Material' })} value={escalateResult.factors.material_inflation} />
                <FactorBadge label={t('boq.ai_factor_labor', { defaultValue: 'Labor' })} value={escalateResult.factors.labor_cost_change} />
                <FactorBadge label={t('boq.ai_factor_region', { defaultValue: 'Regional' })} value={escalateResult.factors.regional_adjustment} />
              </div>
              <p className="text-[10px] text-text-muted italic">{escalateResult.reasoning}</p>
              <div className="flex items-center gap-2">
                <ConfidenceBadge level={escalateResult.confidence} />
                <Button size="sm" variant="primary" icon={<Zap size={13} />} onClick={applyEscalatedRate}>
                  {t('boq.ai_apply_rate', { defaultValue: 'Apply Escalated Rate' })}
                </Button>
              </div>
            </div>
          )}
        </ActionCard>

        {/* Divider */}
        <div className="border-t border-border-light pt-3">
          <div className="text-xs font-semibold text-text-muted uppercase tracking-wider">
            {t('boq.ai_global_actions', { defaultValue: 'BOQ-level Actions' })}
          </div>
        </div>

        {/* Check Scope */}
        <ActionCard
          icon={<AlertTriangle size={15} />}
          title={t('boq.ai_scope_title', { defaultValue: 'Check Scope Completeness' })}
          subtitle={t('boq.ai_scope_subtitle', { defaultValue: 'Find missing trades, work packages, critical items' })}
          loading={scopeLoading}
          disabled={allPositions.length === 0}
          onClick={handleCheckScope}
          expanded={expandedSection === 'scope'}
          onToggle={() => toggleSection('scope')}
          hasResult={!!scopeResult}
        >
          {scopeResult && (
            <div className="space-y-2">
              {/* Score */}
              <div className="flex items-center gap-3">
                <div className="relative w-12 h-12">
                  <svg viewBox="0 0 36 36" className="w-12 h-12 -rotate-90">
                    <circle cx="18" cy="18" r="15.9" fill="none" stroke="currentColor" strokeWidth="2" className="text-surface-secondary" />
                    <circle
                      cx="18" cy="18" r="15.9" fill="none"
                      stroke={scopeResult.completeness_score >= 0.8 ? '#22c55e' : scopeResult.completeness_score >= 0.5 ? '#f59e0b' : '#ef4444'}
                      strokeWidth="2.5"
                      strokeDasharray={`${scopeResult.completeness_score * 100} ${100 - scopeResult.completeness_score * 100}`}
                      strokeLinecap="round"
                    />
                  </svg>
                  <span className="absolute inset-0 flex items-center justify-center text-xs font-bold">
                    {Math.round(scopeResult.completeness_score * 100)}%
                  </span>
                </div>
                <div>
                  <p className="text-sm font-medium">
                    {t('boq.ai_scope_score', { defaultValue: 'Completeness Score' })}
                  </p>
                  <p className="text-xs text-text-muted">{scopeResult.summary}</p>
                </div>
              </div>

              {/* Warnings */}
              {scopeResult.warnings.length > 0 && (
                <div className="space-y-1">
                  {scopeResult.warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-400">
                      <AlertTriangle size={12} className="shrink-0 mt-0.5" />
                      {w}
                    </div>
                  ))}
                </div>
              )}

              {/* Missing items */}
              {scopeResult.missing_items.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-text-muted">
                    {t('boq.ai_missing_items', { defaultValue: 'Missing Items' })} ({scopeResult.missing_items.length})
                  </p>
                  {scopeResult.missing_items.map((item, i) => (
                    <div key={i} className="p-2 rounded border border-border-light bg-surface">
                      <div className="flex items-start gap-2">
                        <span className={`shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          item.priority === 'high'
                            ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                            : item.priority === 'low'
                            ? 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
                            : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
                        }`}>
                          {item.priority}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-medium leading-tight">{item.description}</p>
                          <p className="text-[10px] text-text-muted mt-0.5">{item.category}</p>
                          <p className="text-[10px] text-text-muted italic">{item.reason}</p>
                          <p className="text-[10px] text-text-secondary mt-0.5">
                            {item.unit} | ~{fmtWithCurrency(item.estimated_rate, locale, currencyCode)}
                          </p>
                        </div>
                      </div>
                      <button
                        onClick={() => addScopeMissingItem(item)}
                        className="flex items-center gap-1 mt-1.5 px-2 py-1 text-xs font-medium rounded bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                      >
                        <Plus size={12} />
                        {t('boq.ai_add_to_boq', { defaultValue: 'Add to BOQ' })}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </ActionCard>
      </div>

      {/* Footer */}
      <div className="shrink-0 px-4 py-2 border-t border-border-light text-[10px] text-text-muted">
        <div className="flex items-center gap-1">
          <Sparkles size={10} />
          {t('boq.ai_smart_footer', { defaultValue: 'Powered by your AI provider (Settings > AI). Results are suggestions — always review.' })}
        </div>
      </div>
    </div>
  );
}

/* ── Action Card ───────────────────────────────────────────────────── */

interface ActionCardProps {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  loading: boolean;
  disabled: boolean;
  onClick: () => void;
  expanded: boolean;
  onToggle: () => void;
  hasResult: boolean;
  children?: React.ReactNode;
}

function ActionCard({ icon, title, subtitle, loading, disabled, onClick, expanded, onToggle, hasResult, children }: ActionCardProps) {
  return (
    <div className="border border-border-light rounded-lg bg-surface overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2.5">
        <div className="shrink-0 text-primary">{icon}</div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">{title}</p>
          <p className="text-[10px] text-text-muted truncate">{subtitle}</p>
        </div>
        <button
          onClick={onClick}
          disabled={disabled || loading}
          className="shrink-0 px-2.5 py-1.5 text-xs font-medium rounded-md bg-primary text-white hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
        >
          {loading ? (
            <div className="animate-spin h-3 w-3 border-2 border-white border-t-transparent rounded-full" />
          ) : (
            <Sparkles size={12} />
          )}
          {loading ? 'AI...' : 'Run'}
        </button>
        {hasResult && (
          <button onClick={onToggle} className="shrink-0 p-1 rounded hover:bg-surface-hover transition-colors">
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        )}
      </div>
      {expanded && hasResult && children && (
        <div className="px-3 pb-3 border-t border-border-light pt-2">{children}</div>
      )}
    </div>
  );
}

/* ── Small helpers ─────────────────────────────────────────────────── */

function FactorBadge({ label, value }: { label: string; value: number }) {
  return (
    <div className="px-2 py-1 rounded bg-surface-secondary text-center">
      <p className="text-[10px] text-text-muted">{label}</p>
      <p className={`text-xs font-bold ${value > 0 ? 'text-red-500' : value < 0 ? 'text-green-500' : 'text-text-secondary'}`}>
        {value > 0 ? '+' : ''}{value}%
      </p>
    </div>
  );
}

function ConfidenceBadge({ level }: { level: string }) {
  const colors =
    level === 'high'
      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
      : level === 'medium'
      ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
      : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400';
  return <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${colors}`}>{level}</span>;
}
