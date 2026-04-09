/**
 * BOQToolbar — The toolbar/action bar at the top of the BOQ editor.
 *
 * Contains: undo/redo, add buttons, import/export, validate, recalculate, AI toggle.
 * Extracted from BOQEditorPage.tsx for modularity.
 */

import React, { useState, useRef, useEffect } from 'react';
import {
  Plus,
  Download,
  Upload,
  ClipboardPaste,
  ShieldCheck,
  Layers,
  Database,
  Sparkles,
  Undo2,
  Redo2,
  Clock,
  Columns3,
  ListOrdered,
  FileSpreadsheet,
  FileText,
  FileDown,
  RefreshCw,
  AlertTriangle,
  SearchCheck,
  Check,
  Brain,
} from 'lucide-react';
import { Button } from '@/shared/ui';
import type { QualityBreakdown } from './boqHelpers';

export interface BOQToolbarProps {
  t: (key: string, options?: Record<string, string | number>) => string;
  // Undo / redo
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onShowVersionHistory: () => void;
  // Add actions
  onAddPosition: () => void;
  onAddSection: () => void;
  onOpenCostDb: () => void;
  onOpenAssembly: () => void;
  // Import
  onImportClick: () => void;
  isImporting: boolean;
  importInputRef: React.RefObject<HTMLInputElement | null>;
  onImportInputChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  // Export
  onExport: (format: 'excel' | 'csv' | 'pdf' | 'gaeb') => void;
  // Validate & recalculate
  onValidate: () => void;
  isValidating?: boolean;
  lastValidationScore?: number | null;
  onRecalculate: () => void;
  isRecalculating: boolean;
  isCheckingAnomalies?: boolean;
  // AI
  aiChatOpen: boolean;
  onToggleAiChat: () => void;
  costFinderOpen: boolean;
  onToggleCostFinder: () => void;
  onCheckAnomalies?: () => void;
  onCancelAnomalies?: () => void;
  anomalyCount?: number;
  onAcceptAllAnomalies?: () => void;
  // AI Smart Panel
  smartPanelOpen: boolean;
  onToggleSmartPanel: () => void;
  // Excel paste
  onPasteFromExcel?: () => void;
  // Custom columns
  onManageColumns?: () => void;
  customColumnCount?: number;
  // Renumber positions (gap-of-10 scheme)
  onRenumber?: () => void;
  isRenumbering?: boolean;
  // Quality
  hasPositions: boolean;
  qualityBreakdown: QualityBreakdown;
  qualityScoreRing: React.ReactNode;
}

export function BOQToolbar({
  t,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onShowVersionHistory,
  onAddPosition,
  onAddSection,
  onOpenCostDb,
  onOpenAssembly,
  onImportClick,
  isImporting,
  importInputRef,
  onImportInputChange,
  onExport,
  onValidate,
  isValidating,
  lastValidationScore,
  onRecalculate,
  isRecalculating,
  isCheckingAnomalies,
  aiChatOpen,
  onToggleAiChat,
  costFinderOpen,
  onToggleCostFinder,
  onCheckAnomalies,
  onCancelAnomalies,
  anomalyCount,
  onAcceptAllAnomalies,
  smartPanelOpen,
  onToggleSmartPanel,
  onPasteFromExcel,
  onManageColumns,
  customColumnCount,
  onRenumber,
  isRenumbering,
  hasPositions,
  qualityScoreRing,
}: BOQToolbarProps) {
  /* ── Export dropdown state ─────────────────────────────────────────── */
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) {
        setShowExportMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleExportItem = (format: 'excel' | 'csv' | 'pdf' | 'gaeb') => {
    setShowExportMenu(false);
    onExport(format);
  };

  return (
    <div className="sticky top-0 z-20 bg-surface-primary flex flex-wrap items-center gap-x-2 gap-y-2 px-1 py-2 border-b border-border-light mb-3">
      {/* ── Row-group: Quality + Undo/Redo ─────────────────────────────── */}
      <div className="flex items-center gap-1.5">
        {hasPositions && qualityScoreRing}
        <Button variant="ghost" size="sm" icon={<Undo2 size={15} />} onClick={onUndo} disabled={!canUndo} title={t('boq.undo', { defaultValue: 'Undo (Ctrl+Z)' })} />
        <Button variant="ghost" size="sm" icon={<Redo2 size={15} />} onClick={onRedo} disabled={!canRedo} title={t('boq.redo', { defaultValue: 'Redo (Ctrl+Y)' })} />
        <Button variant="ghost" size="sm" icon={<Clock size={15} />} onClick={onShowVersionHistory} title={t('boq.version_history', { defaultValue: 'Version History' })} />
      </div>

      <div className="w-px h-6 bg-border-light hidden sm:block" />

      {/* ── Row-group: Add ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-1.5">
        <Button variant="primary" size="sm" icon={<Plus size={15} />} onClick={onAddPosition}>
          {t('boq.add_position')}
        </Button>
        <Button variant="secondary" size="sm" icon={<Layers size={15} />} onClick={onAddSection} title={t('boq.add_section')}>
          {t('boq.add_section')}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          icon={<Database size={15} />}
          onClick={onOpenCostDb}
          className="border-oe-blue/30 text-oe-blue hover:bg-oe-blue/10"
          title={t('boq.add_from_database')}
        >
          {t('boq.add_from_database')}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          icon={<Layers size={15} />}
          onClick={onOpenAssembly}
          className="border-purple-300/30 text-purple-600 hover:bg-purple-50"
          title={t('boq.from_assembly', { defaultValue: 'From Assembly' })}
        >
          {t('boq.from_assembly', { defaultValue: 'From Assembly' })}
        </Button>
      </div>

      <div className="w-px h-6 bg-border-light hidden sm:block" />

      {/* ── Row-group: File (Import / Export) ──────────────────────────── */}
      <div className="flex items-center gap-1.5">
        <Button variant="ghost" size="sm" icon={<Upload size={15} />} onClick={onImportClick} loading={isImporting} disabled={isImporting}>
          {t('common.import', { defaultValue: 'Import' })}
        </Button>
        <input ref={importInputRef as React.RefObject<HTMLInputElement>} type="file" accept=".xlsx,.csv,.pdf,.jpg,.jpeg,.png,.tiff,.rvt,.ifc,.dwg,.dgn" className="hidden" onChange={onImportInputChange} aria-label={t('common.import', { defaultValue: 'Import' })} />
        {onPasteFromExcel && (
          <Button variant="ghost" size="sm" icon={<ClipboardPaste size={15} />} onClick={onPasteFromExcel} title={t('boq.paste_from_excel', { defaultValue: 'Paste from Excel' })}>
            <span className="hidden xl:inline">{t('boq.paste_from_excel', { defaultValue: 'Paste' })}</span>
          </Button>
        )}
        <div ref={exportRef} className="relative">
          <Button variant="ghost" size="sm" icon={<Download size={15} />} onClick={() => setShowExportMenu((prev) => !prev)} aria-expanded={showExportMenu} aria-haspopup="true">
            {t('boq.export')}
          </Button>
          {showExportMenu && (
            <div role="menu" className="absolute left-0 top-full mt-1 z-50 w-44 rounded-lg border border-border-light bg-surface-elevated shadow-md animate-fade-in">
              <button role="menuitem" onClick={() => handleExportItem('excel')} className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors rounded-t-lg">
                <FileSpreadsheet size={15} className="text-content-tertiary" />
                {t('boq.export_format_excel', { defaultValue: 'Excel (.xlsx)' })}
              </button>
              <button role="menuitem" onClick={() => handleExportItem('csv')} className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors">
                <FileText size={15} className="text-content-tertiary" />
                {t('boq.export_format_csv', { defaultValue: 'CSV (.csv)' })}
              </button>
              <button role="menuitem" onClick={() => handleExportItem('pdf')} className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors">
                <FileDown size={15} className="text-content-tertiary" />
                {t('boq.export_format_pdf', { defaultValue: 'PDF' })}
              </button>
              <button role="menuitem" onClick={() => handleExportItem('gaeb')} className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors rounded-b-lg">
                <FileText size={15} className="text-content-tertiary" />
                {t('boq.export_format_gaeb', { defaultValue: 'GAEB XML (.x83)' })}
              </button>
            </div>
          )}
        </div>
        {onManageColumns && (
          <Button
            variant="ghost"
            size="sm"
            icon={<Columns3 size={15} />}
            onClick={onManageColumns}
            title={t('boq.manage_columns', { defaultValue: 'Manage custom columns' })}
          >
            <span className="hidden xl:inline">
              {t('boq.columns', { defaultValue: 'Columns' })}
            </span>
            {customColumnCount != null && customColumnCount > 0 && (
              <span className="ml-1 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-oe-blue/15 px-1 text-2xs font-semibold text-oe-blue tabular-nums">
                {customColumnCount}
              </span>
            )}
          </Button>
        )}
        {onRenumber && (
          <Button
            variant="ghost"
            size="sm"
            icon={<ListOrdered size={15} className={isRenumbering ? 'animate-pulse text-oe-blue' : ''} />}
            onClick={onRenumber}
            disabled={isRenumbering}
            title={t('boq.renumber_tip', {
              defaultValue: 'Renumber all positions using a gap-of-10 scheme (01.10, 01.20, …) so future inserts don\'t require renumbering everything.',
            })}
          >
            <span className="hidden xl:inline">
              {isRenumbering
                ? t('boq.renumbering', { defaultValue: 'Renumbering…' })
                : t('boq.renumber', { defaultValue: 'Renumber' })}
            </span>
          </Button>
        )}
      </div>

      <div className="w-px h-6 bg-border-light hidden sm:block" />

      {/* ── Row-group: Quality & AI ─────────────────────────────────────── */}
      <div className="flex items-center gap-1.5">
        <span className="text-2xs font-medium text-content-quaternary uppercase tracking-wider hidden lg:inline ml-1 mr-1">{t('boq.toolbar_quality', { defaultValue: 'Quality' })}</span>
        {/* Validate: checks data quality, completeness, DIN 276 compliance */}
        <div className="relative group/validate">
          <Button
            variant="ghost"
            size="sm"
            icon={<ShieldCheck size={15} className={isValidating ? 'animate-pulse text-oe-blue' : lastValidationScore != null ? (lastValidationScore >= 80 ? 'text-emerald-500' : lastValidationScore >= 50 ? 'text-amber-500' : 'text-red-500') : ''} />}
            onClick={onValidate}
            disabled={isValidating}
            title={t('boq.validate_info_tooltip', { defaultValue: 'Run 42 automatic quality checks against DIN 276, NRM, MasterFormat, and GAEB standards' })}
          >
            <span className="hidden xl:inline">
              {isValidating
                ? t('boq.validating', { defaultValue: 'Checking...' })
                : t('boq.validate', { defaultValue: 'Validate' })
              }
            </span>
            {lastValidationScore != null && !isValidating && (
              <span className={`ml-1 text-2xs font-bold tabular-nums ${lastValidationScore >= 80 ? 'text-emerald-600' : lastValidationScore >= 50 ? 'text-amber-600' : 'text-red-600'}`}>
                {lastValidationScore}%
              </span>
            )}
          </Button>
          <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-56 rounded-lg bg-gray-900 text-white text-2xs p-2.5 shadow-lg opacity-0 invisible group-hover/validate:opacity-100 group-hover/validate:visible transition-all z-50 pointer-events-none">
            <p className="font-medium mb-1">{t('boq.validate_tip_title', { defaultValue: 'Quality Check' })}</p>
            <p className="text-gray-300">{t('boq.validate_tip', { defaultValue: 'Checks for missing descriptions, zero quantities, pricing gaps, DIN 276 compliance, and duplicate positions.' })}</p>
          </div>
        </div>

        {/* Recalculate: enriches resources from cost DB and recalculates unit rates */}
        <div className="relative group/recalc">
          <Button
            variant="ghost"
            size="sm"
            icon={<RefreshCw size={15} className={isRecalculating ? 'animate-spin text-oe-blue' : ''} />}
            onClick={onRecalculate}
            disabled={isRecalculating}
          >
            <span className="hidden xl:inline">
              {isRecalculating
                ? t('boq.recalculating', { defaultValue: 'Updating...' })
                : t('boq.recalculate_rates', { defaultValue: 'Update Rates' })
              }
            </span>
          </Button>
          <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-56 rounded-lg bg-gray-900 text-white text-2xs p-2.5 shadow-lg opacity-0 invisible group-hover/recalc:opacity-100 group-hover/recalc:visible transition-all z-50 pointer-events-none">
            <p className="font-medium mb-1">{t('boq.recalculate_tip_title', { defaultValue: 'Update Unit Rates' })}</p>
            <p className="text-gray-300">{t('boq.recalculate_tip', { defaultValue: 'Matches positions to cost database, attaches resource breakdowns (materials, labor, equipment), and recalculates unit rates from components.' })}</p>
          </div>
        </div>

        {/* Price Check: compares unit rates against cost database */}
        {onCheckAnomalies && (
          <div className="relative group/anomaly">
            {isCheckingAnomalies ? (
              <div className="flex items-center gap-1">
                <Button variant="ghost" size="sm" icon={<AlertTriangle size={15} className="animate-pulse text-amber-500" />} disabled>
                  <span className="hidden xl:inline text-amber-600">
                    {t('boq.checking_anomalies', { defaultValue: 'Checking...' })}
                  </span>
                </Button>
                {onCancelAnomalies && (
                  <button
                    onClick={onCancelAnomalies}
                    aria-label={t('common.cancel', { defaultValue: 'Cancel' })}
                    className="rounded-md px-1.5 py-1 text-2xs font-medium text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                  >
                    {t('common.cancel', { defaultValue: 'Cancel' })}
                  </button>
                )}
              </div>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                icon={<AlertTriangle size={15} className={anomalyCount ? 'text-amber-500' : ''} />}
                onClick={onCheckAnomalies}
                className={anomalyCount ? 'text-amber-600 dark:text-amber-400' : ''}
              >
                <span className="hidden xl:inline">
                  {anomalyCount
                    ? t('boq.anomalies_badge', { defaultValue: 'Anomalies ({{count}})', count: anomalyCount })
                    : t('boq.price_check', { defaultValue: 'Price Check' })
                  }
                </span>
              </Button>
            )}
            <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-56 rounded-lg bg-gray-900 text-white text-2xs p-2.5 shadow-lg opacity-0 invisible group-hover/anomaly:opacity-100 group-hover/anomaly:visible transition-all z-50 pointer-events-none">
              <p className="font-medium mb-1">{t('boq.anomaly_tip_title', { defaultValue: 'Price Benchmark' })}</p>
              <p className="text-gray-300">{t('boq.anomaly_tip', { defaultValue: 'Compares each unit rate against median market rates from the cost database. Flags overpriced and underpriced positions.' })}</p>
            </div>
          </div>
        )}
        {anomalyCount !== undefined && anomalyCount > 0 && onAcceptAllAnomalies && (
          <Button
            variant="ghost"
            size="sm"
            icon={<Check size={15} className="text-green-500" />}
            onClick={onAcceptAllAnomalies}
            title={t('boq.accept_all_anomaly_suggestions', { defaultValue: 'Accept All Suggested Rates ({{count}})', count: anomalyCount })}
            className="text-green-600 dark:text-green-400"
          >
            <span className="hidden xl:inline">{t('boq.accept_all', { defaultValue: 'Accept All' })}</span>
          </Button>
        )}
        <div className="w-px h-6 bg-border-light hidden sm:block" />

        {/* ── AI Tools (visually grouped) ───────────────────────────────── */}
        <div className="flex items-center gap-1 rounded-xl bg-gradient-to-r from-violet-50 to-blue-50 dark:from-violet-950/30 dark:to-blue-950/30 border border-violet-200/50 dark:border-violet-800/30 px-2 py-1">
          <div className="flex items-center gap-1 mr-1 hidden lg:flex">
            <Sparkles size={12} className="text-violet-500" />
            <span className="text-2xs font-bold text-violet-600 dark:text-violet-400 uppercase tracking-wider">AI</span>
          </div>

          {/* Cost Finder — search cost database */}
          <div className="relative group/cf">
            <Button
              variant={costFinderOpen ? 'primary' : 'ghost'}
              size="sm"
              icon={<SearchCheck size={15} className={costFinderOpen ? '' : 'text-violet-600 dark:text-violet-400'} />}
              onClick={onToggleCostFinder}
            >
              <span className="hidden xl:inline">{t('boq.cost_finder_short', { defaultValue: 'Find Costs' })}</span>
            </Button>
            <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-52 rounded-lg bg-gray-900 text-white text-2xs p-2.5 shadow-lg opacity-0 invisible group-hover/cf:opacity-100 group-hover/cf:visible transition-all z-50 pointer-events-none">
              <p className="font-semibold mb-1">{t('boq.cost_finder_tip_title', { defaultValue: 'Find Costs in Database' })}</p>
              <p className="text-gray-300">{t('boq.cost_finder_tooltip', { defaultValue: 'Search 55,000+ cost items by description. Find materials, labor, and equipment rates from regional databases.' })}</p>
            </div>
          </div>

          {/* AI Chat — generate positions */}
          <div className="relative group/chat">
            <Button
              variant={aiChatOpen ? 'primary' : 'ghost'}
              size="sm"
              icon={<Sparkles size={15} className={aiChatOpen ? '' : 'text-violet-600 dark:text-violet-400'} />}
              onClick={onToggleAiChat}
            >
              <span className="hidden xl:inline">{t('boq.ai_assistant_short', { defaultValue: 'Generate' })}</span>
            </Button>
            <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-52 rounded-lg bg-gray-900 text-white text-2xs p-2.5 shadow-lg opacity-0 invisible group-hover/chat:opacity-100 group-hover/chat:visible transition-all z-50 pointer-events-none">
              <p className="font-semibold mb-1">{t('boq.ai_chat_tip_title', { defaultValue: 'AI Position Generator' })}</p>
              <p className="text-gray-300">{t('boq.ai_assistant_tooltip', { defaultValue: 'Describe what you need in plain text — AI creates BOQ positions with realistic pricing.' })}</p>
            </div>
          </div>

          {/* Smart AI — analysis tools */}
          <div className="relative group/smart">
            <Button
              variant={smartPanelOpen ? 'primary' : 'ghost'}
              size="sm"
              icon={<Brain size={15} className={smartPanelOpen ? '' : 'text-violet-600 dark:text-violet-400'} />}
              onClick={onToggleSmartPanel}
            >
              <span className="hidden xl:inline">{t('boq.ai_smart_short', { defaultValue: 'Analyze' })}</span>
            </Button>
            <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-52 rounded-lg bg-gray-900 text-white text-2xs p-2.5 shadow-lg opacity-0 invisible group-hover/smart:opacity-100 group-hover/smart:visible transition-all z-50 pointer-events-none">
              <p className="font-semibold mb-1">{t('boq.ai_smart_tip_title', { defaultValue: 'AI Analysis & Optimization' })}</p>
              <p className="text-gray-300">{t('boq.ai_smart_tooltip', { defaultValue: 'Enhance descriptions, find missing items, check scope completeness, escalate rates to current prices.' })}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
