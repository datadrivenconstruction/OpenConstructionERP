/**
 * BOQSummaryPanel — Quality score ring, Tips panel, Empty state onboarding,
 * and Quick Add FAB for the BOQ Editor.
 *
 * Extracted from BOQEditorPage.tsx for modularity.
 */

import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  Plus,
  Download,
  ShieldCheck,
  ChevronDown,
  ChevronRight,
  FileText,
  Sparkles,
  Lightbulb,
  Layers,
  ListPlus,
  Database,
  BookTemplate,
  CheckCircle2,
  Hash,
  DollarSign,
  Calculator,
  Percent,
} from 'lucide-react';
import { Button } from '@/shared/ui';
import type { QualityBreakdown, Tip } from './boqHelpers';

/* ── QualityRow (used by QualityScoreRing tooltip) ───────────────────── */

function QualityRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) {
  const rounded = Math.round(value);
  let barColor: string;
  if (rounded > 80) barColor = 'bg-semantic-success';
  else if (rounded >= 50) barColor = 'bg-semantic-warning';
  else barColor = 'bg-semantic-error';

  return (
    <div className="flex items-center gap-2">
      <span className="text-content-tertiary shrink-0">{icon}</span>
      <span className="flex-1 text-xs text-content-secondary">{label}</span>
      <div className="w-16 h-1.5 rounded-full bg-surface-tertiary shrink-0 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${rounded}%` }}
        />
      </div>
      <span className="text-xs font-medium text-content-primary tabular-nums w-8 text-right">
        {rounded}%
      </span>
    </div>
  );
}

/* ── QualityScoreRing (SVG circular progress) ─────────────────────── */

export function QualityScoreRing({
  score,
  breakdown,
  t,
}: {
  score: number;
  breakdown: QualityBreakdown;
  t: (key: string, options?: Record<string, string | number>) => string;
}) {
  const [showTooltip, setShowTooltip] = useState(false);

  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;

  let color: string;
  let bgColor: string;
  let label: string;
  if (score > 80) {
    color = '#22c55e';
    bgColor = 'bg-semantic-success-bg';
    label = t('boq.quality_great', { defaultValue: 'Great' });
  } else if (score >= 50) {
    color = '#eab308';
    bgColor = 'bg-semantic-warning-bg';
    label = t('boq.quality_fair', { defaultValue: 'Fair' });
  } else {
    color = '#ef4444';
    bgColor = 'bg-semantic-error-bg';
    label = t('boq.quality_needs_work', { defaultValue: 'Needs work' });
  }

  return (
    <div
      className="relative"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <div className={`flex items-center gap-2.5 px-3 py-1.5 rounded-lg ${bgColor} cursor-default transition-colors`}>
        {/* SVG ring */}
        <svg width="40" height="40" viewBox="0 0 44 44" className="shrink-0 -rotate-90">
          <circle
            cx="22"
            cy="22"
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            className="text-surface-tertiary"
          />
          <circle
            cx="22"
            cy="22"
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth="3"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            className="transition-all duration-700 ease-out"
          />
        </svg>
        <div className="absolute left-3 top-1/2 -translate-y-1/2 w-10 h-10 flex items-center justify-center">
          <span className="text-xs font-bold tabular-nums" style={{ color }}>
            {score}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
            {t('boq.quality', { defaultValue: 'Quality' })}
          </span>
          <span className="text-xs font-semibold text-content-primary">{label}</span>
        </div>
      </div>

      {/* Tooltip breakdown */}
      {showTooltip && (
        <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 z-50 w-64 rounded-xl border border-border-light bg-surface-elevated shadow-lg p-4 animate-fade-in">
          <p className="text-xs font-semibold text-content-primary mb-3">
            {t('boq.quality_breakdown', { defaultValue: 'Quality Breakdown' })}
          </p>
          <div className="space-y-2.5">
            <QualityRow
              icon={<FileText size={13} />}
              label={t('boq.quality_descriptions', { defaultValue: 'Descriptions filled' })}
              value={breakdown.withDescription}
            />
            <QualityRow
              icon={<Hash size={13} />}
              label={t('boq.quality_quantities', { defaultValue: 'Quantities set' })}
              value={breakdown.withQuantity}
            />
            <QualityRow
              icon={<DollarSign size={13} />}
              label={t('boq.quality_rates', { defaultValue: 'Rates set' })}
              value={breakdown.withRate}
            />
            <div className="flex items-center gap-2">
              <Percent size={13} className="text-content-tertiary shrink-0" />
              <span className="flex-1 text-xs text-content-secondary">
                {t('boq.quality_markups', { defaultValue: 'Markups added' })}
              </span>
              {breakdown.hasMarkups ? (
                <CheckCircle2 size={14} className="text-semantic-success shrink-0" />
              ) : (
                <span className="text-xs text-semantic-error font-medium">
                  {t('boq.quality_missing', { defaultValue: 'Missing' })}
                </span>
              )}
            </div>
          </div>
          <div className="mt-3 pt-2.5 border-t border-border-light">
            <p className="text-2xs text-content-tertiary">
              {t('boq.quality_hint', { defaultValue: 'Fill in all fields to reach 100% and ensure estimate accuracy.' })}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── TipsPanel (collapsible, remembers dismissal in localStorage) ── */

const TIPS_STORAGE_KEY = 'oe_boq_tips_dismissed';

export function TipsPanel({
  tips,
  t,
}: {
  tips: Tip[];
  t: (key: string, options?: Record<string, string>) => string;
}) {
  const [dismissed, setDismissed] = useState<Set<string>>(() => {
    try {
      const stored = localStorage.getItem(TIPS_STORAGE_KEY);
      return stored ? new Set(JSON.parse(stored) as string[]) : new Set();
    } catch {
      return new Set();
    }
  });
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('oe_tips_dismissed') !== 'false');

  const visibleTips = tips.filter((tip) => !dismissed.has(tip.id));

  const handleDismiss = useCallback(
    (tipId: string) => {
      setDismissed((prev) => {
        const next = new Set(prev);
        next.add(tipId);
        try {
          localStorage.setItem(TIPS_STORAGE_KEY, JSON.stringify([...next]));
        } catch {
          // Storage full or restricted
        }
        return next;
      });
    },
    [],
  );

  if (visibleTips.length === 0) return null;

  return (
    <div className="mb-2 rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden animate-fade-in">
      <button
        onClick={() => setCollapsed((prev) => {
          const next = !prev;
          try { localStorage.setItem('oe_tips_dismissed', next ? 'true' : 'false'); } catch { /* noop */ }
          return next;
        })}
        className="flex w-full items-center justify-between px-4 py-3 hover:bg-surface-secondary/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Lightbulb size={15} className="text-[#eab308]" />
          <span className="text-xs font-semibold text-content-primary">
            {t('boq.tips_title', { defaultValue: 'Tips & Hints' })}
          </span>
          <span className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-[#eab308]/10 px-1 text-2xs font-medium text-[#b45309] tabular-nums">
            {visibleTips.length}
          </span>
        </div>
        {collapsed ? <ChevronRight size={14} className="text-content-tertiary" /> : <ChevronDown size={14} className="text-content-tertiary" />}
      </button>

      {!collapsed && (
        <div className="border-t border-border-light divide-y divide-border-light">
          {visibleTips.map((tip) => (
            <div key={tip.id} className="flex items-start gap-3 px-4 py-2.5">
              <span className="mt-0.5 h-1.5 w-1.5 rounded-full bg-[#eab308] shrink-0" />
              <p className="flex-1 text-xs text-content-secondary leading-relaxed">{tip.text}</p>
              <button
                onClick={() => handleDismiss(tip.id)}
                className="shrink-0 text-2xs font-medium text-content-tertiary hover:text-content-primary transition-colors"
              >
                {t('boq.got_it', { defaultValue: 'Got it' })}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── QuickAddFAB (floating action button) ───────────────────────────── */

export function QuickAddFAB({
  onAddPosition,
  onAddSection,
  onImportFromCosts,
  onUseTemplate,
  t,
}: {
  onAddPosition: () => void;
  onAddSection: () => void;
  onImportFromCosts: () => void;
  onUseTemplate: () => void;
  t: (key: string, options?: Record<string, string>) => string;
}) {
  const [open, setOpen] = useState(false);
  const fabRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (fabRef.current && !fabRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const actions = [
    {
      id: 'position',
      icon: <ListPlus size={16} />,
      label: t('boq.quick_add_position', { defaultValue: 'Add Position' }),
      description: t('boq.quick_add_position_desc', { defaultValue: 'Add an empty position to the current section' }),
      onClick: onAddPosition,
    },
    {
      id: 'section',
      icon: <Layers size={16} />,
      label: t('boq.quick_add_section', { defaultValue: 'Add Section' }),
      description: t('boq.quick_add_section_desc', { defaultValue: 'Create a new section to organize positions' }),
      onClick: onAddSection,
    },
    {
      id: 'costs',
      icon: <Database size={16} />,
      label: t('boq.quick_import_costs', { defaultValue: 'Import from Cost Database' }),
      description: t('boq.quick_import_costs_desc', { defaultValue: 'Browse and select items from the cost database' }),
      onClick: onImportFromCosts,
    },
    {
      id: 'template',
      icon: <BookTemplate size={16} />,
      label: t('boq.quick_use_template', { defaultValue: 'Use Template' }),
      description: t('boq.quick_use_template_desc', { defaultValue: 'Start from a pre-built estimate template' }),
      onClick: onUseTemplate,
    },
  ];

  return (
    <div ref={fabRef} className="fixed bottom-8 right-8 z-40 print:hidden">
      {/* FAB menu */}
      {open && (
        <div className="absolute bottom-16 right-0 w-72 rounded-xl border border-border-light bg-surface-elevated shadow-lg overflow-hidden animate-fade-in">
          <div className="px-4 py-3 border-b border-border-light">
            <p className="text-xs font-semibold text-content-primary">
              {t('boq.quick_add', { defaultValue: 'Quick Add' })}
            </p>
          </div>
          <div className="py-1">
            {actions.map((action) => (
              <button
                key={action.id}
                onClick={() => {
                  setOpen(false);
                  action.onClick();
                }}
                className="flex w-full items-start gap-3 px-4 py-3 hover:bg-surface-secondary transition-colors text-left"
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle text-oe-blue">
                  {action.icon}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-content-primary">{action.label}</p>
                  <p className="text-2xs text-content-tertiary mt-0.5">{action.description}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* FAB button */}
      <button
        onClick={() => setOpen((prev) => !prev)}
        className={`flex h-12 w-12 items-center justify-center rounded-full shadow-lg transition-all duration-200 ease-out transform-gpu ${
          open
            ? 'bg-content-primary text-content-inverse rotate-45 scale-95'
            : 'bg-oe-blue text-content-inverse hover:bg-oe-blue-hover hover:scale-105 hover:shadow-xl active:scale-95'
        }`}
      >
        <Plus size={22} strokeWidth={2.5} />
      </button>
    </div>
  );
}

/* ── EmptyBOQOnboarding ─────────────────────────────────────────────── */

export function EmptyBOQOnboarding({
  onAddSection,
  onAddPosition,
  hasMarkups,
  sectionCount,
  positionCount,
  t,
}: {
  onAddSection: () => void;
  onAddPosition: () => void;
  hasMarkups: boolean;
  sectionCount: number;
  positionCount: number;
  t: (key: string, options?: Record<string, string>) => string;
}) {
  const steps = [
    {
      id: 'sections',
      icon: <Layers size={20} />,
      title: t('boq.step_add_sections', { defaultValue: 'Add sections' }),
      description: t('boq.step_add_sections_desc', { defaultValue: 'Organize your estimate into sections (e.g., Foundations, Walls, Roof)' }),
      action: t('boq.add_section', { defaultValue: 'Add Section' }),
      onClick: onAddSection,
      complete: sectionCount > 0,
    },
    {
      id: 'positions',
      icon: <ListPlus size={20} />,
      title: t('boq.step_add_positions', { defaultValue: 'Add positions' }),
      description: t('boq.step_add_positions_desc', { defaultValue: 'Add line items with descriptions and units to each section' }),
      action: t('boq.add_position', { defaultValue: 'Add Position' }),
      onClick: onAddPosition,
      complete: positionCount > 0,
    },
    {
      id: 'quantities',
      icon: <Calculator size={20} />,
      title: t('boq.step_set_quantities', { defaultValue: 'Set quantities' }),
      description: t('boq.step_set_quantities_desc', { defaultValue: 'Enter quantities and unit rates for each position to calculate totals' }),
      action: null,
      onClick: undefined,
      complete: false, // computed dynamically only when there are positions
    },
    {
      id: 'review',
      icon: <CheckCircle2 size={20} />,
      title: t('boq.step_review', { defaultValue: 'Review totals' }),
      description: t('boq.step_review_desc', { defaultValue: 'Add markups for overhead costs and profit, then review your grand total' }),
      action: null,
      onClick: undefined,
      complete: hasMarkups,
    },
  ];

  const completedCount = steps.filter((s) => s.complete).length;

  return (
    <div className="px-4 py-10">
      <div className="max-w-lg mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-oe-blue-subtle">
            <Sparkles size={24} className="text-oe-blue" />
          </div>
          <h3 className="text-lg font-semibold text-content-primary">
            {t('boq.start_building', { defaultValue: 'Start building your estimate' })}
          </h3>
          <p className="mt-1.5 text-sm text-content-secondary max-w-sm mx-auto">
            {t('boq.start_building_desc', { defaultValue: 'Follow these steps to create a professional Bill of Quantities' })}
          </p>
        </div>

        {/* Progress dots */}
        <div className="flex items-center justify-center gap-2 mb-8">
          {steps.map((step, i) => (
            <div
              key={step.id}
              className={`h-2 rounded-full transition-all duration-300 ${
                step.complete
                  ? 'w-8 bg-semantic-success'
                  : i === completedCount
                    ? 'w-8 bg-oe-blue'
                    : 'w-2 bg-surface-tertiary'
              }`}
            />
          ))}
        </div>

        {/* Steps */}
        <div className="space-y-3">
          {steps.map((step, i) => (
            <div
              key={step.id}
              className={`flex items-start gap-4 p-4 rounded-xl border transition-all ${
                step.complete
                  ? 'border-semantic-success/30 bg-semantic-success-bg/30'
                  : i === completedCount
                    ? 'border-oe-blue/30 bg-oe-blue-subtle/30'
                    : 'border-border-light bg-surface-elevated'
              }`}
            >
              {/* Step number / check */}
              <div
                className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-colors ${
                  step.complete
                    ? 'bg-semantic-success/10 text-semantic-success'
                    : i === completedCount
                      ? 'bg-oe-blue-subtle text-oe-blue'
                      : 'bg-surface-secondary text-content-tertiary'
                }`}
              >
                {step.complete ? <CheckCircle2 size={18} /> : step.icon}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <p
                  className={`text-sm font-semibold ${
                    step.complete ? 'text-semantic-success line-through' : 'text-content-primary'
                  }`}
                >
                  {step.title}
                </p>
                <p className="text-xs text-content-tertiary mt-0.5">{step.description}</p>
              </div>

              {/* Action button */}
              {step.action && step.onClick && !step.complete && (
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Plus size={14} />}
                  onClick={step.onClick}
                >
                  {step.action}
                </Button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Export Quality Warning Dialog ────────────────────────────────────── */

export function ExportWarningDialog({
  exportWarning,
  onCancel,
  onConfirm,
  t,
}: {
  exportWarning: { format: 'excel' | 'csv' | 'pdf' | 'gaeb'; score: number };
  onCancel: () => void;
  onConfirm: (format: 'excel' | 'csv' | 'pdf' | 'gaeb') => void;
  t: (key: string, options?: Record<string, string | number>) => string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="w-96 rounded-xl border border-border bg-surface-elevated p-5 shadow-2xl animate-fade-in">
        <div className="flex items-center gap-3 mb-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30">
            <ShieldCheck size={20} className="text-amber-600" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('boq.low_quality_warning', { defaultValue: 'Low Quality Score' })}
            </h3>
            <p className="text-xs text-content-tertiary">
              {t('boq.quality_score_value', {
                defaultValue: 'Quality score: {{score}}%',
                score: Math.round(exportWarning.score),
              })}
            </p>
          </div>
        </div>
        <p className="text-xs text-content-secondary mb-4">
          {t('boq.export_quality_warning_desc', {
            defaultValue:
              'Your estimate has a quality score below 60%. Missing quantities, zero prices, or incomplete descriptions may affect the exported document. Consider reviewing the estimate before exporting.',
          })}
        </p>
        <div className="flex items-center justify-end gap-2">
          <button
            onClick={onCancel}
            className="flex h-8 items-center rounded-lg bg-surface-secondary px-4 text-xs font-medium text-content-secondary hover:bg-surface-tertiary transition-colors"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            onClick={() => onConfirm(exportWarning.format)}
            className="flex h-8 items-center gap-1.5 rounded-lg bg-amber-500 px-4 text-xs font-medium text-white hover:bg-amber-600 transition-colors"
          >
            <Download size={13} />
            {t('boq.export_anyway', { defaultValue: 'Export Anyway' })}
          </button>
        </div>
      </div>
    </div>
  );
}

