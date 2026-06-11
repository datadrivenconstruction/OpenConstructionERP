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
  Variable as VariableIcon,
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
  Leaf,
  WrapText,
} from 'lucide-react';
import { Button } from '@/shared/ui';
import { useBoqDescDensityStore, type BoqDescDensity } from '@/stores/useBoqDescDensityStore';

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
  /**
   * Open the embodied-carbon view for this BOQ. When provided, a "Carbon
   * footprint" action appears in the File group; the host wires it to
   * /sustainability with the active project and BOQ preselected.
   */
  onCarbonFootprint?: () => void;
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
  // Per-BOQ named variables ($GFA, $LABOR_RATE, …)
  onManageVariables?: () => void;
  // Renumber positions (gap-of-10 scheme)
  onRenumber?: () => void;
  isRenumbering?: boolean;
  // Quality
  hasPositions: boolean;
  qualityScoreRing: React.ReactNode;
  // Keyboard shortcuts overlay
  onShowShortcuts?: () => void;
  /**
   * ── Inline mini-summary (merged into toolbar instead of a second row).
   * Renders at the right end with `ml-auto` so on wide screens the toolbar
   * is a single visual band. Falls back to a wrapped row on narrow screens
   * via the toolbar's existing `flex-wrap`. Pass `null` to hide entirely
   * (e.g. on the empty-state of a BOQ with zero positions).
   */
  summary?: {
    sectionCount: number;
    positionCount: number;
    errorCount: number;
    warningCount: number;
    /** Project base currency symbol (e.g. "€"). Used for the Grand Total render. */
    currencySymbol: string;
    /** Project base currency code (e.g. "EUR") — drives the "Display in" default option. */
    currencyCode: string;
    /** FX rate templates configured at project level. Empty array hides the selector. */
    fxRates: { currency: string; rate: number; label?: string }[];
    /** Currently picked display currency (empty string ⇒ base). */
    displayCurrency: string;
    onChangeDisplayCurrency: (code: string) => void;
    /** Live total in base currency. */
    grossTotal: number;
    /** Live total converted to display currency (or base when display === base). */
    grossTotalDisplay: number;
    /** Symbol/code of the active display currency (mirrors `displayCurrency` once resolved). */
    displaySymbol: string;
    /** Resolved FX rate for the display currency, used in the conversion tooltip. */
    displayRate: number | null;
  } | null;
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
  onCarbonFootprint,
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
  onManageVariables,
  onRenumber,
  isRenumbering,
  hasPositions,
  qualityScoreRing,
  onShowShortcuts,
  summary,
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

  /* ── Description density (single line ↔ multi-line Langtext) ───────── */
  const descDensity = useBoqDescDensityStore((s) => s.density);
  const cycleDescDensity = useBoqDescDensityStore((s) => s.cycleDensity);
  const descDensityLabel: Record<BoqDescDensity, string> = {
    compact: t('boq.desc_density_compact', { defaultValue: 'Compact' }),
    comfortable: t('boq.desc_density_comfortable', { defaultValue: 'Comfortable' }),
    tall: t('boq.desc_density_tall', { defaultValue: 'Langtext' }),
  };

  // Bug 7: stick BELOW the app header (52px / --oe-header-height) — using top-0 collides
  // with the sticky header (z-30), pushing the toolbar out of view when scrolling.
  return (
    <div
      data-testid="boq-toolbar"
      className="sticky top-[52px] z-20 bg-surface-primary flex flex-wrap items-center gap-x-1.5 gap-y-2 px-1 py-2 border-b border-border-light mb-3"
    >
      {/* ── Row-group: Quality + Undo/Redo ─────────────────────────────── */}
      <div className="flex items-center gap-1.5" data-testid="boq-quality-ring">
        {hasPositions && qualityScoreRing}
        <Button variant="ghost" size="sm" icon={<Undo2 size={15} />} onClick={onUndo} disabled={!canUndo} title={t('boq.undo', { defaultValue: 'Undo (Ctrl+Z)' })} />
        <Button variant="ghost" size="sm" icon={<Redo2 size={15} />} onClick={onRedo} disabled={!canRedo} title={t('boq.redo', { defaultValue: 'Redo (Ctrl+Y)' })} />
        <Button variant="ghost" size="sm" icon={<Clock size={15} />} onClick={onShowVersionHistory} title={t('boq.version_history', { defaultValue: 'Version History' })} />
      </div>

      <div className="w-px h-6 bg-border-light hidden sm:block" />

      {/* ── Row-group: Add ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-1.5">
        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={15} />}
          onClick={onAddPosition}
          data-testid="boq-add-position-button"
        >
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
          {t('common.import')}
        </Button>
        <input ref={importInputRef as React.RefObject<HTMLInputElement>} type="file" accept=".xlsx,.csv,.pdf,.jpg,.jpeg,.png,.tiff,.rvt,.ifc,.dwg,.dgn,.x81,.x83,.x84,.xml" className="hidden" onChange={onImportInputChange} aria-label={t('common.import')} />
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
        <Button
          variant={descDensity === 'compact' ? 'ghost' : 'secondary'}
          size="sm"
          icon={<WrapText size={15} />}
          onClick={cycleDescDensity}
          title={t('boq.desc_density_tooltip', {
            defaultValue:
              'Description height: switch between a single line and a multi-line Langtext view. Double-click a description to edit the full text.',
          })}
          aria-label={t('boq.desc_density_tooltip', {
            defaultValue: 'Toggle description height',
          })}
          data-testid="boq-desc-density-toggle"
        >
          <span className="hidden xl:inline">{descDensityLabel[descDensity]}</span>
        </Button>
        <div ref={exportRef} className="relative" data-testid="boq-export-button">
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
        {(onManageColumns || onRenumber || onManageVariables) && (
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
                {onManageVariables && (
                  <button
                    role="menuitem"
                    onClick={() => { setGridSettingsOpen(false); onManageVariables(); }}
                    className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors ${!onManageColumns ? 'rounded-t-lg' : ''}`}
                  >
                    <VariableIcon size={15} className="text-content-tertiary" />
                    {t('boq.manage_variables', { defaultValue: 'Manage Variables' })}
                  </button>
                )}
                {onRenumber && (
                  <button
                    role="menuitem"
                    onClick={() => { setGridSettingsOpen(false); onRenumber(); }}
                    disabled={isRenumbering}
                    className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors ${!onManageColumns && !onManageVariables ? 'rounded-t-lg' : ''} rounded-b-lg ${isRenumbering ? 'opacity-40 pointer-events-none' : ''}`}
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
        {onCarbonFootprint && (
          <Button
            variant="ghost"
            size="sm"
            icon={<Leaf size={15} className="text-emerald-600" />}
            onClick={onCarbonFootprint}
            title={t('boq.carbon_footprint_tip', {
              defaultValue: 'Analyse the embodied carbon of this BOQ from EPD material factors',
            })}
            aria-label={t('boq.carbon_footprint', { defaultValue: 'Carbon footprint' })}
          >
            <span className="hidden xl:inline">
              {t('boq.carbon_footprint', { defaultValue: 'Carbon footprint' })}
            </span>
          </Button>
        )}
      </div>

      <div className="w-px h-6 bg-border-light hidden sm:block" />

      {/* ── Quality & AI dropdown — single pill that fans out to the full
          action list (Validate, Update Rates, Price Check, Cost Finder,
          AI Chat, Analyze). Keeps the toolbar in a single row on standard
          1440-1920px laptops. Score badge + recalculating spinner are
          surfaced on the pill itself so users still see status at a glance. */}
      <div className="flex items-center gap-1.5">
        <QualityAiMenu
          t={t}
          onValidate={onValidate}
          isValidating={isValidating}
          lastValidationScore={lastValidationScore}
          onRecalculate={onRecalculate}
          isRecalculating={isRecalculating}
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

      {/* ── Inline mini-summary (right side, merged from the old second row).
          Sits at `ml-auto` so on wide screens the toolbar reads as a single
          horizontal band with action buttons on the left and the live
          Grand-Total / status pills on the right. On narrow screens it
          wraps under the toolbar via the parent `flex-wrap`. Renders only
          when `summary` is provided and the BOQ has at least one row. */}
      {summary && hasPositions && (
        <div
          className="ml-auto flex shrink-0 items-center gap-2 whitespace-nowrap
                     rounded-lg border border-border-light bg-surface-secondary/60
                     px-2.5 py-1 tabular-nums"
          title={
            t('boq.toolbar_summary_aria', {
              defaultValue: '{{sections}} sections · {{positions}} positions',
              sections: summary.sectionCount,
              positions: summary.positionCount,
            })
          }
        >
          {/* Errors / warnings as compact tinted chips — actionable signals
              that stay readable and never wrap mid-phrase. The full
              sections/positions breakdown lives in the container tooltip and
              the BOQ Statistics modal. */}
          {summary.errorCount > 0 && (
            <span className="inline-flex items-center whitespace-nowrap rounded-full
                             bg-red-50 px-2 py-0.5 text-2xs font-semibold
                             text-red-600 dark:bg-red-500/15 dark:text-red-400">
              {summary.errorCount} {t('boq.errors', { defaultValue: 'errors' })}
            </span>
          )}
          {summary.warningCount > 0 && (
            <span className="inline-flex items-center whitespace-nowrap rounded-full
                             bg-amber-50 px-2 py-0.5 text-2xs font-semibold
                             text-amber-600 dark:bg-amber-500/15 dark:text-amber-400">
              {summary.warningCount} {t('boq.warnings', { defaultValue: 'warnings' })}
            </span>
          )}

          {/* Display-in selector — opt-in, hidden when no FX rates configured. */}
          {summary.fxRates.length > 0 && (
            <>
              <span className="w-px h-4 bg-border-light" />
              <span className="inline-flex items-center gap-1 normal-case">
                <span className="hidden lg:inline text-2xs text-content-tertiary">
                  {t('boq.display_in', { defaultValue: 'Display in' })}:
                </span>
                <select
                  value={summary.displayCurrency}
                  onChange={(e) => summary.onChangeDisplayCurrency(e.target.value)}
                  aria-label={t('boq.display_currency_aria', {
                    defaultValue: 'Choose currency for grand total display',
                  })}
                  className="bg-surface-elevated border border-border-light rounded px-1.5 py-0.5
                             text-content-primary text-2xs cursor-pointer
                             focus:outline-none focus:ring-1 focus:ring-oe-blue/40"
                >
                  <option value="">
                    {summary.currencyCode || t('boq.display_base', { defaultValue: 'Base' })}
                  </option>
                  {summary.fxRates.map((fx) => (
                    <option key={fx.currency} value={fx.currency}>
                      {fx.currency}
                    </option>
                  ))}
                </select>
              </span>
            </>
          )}

          {/* Grand Total — the headline figure, clearly separated and never
              wrapped. The tooltip spells out the FX rate so the converted
              figure is auditable. When display ≠ base the entire BOQ renders
              in the chosen currency in lock-step; edits stay locked to base
              (switch back to "Base" to change a unit_rate). */}
          {(summary.errorCount > 0 ||
            summary.warningCount > 0 ||
            summary.fxRates.length > 0) && (
            <span className="w-px h-5 bg-border-light" />
          )}
          <span
            className="flex items-baseline gap-1.5 whitespace-nowrap"
            title={
              summary.displayRate != null && summary.displayCurrency
                ? t('boq.grand_total_conversion_tooltip_v2', {
                    defaultValue:
                      'Whole BOQ rendered in {{disp}} at rate {{rate}} ({{base}} → {{disp}}). View-only - server keeps base values. Switch to "Base" to edit prices.',
                    base: summary.currencyCode || summary.currencySymbol,
                    disp: summary.displayCurrency,
                    rate: summary.displayRate.toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 6,
                    }),
                  })
                : undefined
            }
          >
            <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('boq.grand_total', { defaultValue: 'Grand Total' })}
            </span>
            <span className="text-sm font-bold text-content-primary">
              {summary.displaySymbol}{' '}
              {summary.grossTotalDisplay.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </span>
          </span>
        </div>
      )}
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
  onRecalculate: () => void;
  isRecalculating?: boolean;
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
    onRecalculate,
    isRecalculating,
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
    <div ref={wrapperRef} className="relative" data-testid="boq-quality-ai-menu">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={t('boq.quality_ai_menu_tip', { defaultValue: 'All quality & AI tools' })}
        className={`flex shrink-0 items-center gap-1.5 px-2.5 h-7 whitespace-nowrap rounded-lg border text-2xs font-semibold uppercase tracking-wider transition-colors ${
          open
            ? 'bg-violet-100 dark:bg-violet-900/40 border-violet-300 dark:border-violet-700 text-violet-700 dark:text-violet-200'
            : 'bg-gradient-to-r from-violet-50 to-blue-50 dark:from-violet-950/30 dark:to-blue-950/30 border-violet-200/50 dark:border-violet-800/30 text-violet-700 dark:text-violet-300 hover:from-violet-100 hover:to-blue-100 dark:hover:from-violet-900/40'
        }`}
      >
        {isRecalculating ? (
          <RefreshCw size={13} className="animate-spin text-oe-blue" />
        ) : isValidating ? (
          <ShieldCheck size={13} className="animate-pulse text-oe-blue" />
        ) : (
          <Sparkles size={13} className="text-violet-500" />
        )}
        <span className="hidden lg:inline whitespace-nowrap">{t('boq.quality_ai_menu', { defaultValue: 'Quality & AI' })}</span>
        {lastValidationScore != null && !isValidating && (
          <span className={`text-2xs font-bold tabular-nums ${lastValidationScore >= 80 ? 'text-emerald-600' : lastValidationScore >= 50 ? 'text-amber-600' : 'text-red-600'}`}>
            {lastValidationScore}%
          </span>
        )}
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
            <MenuRow
              icon={<RefreshCw size={14} className={isRecalculating ? 'animate-spin text-oe-blue' : 'text-content-tertiary'} />}
              label={isRecalculating ? t('boq.recalculating', { defaultValue: 'Updating...' }) : t('boq.recalculate_rates', { defaultValue: 'Update Rates' })}
              hint={t('boq.recalculate_tip', { defaultValue: 'Matches positions to cost database, attaches resource breakdowns (materials, labor, equipment), and recalculates unit rates from components.' })}
              onClick={fire(onRecalculate)}
              disabled={isRecalculating}
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
              hint={t('boq.ai_assistant_tooltip', { defaultValue: 'Describe what you need in plain text - AI creates BOQ positions with realistic pricing.' })}
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
