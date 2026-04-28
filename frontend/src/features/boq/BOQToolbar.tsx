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
  Settings,
  ChevronDown,
  Keyboard,
} from 'lucide-react';
import { Button } from '@/shared/ui';

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
  qualityScoreRing: React.ReactNode;
  // Keyboard shortcuts overlay
  onShowShortcuts?: () => void;
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
  onShowShortcuts,
}: BOQToolbarProps) {
  /* ── Export dropdown state ─────────────────────────────────────────── */
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);

  /* ── Grid Settings dropdown state ────────────────────────────────── */
  const [gridSettingsOpen, setGridSettingsOpen] = useState(false);
  const gridSettingsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) {
        setShowExportMenu(false);
      }
      if (gridSettingsRef.current && !gridSettingsRef.current.contains(e.target as Node)) {
        setGridSettingsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleExportItem = (format: 'excel' | 'csv' | 'pdf' | 'gaeb') => {
    setShowExportMenu(false);
    onExport(format);
  };

  // Bug 7: stick BELOW the app header (52px / --oe-header-height) — using top-0 collides
  // with the sticky header (z-30), pushing the toolbar out of view when scrolling.
  return (
    <div className="sticky top-[52px] z-20 bg-surface-primary flex flex-wrap items-center gap-x-1.5 gap-y-2 px-1 py-2 border-b border-border-light mb-3">
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
          title={t('boq.add_from_database')}
        >
          {t('boq.add_from_database')}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          icon={<Layers size={15} />}
          onClick={onOpenAssembly}
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
          <Button
            variant="ghost"
            size="sm"
            icon={<ClipboardPaste size={15} />}
            onClick={onPasteFromExcel}
            title={t('boq.paste_from_excel', { defaultValue: 'Paste from Excel' })}
            aria-label={t('boq.paste_from_excel', { defaultValue: 'Paste from Excel' })}
          >
            <span className="hidden xl:inline">
              {t('boq.paste_from_excel_short', { defaultValue: 'Paste' })}
            </span>
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
        {/* ── Grid Settings dropdown (Columns + Renumber) ─────────────── */}
        {(onManageColumns || onRenumber) && (
          <div ref={gridSettingsRef} className="relative">
            <Button
              variant="ghost"
              size="sm"
              icon={<Settings size={15} />}
              onClick={() => setGridSettingsOpen((prev) => !prev)}
              aria-expanded={gridSettingsOpen}
              aria-haspopup="true"
              title={t('boq.grid_settings', { defaultValue: 'Grid Settings' })}
            >
              <span className="hidden xl:inline">
                {t('boq.grid_settings', { defaultValue: 'Grid Settings' })}
              </span>
              {customColumnCount != null && customColumnCount > 0 && (
                <span className="ml-1 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-surface-tertiary px-1 text-2xs font-semibold text-content-secondary tabular-nums">
                  {customColumnCount}
                </span>
              )}
              <ChevronDown size={12} className={`transition-transform ${gridSettingsOpen ? 'rotate-180' : ''}`} />
            </Button>
            {gridSettingsOpen && (
              <div role="menu" className="absolute left-0 top-full mt-1 z-50 w-64 rounded-lg border border-border-light bg-surface-elevated shadow-md animate-fade-in">
                {onManageColumns && (
                  <button
                    role="menuitem"
                    onClick={() => { setGridSettingsOpen(false); onManageColumns(); }}
                    className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors rounded-t-lg"
                  >
                    <Columns3 size={15} className="text-content-tertiary" />
                    {t('boq.manage_columns', { defaultValue: 'Manage Columns' })}
                    {customColumnCount != null && customColumnCount > 0 && (
                      <span className="ml-auto inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-surface-tertiary px-1 text-2xs font-semibold text-content-secondary tabular-nums">
                        {customColumnCount}
                      </span>
                    )}
                  </button>
                )}
                {onRenumber && (
                  <button
                    role="menuitem"
                    onClick={() => { setGridSettingsOpen(false); onRenumber(); }}
                    disabled={isRenumbering}
                    className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors ${!onManageColumns ? 'rounded-t-lg' : ''} rounded-b-lg ${isRenumbering ? 'opacity-40 pointer-events-none' : ''}`}
                  >
                    <ListOrdered size={15} className={`text-content-tertiary ${isRenumbering ? 'animate-pulse' : ''}`} />
                    {isRenumbering
                      ? t('boq.renumbering', { defaultValue: 'Renumbering...' })
                      : t('boq.renumber', { defaultValue: 'Renumber Positions' })}
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="w-px h-6 bg-border-light hidden sm:block" />

      {/* ── Row-group: hot Quality/AI actions promoted inline ──────────────
          Validate, Update Rates, AI Chat are the three actions used most
          often. Everything else (Price Check, Cost Finder, Smart AI) lives
          in the "Quality & AI" dropdown to the right so the toolbar stays
          tight on narrow screens. */}
      <div className="flex items-center gap-1.5">
        {/* Validate (hot — surfaces score badge inline) */}
        <div className="relative group/validate">
          <Button
            variant="ghost"
            size="sm"
            icon={<ShieldCheck size={15} className={isValidating ? 'animate-pulse text-oe-blue' : lastValidationScore != null ? (lastValidationScore >= 80 ? 'text-emerald-500' : lastValidationScore >= 50 ? 'text-amber-500' : 'text-red-500') : ''} />}
            onClick={onValidate}
            disabled={isValidating}
            title={t('boq.validate_info_tooltip', { defaultValue: 'Run 42 automatic quality checks against the project\'s configured classification and quality rules' })}
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
        </div>

        {/* Update Rates (hot) */}
        <Button
          variant="ghost"
          size="sm"
          icon={<RefreshCw size={15} className={isRecalculating ? 'animate-spin text-oe-blue' : ''} />}
          onClick={onRecalculate}
          disabled={isRecalculating}
          title={t('boq.recalculate_tip', { defaultValue: 'Matches positions to cost database, attaches resource breakdowns (materials, labor, equipment), and recalculates unit rates from components.' })}
        >
          <span className="hidden xl:inline">
            {isRecalculating
              ? t('boq.recalculating', { defaultValue: 'Updating...' })
              : t('boq.recalculate_rates', { defaultValue: 'Update Rates' })
            }
          </span>
        </Button>

        {/* AI Chat (hot — the most-discoverable AI entry point) */}
        <Button
          variant={aiChatOpen ? 'primary' : 'ghost'}
          size="sm"
          icon={<Sparkles size={15} className={aiChatOpen ? '' : 'text-violet-600 dark:text-violet-400'} />}
          onClick={onToggleAiChat}
          title={t('boq.ai_assistant_tooltip', { defaultValue: 'Describe what you need in plain text — AI creates BOQ positions with realistic pricing.' })}
        >
          <span className="hidden xl:inline">{t('boq.ai_chat_short', { defaultValue: 'AI Chat' })}</span>
        </Button>

        {/* "Quality & AI" pill — opens a popover with the full action list. */}
        <QualityAiMenu
          t={t}
          onValidate={onValidate}
          isValidating={isValidating}
          lastValidationScore={lastValidationScore}
          onCheckAnomalies={onCheckAnomalies}
          onCancelAnomalies={onCancelAnomalies}
          isCheckingAnomalies={isCheckingAnomalies}
          anomalyCount={anomalyCount}
          onAcceptAllAnomalies={onAcceptAllAnomalies}
          aiChatOpen={aiChatOpen}
          onToggleAiChat={onToggleAiChat}
          costFinderOpen={costFinderOpen}
          onToggleCostFinder={onToggleCostFinder}
          smartPanelOpen={smartPanelOpen}
          onToggleSmartPanel={onToggleSmartPanel}
        />

        {/* ── Keyboard Shortcuts Button ────────────────────────────────── */}
        {onShowShortcuts && (
          <>
            <div className="w-px h-6 bg-border-light hidden sm:block" />
            <button
              onClick={onShowShortcuts}
              title={t('boq.show_shortcuts', { defaultValue: 'Keyboard Shortcuts (F1)' })}
              className="flex h-7 w-7 items-center justify-center rounded-md text-content-quaternary hover:text-content-secondary hover:bg-surface-secondary transition-colors"
            >
              <Keyboard size={14} />
            </button>
          </>
        )}
      </div>
    </div>
  );
}

/* ── Quality & AI dropdown menu ──────────────────────────────────────────
   Single pill button that opens a panel listing the full set of quality
   and AI actions. The three hottest actions (Validate, Update Rates, AI
   Chat) stay inline in the toolbar; this menu is for the rest plus a
   complete reference of every action available on this BOQ. */

interface QualityAiMenuProps {
  t: (key: string, options?: Record<string, string | number>) => string;
  onValidate: () => void;
  isValidating?: boolean;
  lastValidationScore?: number | null;
  onCheckAnomalies?: () => void;
  onCancelAnomalies?: () => void;
  isCheckingAnomalies?: boolean;
  anomalyCount?: number;
  onAcceptAllAnomalies?: () => void;
  aiChatOpen: boolean;
  onToggleAiChat: () => void;
  costFinderOpen: boolean;
  onToggleCostFinder: () => void;
  smartPanelOpen: boolean;
  onToggleSmartPanel: () => void;
}

function QualityAiMenu(props: QualityAiMenuProps) {
  const {
    t,
    onValidate,
    isValidating,
    lastValidationScore,
    onCheckAnomalies,
    onCancelAnomalies,
    isCheckingAnomalies,
    anomalyCount,
    onAcceptAllAnomalies,
    aiChatOpen,
    onToggleAiChat,
    costFinderOpen,
    onToggleCostFinder,
    smartPanelOpen,
    onToggleSmartPanel,
  } = props;
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  // Run the action and dismiss the menu — toggles like AI Chat keep the
  // panel open in case the user wants a follow-up flip; CTAs (Validate,
  // Update Rates, Price Check) close it because they kick off a single
  // background job that takes over the screen.
  const fire = (cb: () => void, dismiss: boolean = true) => () => {
    cb();
    if (dismiss) setOpen(false);
  };

  return (
    <div ref={wrapperRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={t('boq.quality_ai_menu_tip', { defaultValue: 'All quality & AI tools' })}
        className={`flex items-center gap-1.5 px-2.5 h-7 rounded-lg border text-2xs font-semibold uppercase tracking-wider transition-colors ${
          open
            ? 'bg-violet-100 dark:bg-violet-900/40 border-violet-300 dark:border-violet-700 text-violet-700 dark:text-violet-200'
            : 'bg-gradient-to-r from-violet-50 to-blue-50 dark:from-violet-950/30 dark:to-blue-950/30 border-violet-200/50 dark:border-violet-800/30 text-violet-700 dark:text-violet-300 hover:from-violet-100 hover:to-blue-100 dark:hover:from-violet-900/40'
        }`}
      >
        <Sparkles size={13} className="text-violet-500" />
        <span className="hidden lg:inline">{t('boq.quality_ai_menu', { defaultValue: 'Quality & AI' })}</span>
        <ChevronDown size={11} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          role="menu"
          aria-label={t('boq.quality_ai_menu', { defaultValue: 'Quality & AI' })}
          className="absolute right-0 top-full mt-2 w-72 rounded-xl shadow-2xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-elevated overflow-hidden animate-card-in z-50"
        >
          {/* Quality section */}
          <div className="px-3 pt-2.5 pb-1 border-b border-border-light dark:border-border-dark bg-surface-secondary/30">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-content-quaternary">
              {t('boq.toolbar_quality', { defaultValue: 'Quality' })}
            </span>
          </div>
          <div className="py-1">
            <MenuRow
              icon={<ShieldCheck size={14} className={isValidating ? 'animate-pulse text-oe-blue' : lastValidationScore != null ? (lastValidationScore >= 80 ? 'text-emerald-500' : lastValidationScore >= 50 ? 'text-amber-500' : 'text-red-500') : 'text-content-tertiary'} />}
              label={isValidating ? t('boq.validating', { defaultValue: 'Checking...' }) : t('boq.validate', { defaultValue: 'Validate' })}
              hint={t('boq.validate_tip', { defaultValue: 'Checks for missing descriptions, zero quantities, pricing gaps, classification compliance, and duplicate positions.' })}
              trailing={lastValidationScore != null && !isValidating ? (
                <span className={`text-2xs font-bold tabular-nums ${lastValidationScore >= 80 ? 'text-emerald-600' : lastValidationScore >= 50 ? 'text-amber-600' : 'text-red-600'}`}>
                  {lastValidationScore}%
                </span>
              ) : null}
              onClick={fire(onValidate)}
              disabled={isValidating}
            />
            {onCheckAnomalies && (
              <MenuRow
                icon={<AlertTriangle size={14} className={anomalyCount ? 'text-amber-500' : isCheckingAnomalies ? 'animate-pulse text-amber-500' : 'text-content-tertiary'} />}
                label={isCheckingAnomalies
                  ? t('boq.checking_anomalies', { defaultValue: 'Checking...' })
                  : anomalyCount
                    ? t('boq.anomalies_badge', { defaultValue: 'Anomalies ({{count}})', count: anomalyCount })
                    : t('boq.price_check', { defaultValue: 'Price Check' })}
                hint={t('boq.anomaly_tip', { defaultValue: 'Compares each unit rate against median market rates from the cost database. Flags overpriced and underpriced positions.' })}
                onClick={isCheckingAnomalies && onCancelAnomalies ? fire(onCancelAnomalies) : fire(onCheckAnomalies)}
                trailing={isCheckingAnomalies && onCancelAnomalies ? (
                  <span className="text-2xs font-medium text-red-500">{t('common.cancel', { defaultValue: 'Cancel' })}</span>
                ) : null}
              />
            )}
            {anomalyCount !== undefined && anomalyCount > 0 && onAcceptAllAnomalies && (
              <MenuRow
                icon={<Check size={14} className="text-green-500" />}
                label={t('boq.accept_all_anomaly_suggestions', { defaultValue: 'Accept All Suggested Rates ({{count}})', count: anomalyCount })}
                onClick={fire(onAcceptAllAnomalies)}
              />
            )}
          </div>

          {/* AI section */}
          <div className="px-3 pt-2.5 pb-1 border-b border-t border-border-light dark:border-border-dark bg-gradient-to-r from-violet-50/40 to-blue-50/40 dark:from-violet-950/20 dark:to-blue-950/20">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-violet-700 dark:text-violet-300 inline-flex items-center gap-1">
              <Sparkles size={10} /> AI
            </span>
          </div>
          <div className="py-1">
            <MenuRow
              icon={<SearchCheck size={14} className={costFinderOpen ? 'text-blue-600' : 'text-content-tertiary'} />}
              label={t('boq.cost_finder_short', { defaultValue: 'Find Costs' })}
              hint={t('boq.cost_finder_tooltip', { defaultValue: 'Search 55,000+ cost items by description. Find materials, labor, and equipment rates from regional databases.' })}
              active={costFinderOpen}
              onClick={fire(onToggleCostFinder, false)}
            />
            <MenuRow
              icon={<Sparkles size={14} className={aiChatOpen ? 'text-violet-600' : 'text-content-tertiary'} />}
              label={t('boq.ai_chat_short', { defaultValue: 'AI Chat' })}
              hint={t('boq.ai_assistant_tooltip', { defaultValue: 'Describe what you need in plain text — AI creates BOQ positions with realistic pricing.' })}
              active={aiChatOpen}
              onClick={fire(onToggleAiChat, false)}
            />
            <MenuRow
              icon={<Brain size={14} className={smartPanelOpen ? 'text-fuchsia-600' : 'text-content-tertiary'} />}
              label={t('boq.ai_smart_short', { defaultValue: 'Analyze' })}
              hint={t('boq.ai_smart_tooltip', { defaultValue: 'Enhance descriptions, find missing items, check scope completeness, escalate rates to current prices.' })}
              active={smartPanelOpen}
              onClick={fire(onToggleSmartPanel, false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}

interface MenuRowProps {
  icon: React.ReactNode;
  label: string;
  hint?: string;
  active?: boolean;
  disabled?: boolean;
  trailing?: React.ReactNode;
  onClick: () => void;
}

function MenuRow({ icon, label, hint, active, disabled, trailing, onClick }: MenuRowProps) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      disabled={disabled}
      className={`w-full text-left px-3 py-2 flex items-start gap-2.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
        active
          ? 'bg-violet-50 dark:bg-violet-950/30 hover:bg-violet-100 dark:hover:bg-violet-900/40'
          : 'hover:bg-surface-secondary'
      }`}
    >
      <span className="shrink-0 mt-0.5">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className={`text-xs font-medium ${active ? 'text-violet-700 dark:text-violet-200' : 'text-content-primary'}`}>
            {label}
          </span>
          {trailing}
        </div>
        {hint && (
          <div className="text-[10px] text-content-tertiary leading-snug mt-0.5 line-clamp-2">
            {hint}
          </div>
        )}
      </div>
    </button>
  );
}
