// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BOQToolbar — The toolbar/action bar at the top of the BOQ editor.
 *
 * Rendered as two harmonious cards that share the same shell (rounded-xl,
 * hairline border, soft shadow, white surface) floating on the page's
 * canvas-coloured sticky band:
 *
 *   ┌ Toolbar card (flex-1) ─────────────────────────┐  ┌ Grand Total ─────┐
 *   │ Row 1  quality ring · add actions · Validate ·  │  │ GRAND TOTAL  EUR▾ │
 *   │        AI Chat · Quality & AI ▾                  │  │ € 1,234,567.89    │
 *   │ ───────────────────────────────────────────────│  │ 12 sec · 340 pos  │
 *   │ Row 2  undo/redo · import/export · grid settings│  │ 3 errors          │
 *   └─────────────────────────────────────────────────┘  └───────────────────┘
 *
 * Row 1 carries the "build the BOQ" actions plus the two hottest quality/AI
 * actions surfaced as buttons (Validate, AI Chat); the rest of the quality/AI
 * toolset lives in the compact "Quality & AI" overflow menu. Row 2 carries the
 * utility/view controls. The Grand-Total card is a separate block on the right.
 *
 * The Quality & AI overflow menu and the Export menu render through a portal
 * (document.body) with fixed positioning, so they float above the AG-Grid
 * below instead of being clipped by the sticky toolbar's own stacking context
 * (the band is `sticky z-20`; the grid creates competing stacking contexts).
 */

import React, { useState, useRef, useEffect, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import {
  Plus,
  Download,
  ArrowUpRight,
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
  ChevronDown,
  Keyboard,
  Leaf,
  WrapText,
  PieChart,
  FoldVertical,
  UnfoldVertical,
  ListTree,
  ListCollapse,
} from 'lucide-react';
import { Button } from '@/shared/ui';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { formatCurrency } from '@/shared/lib/money';
import { useBoqDescDensityStore, type BoqDescDensity } from '@/stores/useBoqDescDensityStore';
import { useModuleStore } from '@/stores/useModuleStore';

export interface BOQToolbarProps {
  t: (key: string, options?: Record<string, string | number>) => string;
  /**
   * The BOQ the editor currently has open, and the project it belongs to.
   * Required, not optional: the Export menu hands both to the GAEB Exchange
   * module as a deep link, and a link built from an id the host forgot to
   * pass would land on an empty page. Making them required puts that wiring
   * under the type checker.
   */
  projectId: string;
  boqId: string;
  // Undo / redo
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onShowVersionHistory: () => void;
  /** The bill is locked: the add and import actions, all writes, are not offered. */
  readOnly?: boolean;
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
  onExport: (format: string) => void;
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
  // Resource cost-driver split (Material/Labor/Equipment) display: one button
  // cycles pill -> columns -> off so it can be removed entirely.
  resourceSplitMode?: 'pill' | 'columns' | 'off';
  onCycleResourceSplit?: () => void;
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
  // Expand / collapse every section at once
  onToggleCollapseAll?: () => void;
  allSectionsCollapsed?: boolean;
  /**
   * Show or hide the resource breakdown under every position at once. Showing
   * also expands the sections, because a position inside a collapsed section
   * renders nothing and the button would look broken.
   */
  onToggleAllResources?: () => void;
  resourcesAllExpanded?: boolean;
  /**
   * How many positions carry resources. Zero disables the toggle: on a BOQ
   * priced with flat unit rates there is no breakdown to show, and a live
   * button that does nothing reads as a bug.
   */
  expandableResourceCount?: number;
  /**
   * ── Grand-Total summary, rendered as its own card to the right of the
   * toolbar card. Falls back to wrapping below on narrow screens. Pass `null`
   * to hide entirely (e.g. on the empty-state of a BOQ with zero positions).
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
    /**
     * The BOQ's Grand Total, converted to the display currency (or the base
     * value when display === base).
     *
     * Audit #156: this is the SERVER's ``cost-breakdown.grand_total``, read
     * from the same React Query cache entry the Cost Breakdown panel renders,
     * so the two "Grand Total" figures on this page cannot disagree. It used
     * to be a client-side chain whose VAT came from the first percentage tax
     * markup only, which under-stated any BOQ carrying more than one tax line.
     * Do not repoint this at a locally computed total.
     *
     * ``null`` while the server has not answered yet — the card renders a
     * placeholder, never a client-computed stand-in.
     */
    grandTotalDisplay: number | null;
    /** Symbol/code of the active display currency (mirrors `displayCurrency` once resolved). */
    displaySymbol: string;
    /** Resolved FX rate for the display currency, used in the conversion tooltip. */
    displayRate: number | null;
  } | null;
}

export function BOQToolbar({
  t,
  projectId,
  boqId,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onShowVersionHistory,
  readOnly = false,
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
  resourceSplitMode,
  onCycleResourceSplit,
  customColumnCount,
  onManageVariables,
  onRenumber,
  isRenumbering,
  hasPositions,
  qualityScoreRing,
  onShowShortcuts,
  onToggleCollapseAll,
  allSectionsCollapsed,
  onToggleAllResources,
  resourcesAllExpanded,
  expandableResourceCount,
  summary,
}: BOQToolbarProps) {
  // Routes are registered per enabled module (ModuleRoutes filters on the same
  // flag), so linking to a module the operator switched off would dead-end.
  const gaebExchangeEnabled = useModuleStore((s) => s.isModuleEnabled('gaeb-exchange'));

  /* ── Export dropdown (portaled so it floats above the grid) ────────── */
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportBtnRef = useRef<HTMLButtonElement>(null);
  const exportMenuPos = useAnchoredMenu(showExportMenu, exportBtnRef, 'left');

  // Close the export menu on outside click / Escape (the panel lives in a
  // portal, so an "outside" click must be measured against both the trigger
  // and the portaled panel).
  const exportMenuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!showExportMenu) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        exportBtnRef.current && !exportBtnRef.current.contains(target) &&
        exportMenuRef.current && !exportMenuRef.current.contains(target)
      ) {
        setShowExportMenu(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowExportMenu(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [showExportMenu]);

  const handleExportItem = (format: string) => {
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

  const scoreColor = (s: number) =>
    s >= 80 ? 'text-emerald-600' : s >= 50 ? 'text-amber-600' : 'text-red-600';

  // Bug 7: stick BELOW the app header (52px / --oe-header-height) — using top-0 collides
  // with the sticky header (z-30), pushing the toolbar out of view when scrolling.
  // The band paints the page canvas colour (surface-secondary) so content
  // scrolling beneath it does not bleed through, and the two cards read as
  // distinct blocks floating on it.
  return (
    <div
      data-testid="boq-toolbar"
      className="sticky top-[52px] z-20 mb-3 flex flex-wrap items-stretch gap-3 bg-surface-secondary px-0.5 py-2"
    >
      {/* ══ Block 1: the toolbar card (two rows) ════════════════════════════ */}
      <section
        aria-label={t('boq.toolbar_aria', { defaultValue: 'Estimate toolbar' })}
        className="flex min-w-[300px] flex-1 flex-col gap-2 rounded-xl border border-border-light
                   bg-surface-primary px-3 py-2.5 shadow-sm"
      >
        {/* ── Row 1: the primary "build the BOQ" actions ──────────────────── */}
        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-2">
          {/* Quality ring + Add group */}
          <div className="flex items-center gap-1.5" data-testid="boq-quality-ring">
            {hasPositions && qualityScoreRing}
            {!readOnly && <>
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
              <span className="hidden lg:inline">{t('boq.add_section')}</span>
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Database size={15} />}
              onClick={onOpenCostDb}
              title={t('boq.add_from_database')}
            >
              <span className="hidden lg:inline">{t('boq.add_from_database')}</span>
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Layers size={15} />}
              onClick={onOpenAssembly}
              title={t('boq.from_assembly', { defaultValue: 'From Assembly' })}
            >
              <span className="hidden xl:inline">{t('boq.from_assembly', { defaultValue: 'From Assembly' })}</span>
            </Button>
            </>}
          </div>

          <div className="w-px h-6 bg-border-light hidden sm:block" />

          {/* Hot quality/AI actions surfaced as buttons + overflow menu */}
          <div className="flex items-center gap-1.5">
            <Button
              variant="secondary"
              size="sm"
              icon={
                <ShieldCheck
                  size={15}
                  className={isValidating ? 'animate-pulse text-oe-blue' : undefined}
                />
              }
              onClick={onValidate}
              loading={isValidating}
              disabled={isValidating}
              title={t('boq.validate_tip', {
                defaultValue:
                  'Checks for missing descriptions, zero quantities, pricing gaps, classification compliance, and duplicate positions.',
              })}
              data-testid="boq-validate-button"
            >
              {isValidating ? t('boq.validating', { defaultValue: 'Checking...' }) : t('boq.validate', { defaultValue: 'Validate' })}
              {lastValidationScore != null && !isValidating && (
                <span className={`ml-1 text-2xs font-bold tabular-nums ${scoreColor(lastValidationScore)}`}>
                  {lastValidationScore}%
                </span>
              )}
            </Button>
            <Button
              variant={aiChatOpen ? 'secondary' : 'ghost'}
              size="sm"
              aria-pressed={!!aiChatOpen}
              icon={<Sparkles size={15} className={aiChatOpen ? 'text-violet-600' : 'text-violet-500'} />}
              onClick={onToggleAiChat}
              title={t('boq.ai_assistant_tooltip', {
                defaultValue:
                  'Describe what you need in plain text - AI creates BOQ positions with realistic pricing.',
              })}
              data-testid="boq-ai-chat-button"
            >
              {t('boq.ai_chat_short', { defaultValue: 'AI Chat' })}
            </Button>
            <QualityAiMenu
              t={t}
              onRecalculate={onRecalculate}
              isRecalculating={isRecalculating}
              onCheckAnomalies={onCheckAnomalies}
              onCancelAnomalies={onCancelAnomalies}
              isCheckingAnomalies={isCheckingAnomalies}
              anomalyCount={anomalyCount}
              onAcceptAllAnomalies={onAcceptAllAnomalies}
              costFinderOpen={costFinderOpen}
              onToggleCostFinder={onToggleCostFinder}
              smartPanelOpen={smartPanelOpen}
              onToggleSmartPanel={onToggleSmartPanel}
            />
          </div>
        </div>
        {/* end Row 1 */}

        {/* ── Row 2: utility + view controls, one compact icon line ────────
            All secondary actions collapse to 28px icon buttons (the label moves
            to the tooltip + aria-label) so the row never wraps to a second
            line. The Material/Labor/Equipment column toggle keeps a short label
            because it is the discoverable on/off for those columns. The Export
            menu is portaled (see useAnchoredMenu) so it floats above the grid. */}
        <div
          data-testid="boq-toolbar-row2"
          className="flex flex-wrap items-center gap-1 border-t border-border-light/70 pt-2"
        >
          {/* History */}
          <IconBtn icon={<Undo2 size={15} />} title={t('boq.undo', { defaultValue: 'Undo (Ctrl+Z)' })} onClick={onUndo} disabled={!canUndo} />
          <IconBtn icon={<Redo2 size={15} />} title={t('boq.redo', { defaultValue: 'Redo (Ctrl+Y)' })} onClick={onRedo} disabled={!canRedo} />
          <IconBtn icon={<Clock size={15} />} title={t('boq.version_history', { defaultValue: 'Version History' })} onClick={onShowVersionHistory} />
          {onToggleCollapseAll && (
            <IconBtn
              icon={allSectionsCollapsed ? <UnfoldVertical size={15} /> : <FoldVertical size={15} />}
              title={
                allSectionsCollapsed
                  ? t('boq.expand_all', { defaultValue: 'Expand all sections' })
                  : t('boq.collapse_all', { defaultValue: 'Collapse all sections' })
              }
              onClick={onToggleCollapseAll}
              active={allSectionsCollapsed}
              testId="boq-collapse-all-toggle"
            />
          )}
          {onToggleAllResources && (
            <IconBtn
              icon={resourcesAllExpanded ? <ListCollapse size={15} /> : <ListTree size={15} />}
              title={
                expandableResourceCount === 0
                  ? t('boq.no_resources_to_expand', {
                      defaultValue: 'No position has a resource breakdown to show',
                    })
                  : resourcesAllExpanded
                    ? t('boq.hide_all_resources', {
                        defaultValue: 'Hide the resource breakdown everywhere',
                      })
                    : t('boq.show_all_resources', {
                        defaultValue:
                          'Open every position and show its resources ({{count}} priced)',
                        count: expandableResourceCount ?? 0,
                      })
              }
              onClick={onToggleAllResources}
              active={resourcesAllExpanded}
              disabled={expandableResourceCount === 0}
              testId="boq-expand-all-resources-toggle"
            />
          )}

          <span className="mx-0.5 h-5 w-px shrink-0 bg-border-light" />

          {/* File: import / export / paste / density / carbon */}
          {!readOnly && (
            <IconBtn
              icon={isImporting ? <RefreshCw size={15} className="animate-spin" /> : <Upload size={15} />}
              title={t('common.import')}
              onClick={onImportClick}
              disabled={isImporting}
            />
          )}
          <input ref={importInputRef as React.RefObject<HTMLInputElement>} type="file" accept=".xlsx,.csv,.pdf,.jpg,.jpeg,.png,.tiff,.rvt,.ifc,.dwg,.dgn,.x81,.x83,.x84,.x85,.x86,.xml,.bc3,.ods,.json,.yaml,.yml" className="hidden" onChange={onImportInputChange} aria-label={t('common.import')} />
          <div className="relative">
            <button
              ref={exportBtnRef}
              type="button"
              onClick={() => setShowExportMenu((prev) => !prev)}
              aria-expanded={showExportMenu}
              aria-haspopup="menu"
              title={t('boq.export')}
              aria-label={t('boq.export')}
              className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors ${
                showExportMenu
                  ? 'bg-oe-blue/10 text-oe-blue'
                  : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary'
              }`}
            >
              <Download size={15} />
            </button>
            {showExportMenu && exportMenuPos &&
              createPortal(
                <div
                  ref={exportMenuRef}
                  role="menu"
                  style={{ position: 'fixed', top: exportMenuPos.top, left: exportMenuPos.left, zIndex: 1000 }}
                  className="w-44 rounded-lg border border-border-light bg-surface-elevated shadow-md animate-fade-in"
                  data-portal="boq-export-menu"
                >
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
                  <button role="menuitem" onClick={() => handleExportItem('gaeb')} className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors">
                    <FileText size={15} className="text-content-tertiary" />
                    {t('boq.export_format_gaeb', { defaultValue: 'GAEB XML (.x83)' })}
                  </button>
                  <button role="menuitem" onClick={() => handleExportItem('gaeb_x84')} className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors">
                    <FileText size={15} className="text-content-tertiary" />
                    {t('boq.export_format_gaeb_x84', { defaultValue: 'GAEB XML (.x84) - with prices' })}
                  </button>
                  <button role="menuitem" onClick={() => handleExportItem('bc3')} className={`flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors ${gaebExchangeEnabled ? '' : 'rounded-b-lg'}`}>
                    <FileText size={15} className="text-content-tertiary" />
                    {t('boq.export_format_bc3', { defaultValue: 'FIEBDC-3 (.bc3)' })}
                  </button>
                  {/* The five entries above download a file straight away. This
                      one leaves the editor for the GAEB Exchange module, where
                      the exchange phase (X81 / X83 / X84) is an explicit choice
                      rather than the X83 default above - hence the rule and the
                      leaving-arrow. Issue #439: the module carried `navItems: []`
                      and a comment saying it was reached from /boq, and nothing
                      here reached it. The open project and BOQ ride along so the
                      target page does not ask again for context the user already
                      gave. */}
                  {gaebExchangeEnabled && (
                    <>
                      <div role="separator" className="border-t border-border-light" />
                      <Link
                        role="menuitem"
                        to={`/gaeb-exchange?project_id=${encodeURIComponent(projectId)}&boq_id=${encodeURIComponent(boqId)}&tab=export`}
                        onClick={() => setShowExportMenu(false)}
                        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-sm leading-snug text-content-primary hover:bg-surface-secondary transition-colors rounded-b-lg"
                      >
                        <ArrowUpRight size={15} className="shrink-0 text-content-tertiary" />
                        {t('boq.export_gaeb_exchange', { defaultValue: 'GAEB Exchange (X81 / X83 / X84)' })}
                      </Link>
                    </>
                  )}
                </div>,
                document.body,
              )}
          </div>
          {onPasteFromExcel && (
            <IconBtn
              icon={<ClipboardPaste size={15} />}
              title={t('boq.paste_from_excel', { defaultValue: 'Paste from Excel' })}
              onClick={onPasteFromExcel}
            />
          )}

          <span className="mx-0.5 h-5 w-px shrink-0 bg-border-light" />

          <IconBtn
            icon={<WrapText size={15} />}
            title={`${t('boq.desc_density_tooltip', { defaultValue: 'Description height: switch between a single line and a multi-line Langtext view. Double-click a description to edit the full text.' })} (${descDensityLabel[descDensity]})`}
            onClick={cycleDescDensity}
            active={descDensity !== 'compact'}
            testId="boq-desc-density-toggle"
          />
          {onCarbonFootprint && (
            <IconBtn
              icon={<Leaf size={15} className="text-emerald-600" />}
              title={t('boq.carbon_footprint_tip', { defaultValue: 'Analyse the embodied carbon of this BOQ from EPD material factors' })}
              onClick={onCarbonFootprint}
            />
          )}

          {(onManageColumns || onManageVariables || onRenumber || onCycleResourceSplit) && (
            <span className="mx-0.5 h-5 w-px shrink-0 bg-border-light" />
          )}

          {/* Grid settings */}
          {onManageColumns && (
            <IconBtn
              icon={<Columns3 size={15} />}
              title={t('boq.manage_columns', { defaultValue: 'Manage Columns' })}
              onClick={onManageColumns}
              badge={customColumnCount}
              testId="boq-manage-columns-button"
            />
          )}
          {onManageVariables && (
            <IconBtn
              icon={<VariableIcon size={15} />}
              title={t('boq.manage_variables', { defaultValue: 'Manage Variables' })}
              onClick={onManageVariables}
              testId="boq-manage-variables-button"
            />
          )}
          {onRenumber && (
            <IconBtn
              icon={<ListOrdered size={15} className={isRenumbering ? 'animate-pulse' : ''} />}
              title={t('boq.renumber', { defaultValue: 'Renumber Positions' })}
              onClick={onRenumber}
              disabled={isRenumbering}
              testId="boq-renumber-button"
            />
          )}
          {/* Resource-split control: ONE button cycling three states so an
              estimator who does not need the Material / Labor / Equipment
              breakdown can remove it entirely. pill -> columns -> off -> pill.
              The chosen mode is persisted by BOQEditorPage. */}
          {onCycleResourceSplit && (
            <button
              type="button"
              onClick={onCycleResourceSplit}
              aria-label={t('boq.resource_split_cycle', { defaultValue: 'Resource split display: click to switch between compact, columns and hidden' })}
              title={
                resourceSplitMode === 'columns'
                  ? t('boq.resource_split_tip_columns', { defaultValue: 'Material, Labor and Equipment shown as sortable columns. Click to hide them.' })
                  : resourceSplitMode === 'off'
                    ? t('boq.resource_split_tip_off', { defaultValue: 'Material, Labor and Equipment hidden. Click to show the compact split.' })
                    : t('boq.resource_split_tip_pill', { defaultValue: 'Material, Labor and Equipment shown as a compact inline split. Click to show them as columns.' })
              }
              data-testid="boq-resource-split-toolbar-toggle"
              data-mode={resourceSplitMode ?? 'pill'}
              className={`flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-2xs font-semibold transition-colors ${
                resourceSplitMode === 'columns'
                  ? 'bg-oe-blue/10 text-oe-blue'
                  : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary'
              }`}
            >
              <PieChart size={14} className={resourceSplitMode === 'off' ? 'opacity-40' : undefined} />
              <span className={resourceSplitMode === 'off' ? 'line-through opacity-60' : undefined}>
                {t('boq.resource_split_short', { defaultValue: 'MAT/LAB/EQU' })}
              </span>
              {resourceSplitMode === 'columns' && <Check size={12} />}
            </button>
          )}

          {/* Keyboard shortcuts */}
          {onShowShortcuts && (
            <>
              <span className="mx-0.5 h-5 w-px shrink-0 bg-border-light" />
              <IconBtn
                icon={<Keyboard size={14} />}
                title={t('boq.show_shortcuts', { defaultValue: 'Keyboard Shortcuts (F1)' })}
                onClick={onShowShortcuts}
              />
            </>
          )}
        </div>
        {/* end Row 2 */}
      </section>
      {/* end toolbar card */}

      {/* ══ Block 2: Grand-Total card ═══════════════════════════════════════
          Shares the toolbar card's shell (rounded-xl, border, shadow, white
          surface) so the pair reads as one harmonious set, then differentiates
          itself with the prominent total. `items-stretch` on the band keeps it
          the same height as the toolbar card on wide screens; it wraps below on
          narrow ones. */}
      {summary && hasPositions && (
        <section
          aria-label={t('boq.grand_total', { defaultValue: 'Grand Total' })}
          className="flex min-w-[208px] shrink-0 flex-col justify-center gap-1.5 rounded-xl
                     border border-border-light bg-surface-primary px-4 py-2.5 shadow-sm tabular-nums"
          data-testid="boq-grand-total-card"
        >
          {/* Label + display-currency selector */}
          <div className="flex items-center justify-between gap-3">
            <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('boq.grand_total', { defaultValue: 'Grand Total' })}
            </span>
            {summary.fxRates.length > 0 && (
              <span className="inline-flex items-center gap-1 normal-case">
                <span className="hidden lg:inline text-2xs text-content-quaternary">
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
            )}
          </div>

          {/* The number */}
          <span
            className="text-2xl font-bold leading-none text-content-primary"
            title={
              summary.displayRate != null && summary.displayCurrency
                ? t('boq.grand_total_conversion_tooltip_v2', {
                    defaultValue:
                      'Whole BOQ rendered in {{disp}} at rate {{rate}} ({{base}} → {{disp}}). View-only - server keeps base values. Switch to "Base" to edit prices.',
                    base: summary.currencyCode || summary.currencySymbol,
                    disp: summary.displayCurrency,
                    rate: summary.displayRate.toLocaleString(getNumberLocale(), {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 6,
                    }),
                  })
                : undefined
            }
          >
            {summary.grandTotalDisplay == null ? (
              // Server total not in yet. A dash says "not known", which is the
              // truth; printing a client-side approximation under the same
              // label is what audit #156 removed.
              <span className="text-content-tertiary">—</span>
            ) : (() => {
              // Locale-aware money: the grid rows already format as
              // "133.000,00 €" under de-DE, so the headline total must not
              // fall back to the browser default ("€ 12,550,880.81").
              const code = summary.displayCurrency || summary.currencyCode;
              if (/^[A-Z]{3}$/.test(code)) {
                return <>{formatCurrency(summary.grandTotalDisplay, code)}</>;
              }
              return (
                <>
                  {summary.displaySymbol}{' '}
                  {summary.grandTotalDisplay.toLocaleString(getNumberLocale(), {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </>
              );
            })()}
          </span>

          {/* Meta line: counts + quality status badges */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-2xs text-content-tertiary">
              {t('boq.toolbar_summary_aria', {
                defaultValue: '{{sections}} sections · {{positions}} positions',
                sections: summary.sectionCount,
                positions: summary.positionCount,
              })}
            </span>
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
          </div>
        </section>
      )}
      {/* end Grand-Total card */}
    </div>
  );
}

/* ── Anchored-menu positioning hook ──────────────────────────────────────
   Computes fixed-viewport coordinates for a portaled dropdown anchored under
   a trigger button. Recomputes on open and on resize/scroll so the menu keeps
   tracking the (sticky) toolbar button. Returns null while closed. */
function useAnchoredMenu(
  open: boolean,
  triggerRef: React.RefObject<HTMLElement | null>,
  align: 'left' | 'right',
): { top: number; left?: number; right?: number } | null {
  const [pos, setPos] = useState<{ top: number; left?: number; right?: number } | null>(null);

  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const compute = () => {
      const el = triggerRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      if (align === 'right') {
        setPos({ top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) });
      } else {
        setPos({ top: r.bottom + 6, left: Math.max(8, r.left) });
      }
    };
    compute();
    window.addEventListener('resize', compute);
    window.addEventListener('scroll', compute, true);
    return () => {
      window.removeEventListener('resize', compute);
      window.removeEventListener('scroll', compute, true);
    };
  }, [open, triggerRef, align]);

  return pos;
}

/* ── Quality & AI overflow menu ──────────────────────────────────────────
   Compact pill that fans out to the quality/AI actions that are not surfaced
   directly on the toolbar (Update Rates, Price Check, Find Costs, Analyze).
   The panel renders through a portal with fixed positioning so it floats
   above the AG-Grid instead of being clipped by the sticky toolbar's
   stacking context (the previous `absolute` panel rendered *under* the grid). */

interface QualityAiMenuProps {
  t: (key: string, options?: Record<string, string | number>) => string;
  onRecalculate: () => void;
  isRecalculating?: boolean;
  onCheckAnomalies?: () => void;
  onCancelAnomalies?: () => void;
  isCheckingAnomalies?: boolean;
  anomalyCount?: number;
  onAcceptAllAnomalies?: () => void;
  costFinderOpen: boolean;
  onToggleCostFinder: () => void;
  smartPanelOpen: boolean;
  onToggleSmartPanel: () => void;
}

function QualityAiMenu(props: QualityAiMenuProps) {
  const {
    t,
    onRecalculate,
    isRecalculating,
    onCheckAnomalies,
    onCancelAnomalies,
    isCheckingAnomalies,
    anomalyCount,
    onAcceptAllAnomalies,
    costFinderOpen,
    onToggleCostFinder,
    smartPanelOpen,
    onToggleSmartPanel,
  } = props;
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const pos = useAnchoredMenu(open, triggerRef, 'right');

  // Close on outside click (checking BOTH the trigger and the portaled menu,
  // since the menu lives outside the trigger's DOM subtree) and on Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        triggerRef.current && !triggerRef.current.contains(target) &&
        menuRef.current && !menuRef.current.contains(target)
      ) {
        setOpen(false);
      }
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

  // Run the action and dismiss the menu — toggles (Find Costs, Analyze) keep
  // the panel open in case the user wants a follow-up flip; CTAs (Update
  // Rates, Price Check) close it because they kick off a job that takes over
  // the screen.
  const fire = (cb: () => void, dismiss: boolean = true) => () => {
    cb();
    if (dismiss) setOpen(false);
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={t('boq.quality_ai_menu_tip', { defaultValue: 'More quality & AI tools' })}
        className={`flex shrink-0 items-center gap-1.5 px-2.5 h-7 whitespace-nowrap rounded-lg border text-2xs font-semibold uppercase tracking-wider transition-colors ${
          open
            ? 'bg-violet-100 dark:bg-violet-900/40 border-violet-300 dark:border-violet-700 text-violet-700 dark:text-violet-200'
            : 'bg-gradient-to-r from-violet-50 to-blue-50 dark:from-violet-950/30 dark:to-blue-950/30 border-violet-200/50 dark:border-violet-800/30 text-violet-700 dark:text-violet-300 hover:from-violet-100 hover:to-blue-100 dark:hover:from-violet-900/40'
        }`}
        data-testid="boq-quality-ai-menu"
      >
        {isRecalculating ? (
          <RefreshCw size={13} className="animate-spin text-oe-blue" />
        ) : (
          <Sparkles size={13} className="text-violet-500" />
        )}
        <span className="hidden lg:inline whitespace-nowrap">{t('boq.quality_ai_menu', { defaultValue: 'Quality & AI' })}</span>
        <ChevronDown size={11} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && pos &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            aria-label={t('boq.quality_ai_menu', { defaultValue: 'Quality & AI' })}
            style={{ position: 'fixed', top: pos.top, right: pos.right, zIndex: 1000 }}
            className="w-72 rounded-xl shadow-2xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-elevated overflow-hidden animate-card-in"
          >
            {/* Quality section */}
            <div className="px-3 pt-2.5 pb-1 border-b border-border-light dark:border-border-dark bg-surface-secondary/30">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-content-quaternary">
                {t('boq.toolbar_quality', { defaultValue: 'Quality' })}
              </span>
            </div>
            <div className="py-1">
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
                  onClick={isCheckingAnomalies && onCancelAnomalies ? fire(onCancelAnomalies) : fire(onCheckAnomalies ?? (() => {}))}
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
                icon={<Brain size={14} className={smartPanelOpen ? 'text-fuchsia-600' : 'text-content-tertiary'} />}
                label={t('boq.ai_smart_short', { defaultValue: 'Analyze' })}
                hint={t('boq.ai_smart_tooltip', { defaultValue: 'Enhance descriptions, find missing items, check scope completeness, escalate rates to current prices.' })}
                active={smartPanelOpen}
                onClick={fire(onToggleSmartPanel, false)}
              />
            </div>
          </div>,
          document.body,
        )}
    </>
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

/* ── Compact icon-only toolbar button ────────────────────────────────────
   Used across Row 2 so the utility actions fit on a single line. The label
   moves entirely to the tooltip + aria-label; an optional count badge sits on
   the top-right corner (e.g. the number of custom columns). */
function IconBtn({
  icon,
  title,
  onClick,
  disabled,
  active,
  badge,
  testId,
}: {
  icon: React.ReactNode;
  title: string;
  onClick?: () => void;
  disabled?: boolean;
  active?: boolean;
  badge?: number | null;
  testId?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      aria-pressed={active}
      data-testid={testId}
      className={`relative flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors ${
        disabled
          ? 'text-content-quaternary opacity-40 pointer-events-none'
          : active
            ? 'bg-oe-blue/10 text-oe-blue hover:bg-oe-blue/15'
            : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary'
      }`}
    >
      {icon}
      {badge != null && badge > 0 && (
        <span className="absolute -right-1 -top-1 inline-flex h-3.5 min-w-[14px] items-center justify-center rounded-full bg-oe-blue px-0.5 text-[9px] font-bold leading-none text-white tabular-nums">
          {badge > 99 ? '99+' : badge}
        </span>
      )}
    </button>
  );
}
