// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  FileText,
  Upload,
  Download,
  FileUp,
  FileDown,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Eye,
  X,
} from 'lucide-react';
import { Button, Badge, DismissibleInfo } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { apiGet, getAuthToken, triggerDownload } from '@/shared/lib/api';
import { fmtNumber, fmtFixed } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { boqApi, isSection as isSectionRow } from '@/features/boq/api';
import {
  parseGAEBXML,
  parseGAEBProjectName,
  detectGAEBPhase,
  importGAEBToBOQ,
  truncateFinding,
  decodeXmlBuffer,
  type GAEBPosition,
} from '@/features/boq/gaebImport';
import {
  generateGAEBXML,
  downloadGAEBXML,
  priceCoverage,
  type GAEBExportFormat,
  type ExportPosition,
} from './data/gaebExport';

/**
 * All formats selectable on the Export tab. X81/X83 are generated
 * client-side; X84 (Angebotsabgabe) is produced by the backend exporter,
 * which writes an XSD-valid bid submission (?format=x84).
 */
type ExportFormatChoice = GAEBExportFormat | 'X84';

/** Sentinel option value: create a new BOQ named after the imported file. */
const NEW_BOQ_OPTION = '__new__';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Project {
  id: string;
  name: string;
}
interface BOQ {
  id: string;
  name: string;
  project_id: string;
}
interface BOQPosition {
  id: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total?: number;
  parent_id?: string | null;
  is_section?: boolean;
  section?: string;
}

// ---------------------------------------------------------------------------
// Import Preview Table
// ---------------------------------------------------------------------------

function ImportPreview({
  positions,
  t,
}: {
  positions: GAEBPosition[];
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const [showAll, setShowAll] = useState(false);
  const displayed = showAll ? positions : positions.slice(0, 20);

  return (
    <div className="border border-border-light rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-surface-tertiary/50 flex items-center justify-between">
        <span className="text-xs font-medium text-content-secondary">
          {t('gaeb.preview', { defaultValue: 'Preview' })}: {positions.length} {t('gaeb.positions', { defaultValue: 'positions' })}
        </span>
        {positions.length > 20 && (
          <button
            onClick={() => setShowAll((v) => !v)}
            className="text-2xs text-oe-blue hover:underline"
          >
            {showAll ? t('gaeb.show_less', { defaultValue: 'Show less' }) : t('gaeb.show_all', { count: positions.length, defaultValue: 'Show all {{count}}' })}
          </button>
        )}
      </div>
      <div className="overflow-x-auto max-h-80">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-surface-secondary/50 sticky top-0">
              <th className="px-3 py-1.5 text-left font-medium text-content-secondary w-24">{t('boq.ordinal', { defaultValue: 'Ordinal' })}</th>
              <th className="px-3 py-1.5 text-left font-medium text-content-secondary">{t('boq.description', { defaultValue: 'Description' })}</th>
              <th className="px-3 py-1.5 text-center font-medium text-content-secondary w-16">{t('boq.unit', { defaultValue: 'Unit' })}</th>
              <th className="px-3 py-1.5 text-right font-medium text-content-secondary w-20">{t('boq.quantity', { defaultValue: 'Qty' })}</th>
              <th className="px-3 py-1.5 text-right font-medium text-content-secondary w-20">{t('boq.unit_rate', { defaultValue: 'Rate' })}</th>
              <th className="px-3 py-1.5 text-left font-medium text-content-secondary w-32">{t('boq.section', { defaultValue: 'Section' })}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {/* GAEB is an interchange format: quantities/units stay metric-
                canonical here (no measurement-system conversion). (#270) */}
            {displayed.map((pos, idx) => (
              <tr key={pos.ordinal || `pos-${idx}`} className={`hover:bg-surface-secondary/30 ${idx % 2 === 0 ? 'bg-surface-primary/50' : ''}`}>
                <td className="px-3 py-1.5 font-mono text-content-tertiary">{pos.ordinal}</td>
                <td className="px-3 py-1.5 text-content-primary max-w-[300px] truncate" title={pos.description}>
                  {pos.description || '-'}
                </td>
                <td className="px-3 py-1.5 text-center text-content-secondary">{pos.unit || '-'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{pos.quantity > 0 ? fmtNumber(pos.quantity, 3) : '-'}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{pos.unitRate > 0 ? fmtNumber(pos.unitRate, 2) : '-'}</td>
                <td className="px-3 py-1.5 text-content-tertiary text-2xs truncate" title={pos.section}>{pos.section || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Module Component
// ---------------------------------------------------------------------------

export default function GAEBExchangeModule() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  // The globally active project (header selector) pre-fills both target
  // pickers: a Kalkulator importing an Ausschreibung is almost always
  // working inside the project already open in the header.
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // Deep link from the BOQ workflow (Issue #439). The BOQ editor's Export
  // menu and the BOQ overview both hand over the context the user already
  // has, using the same ?project_id=&boq_id= spelling the Carbon-footprint
  // hand-off to /sustainability uses. `tab` decides which side of the
  // exchange opens first: an estimator arriving from an open BOQ wants
  // Export, one arriving from the overview wants Import.
  const [searchParams] = useSearchParams();
  const linkedProjectId = searchParams.get('project_id');
  const linkedBoqId = searchParams.get('boq_id');
  const linkedTab = searchParams.get('tab');

  // --- Import state ---
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  // The drop target had no dragover state: dragging a file over it changed
  // nothing on screen, so the only feedback that a drop would work was the
  // drop itself landing.
  const [isDropTarget, setIsDropTarget] = useState(false);
  const [parsedPositions, setParsedPositions] = useState<GAEBPosition[] | null>(null);
  const [gaebProjectName, setGaebProjectName] = useState('');
  // Exchange phase (X81/X83/X84…) read from the file's own DP element, not
  // guessed from price presence - an unpriced X83 is NOT an X81.
  const [gaebPhase, setGaebPhase] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);
  const [importTargetBoqId, setImportTargetBoqId] = useState('');
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; errors: string[] } | null>(null);

  // --- Export state ---
  const [exportProjectId, setExportProjectId] = useState(() => linkedProjectId ?? '');
  const [exportBoqId, setExportBoqId] = useState(() => linkedBoqId ?? '');
  const [exportFormat, setExportFormat] = useState<ExportFormatChoice>('X83');
  const [isExporting, setIsExporting] = useState(false);
  const [showExportPreview, setShowExportPreview] = useState(false);

  // Tab state
  const [activeTab, setActiveTab] = useState<'import' | 'export'>(
    () => (linkedTab === 'export' ? 'export' : 'import'),
  );

  // --- Shared queries ---
  const { data: projects = [], isSuccess: projectsLoaded } = useQuery<Project[]>({
    queryKey: ['projects-list'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  // Import: project selection for target BOQ. A deep link wins over the
  // header context, which in turn wins over nothing at all.
  const [importProjectId, setImportProjectId] = useState(() => linkedProjectId ?? activeProjectId ?? '');
  const { data: importBoqs = [] } = useQuery<BOQ[]>({
    queryKey: ['boqs-for-import', importProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${importProjectId}`),
    enabled: !!importProjectId,
  });

  // Export: BOQs for selected project
  const { data: exportBoqs = [], isSuccess: exportBoqsLoaded } = useQuery<BOQ[]>({
    queryKey: ['boqs-for-export', exportProjectId],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${exportProjectId}`),
    enabled: !!exportProjectId,
  });

  // Export: positions for selected BOQ (via BOQ detail endpoint)
  const { data: exportPositions = [] } = useQuery<BOQPosition[]>({
    queryKey: ['boq-positions-export', exportBoqId],
    queryFn: async () => {
      const boq = await apiGet<{ positions?: BOQPosition[] }>(`/v1/boq/boqs/${exportBoqId}`);
      return boq.positions ?? [];
    },
    enabled: !!exportBoqId,
  });

  // A deep link can name a project or a BOQ that no longer resolves: the BOQ
  // was deleted, or the link was pasted across tenants. Drop the id once the
  // list it should have been in has actually arrived, so the page falls back
  // to its own empty state instead of holding a select on a row that is not
  // there. Gating on the query's own success matters: an id cleared before
  // the list loads would look identical, and would throw away good context.
  useEffect(() => {
    if (!projectsLoaded || !exportProjectId) return;
    if (!projects.some((p) => p.id === exportProjectId)) {
      setExportProjectId('');
      setExportBoqId('');
    }
  }, [projectsLoaded, projects, exportProjectId]);

  useEffect(() => {
    if (!projectsLoaded || !importProjectId) return;
    if (!projects.some((p) => p.id === importProjectId)) setImportProjectId('');
  }, [projectsLoaded, projects, importProjectId]);

  useEffect(() => {
    if (!exportBoqsLoaded || !exportBoqId) return;
    if (!exportBoqs.some((b) => b.id === exportBoqId)) setExportBoqId('');
  }, [exportBoqsLoaded, exportBoqs, exportBoqId]);

  // ---------------------------------------------------------------------------
  // Import handlers
  // ---------------------------------------------------------------------------

  const handleFileSelect = useCallback(
    async (file: File) => {
      setImportFile(file);
      setParsedPositions(null);
      setGaebProjectName('');
      setGaebPhase('');
      setParseError(null);
      setImportResult(null);

      try {
        // Read raw bytes so the prolog-declared encoding (e.g. ISO-8859-1)
        // can be honoured. file.text() always decodes as UTF-8 and corrupts
        // umlauts in legacy DACH GAEB exports.
        const buffer = await file.arrayBuffer();
        const xmlString = decodeXmlBuffer(buffer);
        const positions = parseGAEBXML(xmlString);
        setGaebProjectName(parseGAEBProjectName(xmlString));
        setGaebPhase(detectGAEBPhase(xmlString));

        if (positions.length === 0) {
          setParseError(t('gaeb.parse_error', { defaultValue: 'No positions found in the GAEB XML file. Ensure the file is valid GAEB DA XML 3.3 (X81, X83 or X84).' }));
        } else {
          setParsedPositions(positions);
          addToast({
            type: 'success',
            title: t('gaeb.parsed_ok', { defaultValue: 'File parsed successfully' }),
            message: t('gaeb.toast_positions_found', {
              count: positions.length,
              defaultValue: '{{count}} positions found',
            }),
          });
        }
      } catch {
        setParseError(t('gaeb.parse_error_generic', { defaultValue: 'Failed to parse the GAEB XML file.' }));
      }
    },
    [addToast, t],
  );

  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFileSelect(file);
      e.target.value = '';
    },
    [handleFileSelect],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDropTarget(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFileSelect(file);
    },
    [handleFileSelect],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDropTarget(true);
  }, []);

  // dragleave fires for every child the pointer crosses on its way across the
  // zone, so the flag is only cleared once the pointer has left the zone's own
  // box. Clearing on any dragleave makes the highlight flicker.
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    setIsDropTarget(false);
  }, []);

  const handleImport = useCallback(async () => {
    if (!importFile || !importTargetBoqId || !importProjectId) return;
    setIsImporting(true);
    try {
      let targetBoqId = importTargetBoqId;
      if (importTargetBoqId === NEW_BOQ_OPTION) {
        // Create a fresh BOQ named after the tender (PrjInfo/NamePrj),
        // falling back to the file name. An incoming Ausschreibung belongs
        // in its own LV, not appended to an existing estimate.
        const boqName = gaebProjectName || importFile.name.replace(/\.[^.]+$/, '');
        const newBoq = await boqApi.create({ project_id: importProjectId, name: boqName });
        targetBoqId = newBoq.id;
        setImportTargetBoqId(newBoq.id);
        queryClient.invalidateQueries({ queryKey: ['boqs-for-import', importProjectId] });
      }
      const result = await importGAEBToBOQ(importFile, targetBoqId);
      setImportResult(result);
      queryClient.invalidateQueries({ queryKey: ['boq-positions'] });
      addToast({
        type: result.imported > 0 ? 'success' : 'warning',
        title: t('gaeb.import_complete', { defaultValue: 'GAEB import complete' }),
        message:
          result.errors.length > 0
            ? t('gaeb.toast_imported_with_errors', {
                count: result.imported,
                errors: result.errors.length,
                defaultValue: '{{count}} positions imported, {{errors}} rejected',
              })
            : t('gaeb.toast_positions_imported', {
                count: result.imported,
                defaultValue: '{{count}} positions imported',
              }),
      });
    } catch (err) {
      addToast({
        type: 'error',
        title: t('gaeb.import_failed', { defaultValue: 'GAEB import failed' }),
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setIsImporting(false);
    }
  }, [importFile, importTargetBoqId, importProjectId, gaebProjectName, queryClient, addToast, t]);

  const handleClearImport = useCallback(() => {
    setImportFile(null);
    setParsedPositions(null);
    setGaebProjectName('');
    setGaebPhase('');
    setParseError(null);
    setImportResult(null);
  }, []);

  // Generate a tiny, valid sample GAEB X83 so a first-time user can see
  // exactly what a well-formed file looks like (and verify the importer
  // round-trips) without having to source one from their AVA software.
  const handleDownloadSample = useCallback(() => {
    const result = generateGAEBXML({
      format: 'X83',
      projectName: 'Sample Project',
      boqName: 'Sample BOQ',
      positions: [
        { id: 's0', ordinal: '01', description: 'Substructure', unit: '', quantity: 0, unitRate: 0, total: 0, isSection: true },
        { id: 's1', ordinal: '01.01.001', description: 'Reinforced concrete C30/37, foundation slab', unit: 'm3', quantity: 125, unitRate: 142.5, total: 17812.5, section: 'Substructure' },
        { id: 's2', ordinal: '01.01.002', description: 'Formwork to slab edges', unit: 'm2', quantity: 48, unitRate: 38, total: 1824, section: 'Substructure' },
      ],
    });
    downloadGAEBXML(result);
  }, []);

  // ---------------------------------------------------------------------------
  // Export handlers
  // ---------------------------------------------------------------------------

  const exportablePositions: ExportPosition[] = useMemo(
    () =>
      exportPositions.map((p) => ({
        id: p.id,
        ordinal: p.ordinal,
        description: p.description,
        unit: p.unit,
        // Money/quantity arrive as Decimal strings on the wire; coerce so
        // export (.toFixed) and totals never crash on a real BOQ import.
        quantity: Number(p.quantity) || 0,
        unitRate: Number(p.unit_rate) || 0,
        total:
          p.total != null
            ? Number(p.total) || 0
            : (Number(p.quantity) || 0) * (Number(p.unit_rate) || 0),
        section: p.section,
        parentId: p.parent_id,
        // The positions endpoint serves no `is_section` flag — deriving it
        // here from the shared unit rule is what makes the summary's section
        // count and the X81/X83 hierarchy export see the BOQ's sections at
        // all (an explicit server flag, if one ever appears, still wins).
        isSection: p.is_section ?? isSectionRow(p),
      })),
    [exportPositions],
  );

  const selectedExportBoq = exportBoqs.find((b) => b.id === exportBoqId);
  const selectedExportProject = projects.find((p) => p.id === exportProjectId);

  // What the summary's "Prices" tile is allowed to claim. Read from the rates
  // in the bill, then overridden to "none" for X81, which drops prices by
  // definition - the file the user is about to download really carries none.
  const coverage = useMemo(() => priceCoverage(exportablePositions), [exportablePositions]);
  const priceState = exportFormat === 'X81' ? 'none' : coverage.state;

  const handleExport = useCallback(async () => {
    if (exportablePositions.length === 0) {
      addToast({ type: 'warning', title: t('gaeb.no_positions', { defaultValue: 'No positions to export' }) });
      return;
    }
    setIsExporting(true);
    try {
      if (exportFormat === 'X84') {
        // X84 (Angebotsabgabe) comes from the backend exporter: it writes an
        // XSD-valid bid submission with Bieter address, UP/IT and Totals.
        // The server defaults ?format=x84 to a Hauptangebot.
        const token = getAuthToken();
        const r = await fetch(`/api/v1/boq/boqs/${exportBoqId}/export/gaeb/?format=x84`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!r.ok) {
          throw new Error(`Export request failed (${r.status})`);
        }
        const blob = await r.blob();
        const disposition = r.headers.get('content-disposition') ?? '';
        const serverName = disposition.match(/filename="?([^";]+)"?/i)?.[1];
        const fallback = `${(selectedExportBoq?.name ?? 'boq').replace(/[^\w-]+/g, '_')}.X84`;
        const filename = serverName || fallback;
        triggerDownload(blob, filename);
        addToast({
          type: 'success',
          title: t('gaeb.export_complete', { defaultValue: 'GAEB export complete' }),
          message: t('gaeb.toast_exported_to_file', {
            count: exportablePositions.filter((p) => !p.isSection).length,
            file: filename,
            defaultValue: '{{count}} positions → {{file}}',
          }),
        });
      } else {
        const result = generateGAEBXML({
          format: exportFormat,
          projectName: selectedExportProject?.name ?? 'Project',
          boqName: selectedExportBoq?.name ?? 'BOQ',
          positions: exportablePositions,
        });
        downloadGAEBXML(result);
        addToast({
          type: 'success',
          title: t('gaeb.export_complete', { defaultValue: 'GAEB export complete' }),
          message: t('gaeb.toast_exported_with_sections', {
            count: result.positionCount,
            sections: result.sectionCount,
            file: result.filename,
            defaultValue: '{{count}} positions, {{sections}} sections → {{file}}',
          }),
        });
      }
    } catch (err) {
      addToast({
        type: 'error',
        title: t('gaeb.export_failed', { defaultValue: 'GAEB export failed' }),
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setIsExporting(false);
    }
  }, [exportablePositions, exportFormat, exportBoqId, selectedExportProject, selectedExportBoq, addToast, t]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('gaeb.title', { defaultValue: 'GAEB XML 3.3 Import / Export' })}
        subtitle={t('gaeb.subtitle', {
          defaultValue: 'Exchange BOQ data in GAEB DA XML format (X81 / X83 / X84)',
        })}
      />

      <DismissibleInfo
        storageKey="gaeb-exchange"
        title={t('gaeb.intro_title', {
          defaultValue: 'Trade tender data the DACH way',
        })}
        links={[
          {
            label: t('nav.boq', { defaultValue: 'Bill of Quantities' }),
            onClick: () => navigate('/boq'),
          },
          {
            label: t('nav.validation', { defaultValue: 'Validation' }),
            onClick: () => navigate('/validation'),
          },
          {
            label: t('nav.tendering', { defaultValue: 'Tendering' }),
            onClick: () => navigate('/tendering'),
          },
        ]}
      >
        {t('gaeb.intro_body', {
          defaultValue:
            'Import a GAEB DA XML file (X81 tender specification, X83 invitation to tender or X84 priced bid) straight into a BOQ, or export your BOQ back out in the same family of exchange phases. Imports run through validation on the way in, so your Leistungsverzeichnis arrives structured and checked.',
        })}
      </DismissibleInfo>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        <button
          data-testid="gaeb-tab-import"
          onClick={() => setActiveTab('import')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'import'
              ? 'border-oe-blue text-oe-blue'
              : 'border-transparent text-content-tertiary hover:text-content-secondary'
          }`}
        >
          <Upload size={15} />
          {t('gaeb.tab_import', { defaultValue: 'Import' })}
        </button>
        <button
          data-testid="gaeb-tab-export"
          onClick={() => setActiveTab('export')}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'export'
              ? 'border-oe-blue text-oe-blue'
              : 'border-transparent text-content-tertiary hover:text-content-secondary'
          }`}
        >
          <Download size={15} />
          {t('gaeb.tab_export', { defaultValue: 'Export' })}
        </button>
      </div>

      {/* ── Import Tab ───────────────────────────────────────────────── */}
      {activeTab === 'import' && (
        <div className="space-y-5">
          {/* File upload area */}
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
              isDropTarget
                ? 'border-oe-blue bg-oe-blue/10'
                : importFile
                  ? 'border-oe-blue/50 bg-oe-blue/5'
                  : 'border-border hover:border-oe-blue/30 hover:bg-surface-secondary/30'
            }`}
          >
            {importFile ? (
              <div className="space-y-3">
                <div className="flex items-center justify-center gap-2 text-sm text-content-primary">
                  <FileUp size={18} className="text-oe-blue" />
                  <span className="font-medium">{importFile.name}</span>
                  <span className="text-content-tertiary">
                    ({fmtFixed(importFile.size / 1024, 1)} KB)
                  </span>
                  <button
                    onClick={handleClearImport}
                    aria-label={t('gaeb.clear_file', { defaultValue: 'Clear file' })}
                    className="ml-2 p-1 rounded hover:bg-surface-secondary"
                  >
                    <X size={14} className="text-content-tertiary" />
                  </button>
                </div>
                {parsedPositions && (
                  <div className="flex items-center justify-center gap-1.5 text-xs text-emerald-600">
                    <CheckCircle2 size={14} />
                    {parsedPositions.length} {t('gaeb.positions_found', { defaultValue: 'positions found' })}
                    {/* Phase read from the file's DP element - the old price
                        heuristic labelled every unpriced X83 as "X81" and a
                        priced X84 as "X83". Blue marks the priced phases. */}
                    {gaebPhase && (
                      <Badge
                        variant={gaebPhase === 'X84' || gaebPhase === 'X86' ? 'blue' : 'neutral'}
                        className="ml-2"
                      >
                        {gaebPhase}
                      </Badge>
                    )}
                  </div>
                )}
                {parseError && (
                  <div className="flex items-center justify-center gap-1.5 text-xs text-rose-600">
                    <AlertTriangle size={14} />
                    {parseError}
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-2">
                <FileUp size={32} className="mx-auto text-content-quaternary" />
                <p className="text-sm text-content-secondary">
                  {t('gaeb.drop_file', { defaultValue: 'Drop a GAEB XML file here, or' })}
                </p>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                >
                  {t('gaeb.browse', { defaultValue: 'Browse files' })}
                </Button>
                <p className="text-2xs text-content-quaternary">
                  {t('gaeb.formats_hint', { defaultValue: 'Supported: .x81, .x83, .x84, .xml (GAEB DA XML 3.3)' })}
                </p>
                <button
                  type="button"
                  onClick={handleDownloadSample}
                  className="mt-1 inline-flex items-center gap-1.5 text-2xs font-medium text-oe-blue hover:underline"
                >
                  <Download size={12} />
                  {t('gaeb.download_sample', {
                    defaultValue: 'No file yet? Download a sample GAEB X83 to try it',
                  })}
                </button>
              </div>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".x81,.x83,.x84,.xml"
              className="hidden"
              onChange={handleFileInputChange}
            />
          </div>

          {/* Preview */}
          {parsedPositions && parsedPositions.length > 0 && (
            <ImportPreview positions={parsedPositions} t={t} />
          )}

          {/* Target BOQ selection + Import button.
              Hidden once the import has run: leaving an armed "Import N
              positions" button under a "M positions imported" panel invites
              a double import. Clearing the file starts a fresh round. */}
          {parsedPositions && parsedPositions.length > 0 && !importResult && (
            <div className="rounded-xl border border-border bg-surface-primary p-5">
              <h3 className="text-sm font-semibold text-content-primary mb-3">
                {t('gaeb.target_boq', { defaultValue: 'Import Target' })}
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-content-tertiary mb-1">
                    {t('common.project', { defaultValue: 'Project' })}
                  </label>
                  <select
                    data-testid="gaeb-import-project"
                    value={importProjectId}
                    onChange={(e) => {
                      setImportProjectId(e.target.value);
                      setImportTargetBoqId('');
                    }}
                    className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                  >
                    <option value="">— {t('risk.select_project', { defaultValue: 'Select project' })} —</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-content-tertiary mb-1">
                    {t('boq.title', { defaultValue: 'BOQ' })}
                  </label>
                  <select
                    value={importTargetBoqId}
                    onChange={(e) => setImportTargetBoqId(e.target.value)}
                    disabled={!importProjectId}
                    className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm disabled:opacity-50"
                  >
                    <option value="">— {t('gaeb.select_boq', { defaultValue: 'Select BOQ' })} —</option>
                    <option value={NEW_BOQ_OPTION}>
                      + {t('gaeb.create_new_boq', { defaultValue: 'Create a new BOQ' })}
                      {gaebProjectName ? ` (${truncateFinding(gaebProjectName, 60)})` : ''}
                    </option>
                    {importBoqs.map((b) => (
                      <option key={b.id} value={b.id}>{b.name}</option>
                    ))}
                  </select>
                </div>
                <div className="flex items-end">
                  <Button
                    variant="primary"
                    className="w-full"
                    icon={isImporting ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}
                    onClick={handleImport}
                    disabled={!importTargetBoqId || isImporting}
                  >
                    {isImporting
                      ? t('gaeb.importing', { defaultValue: 'Importing...' })
                      : t('gaeb.import_btn', {
                          count: parsedPositions.length,
                          defaultValue: 'Import {{count}} position',
                          defaultValue_other: 'Import {{count}} positions',
                        })
                    }
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Import result */}
          {importResult && (
            <div className={`rounded-xl border p-4 ${importResult.errors.length > 0 ? 'border-amber-300 bg-amber-50/50 dark:bg-amber-950/20' : 'border-emerald-300 bg-emerald-50/50 dark:bg-emerald-950/20'}`}>
              <div className="flex items-center gap-2 text-sm font-medium">
                {importResult.errors.length > 0 ? (
                  <AlertTriangle size={16} className="text-amber-600" />
                ) : (
                  <CheckCircle2 size={16} className="text-emerald-600" />
                )}
                <span className="text-content-primary">
                  {importResult.imported} {t('gaeb.positions_imported', { defaultValue: 'positions imported' })}
                </span>
              </div>
              {importResult.errors.length > 0 && (
                /* Findings never reprint raw payloads: each entry is
                   truncated and the list wraps anywhere, so a base64 blob
                   or Langtext can not blow the layout sideways. */
                <ul className="mt-2 space-y-1 text-xs text-content-secondary [overflow-wrap:anywhere]">
                  {importResult.errors.map((err, idx) => (
                    <li key={`err-${err.slice(0, 40)}-${idx}`}>• {truncateFinding(err, 300)}</li>
                  ))}
                </ul>
              )}
              {importResult.imported > 0 && (
                <Link
                  data-testid="regional-open-boq"
                  // The editor is a path param (/boq/:boqId). `?boq=` was read by
                  // nothing, so this link promised the editor and delivered the list.
                  to={
                    importTargetBoqId && importTargetBoqId !== NEW_BOQ_OPTION
                      ? `/boq/${importTargetBoqId}`
                      : '/boq'
                  }
                  className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-oe-blue hover:underline"
                >
                  {t('gaeb.open_boq', {
                    defaultValue: 'Open in BOQ editor to review & validate →',
                  })}
                </Link>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Export Tab ───────────────────────────────────────────────── */}
      {activeTab === 'export' && (
        <div className="space-y-5">
          {/* BOQ selection */}
          <div className="rounded-xl border border-border bg-surface-primary p-5">
            <h3 className="text-sm font-semibold text-content-primary mb-3">
              {t('gaeb.source_boq', { defaultValue: '1. Select BOQ to Export' })}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1">
                  {t('common.project', { defaultValue: 'Project' })}
                </label>
                <select
                  data-testid="gaeb-export-project"
                  value={exportProjectId}
                  onChange={(e) => {
                    setExportProjectId(e.target.value);
                    setExportBoqId('');
                  }}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                >
                  <option value="">— {t('risk.select_project', { defaultValue: 'Select project' })} —</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1">
                  {t('boq.title', { defaultValue: 'BOQ' })}
                </label>
                <select
                  data-testid="gaeb-export-boq"
                  value={exportBoqId}
                  onChange={(e) => setExportBoqId(e.target.value)}
                  disabled={!exportProjectId}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm disabled:opacity-50"
                >
                  <option value="">— {t('gaeb.select_boq', { defaultValue: 'Select BOQ' })} —</option>
                  {exportBoqs.map((b) => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-content-tertiary mb-1">
                  {t('gaeb.export_format', { defaultValue: 'Format' })}
                </label>
                <select
                  value={exportFormat}
                  onChange={(e) => setExportFormat(e.target.value as ExportFormatChoice)}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm"
                >
                  <option value="X83">X83 - {t('gaeb.x83_desc', { defaultValue: 'Invitation to Tender (Ausschreibung)' })}</option>
                  <option value="X81">X81 - {t('gaeb.x81_desc', { defaultValue: 'Tender Specification (no prices)' })}</option>
                  <option value="X84">X84 - {t('gaeb.x84_desc', { defaultValue: 'Bid Submission (priced offer)' })}</option>
                </select>
              </div>
            </div>
          </div>

          {/* Export summary */}
          {exportBoqId && exportablePositions.length > 0 && (
            <div className="rounded-xl border border-border bg-surface-primary p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('gaeb.export_summary', { defaultValue: '2. Export Summary' })}
                </h3>
                <button
                  onClick={() => setShowExportPreview((v) => !v)}
                  className="flex items-center gap-1 text-xs text-oe-blue hover:underline"
                >
                  <Eye size={13} />
                  {showExportPreview ? t('gaeb.hide_preview', { defaultValue: 'Hide preview' }) : t('gaeb.show_preview', { defaultValue: 'Show preview' })}
                </button>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">{t('gaeb.positions', { defaultValue: 'Positions' })}</div>
                  <div className="text-lg font-bold text-content-primary">{exportablePositions.filter((p) => !p.isSection).length}</div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">{t('gaeb.sections', { defaultValue: 'Sections' })}</div>
                  <div className="text-lg font-bold text-content-primary">{exportablePositions.filter((p) => p.isSection).length}</div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center">
                  <div className="text-2xs text-content-tertiary uppercase">{t('gaeb.format_label', { defaultValue: 'Format' })}</div>
                  <div className="text-lg font-bold text-content-primary">{exportFormat}</div>
                </div>
                <div className="rounded-lg bg-surface-secondary/50 p-3 text-center" data-testid="gaeb-prices-tile">
                  <div className="text-2xs text-content-tertiary uppercase">{t('gaeb.prices', { defaultValue: 'Prices' })}</div>
                  {/* "Yes" only when every line item carries a rate. One priced
                      line out of four hundred is not a priced bid, and the
                      bidder who reads "Yes" and receives a half-priced file has
                      no way back - so the partial state names how many rates
                      are still missing instead of rounding up to Yes. */}
                  <div
                    className={`text-lg font-bold ${priceState === 'partial' ? 'text-amber-600 dark:text-amber-400' : 'text-content-primary'}`}
                  >
                    {priceState === 'all' && t('common.yes', { defaultValue: 'Yes' })}
                    {/* `boq.partial` is the platform's existing "some but not
                        all" label, already translated in every locale. */}
                    {priceState === 'partial' && t('boq.partial', { defaultValue: 'Partial' })}
                    {priceState === 'none' && t('common.no', { defaultValue: 'No' })}
                  </div>
                  {priceState === 'partial' && (
                    <div className="text-2xs text-amber-600 dark:text-amber-400">
                      {t('gaeb.prices_missing', {
                        count: coverage.missing,
                        defaultValue: '{{count}} line without a rate',
                        defaultValue_other: '{{count}} lines without a rate',
                      })}
                    </div>
                  )}
                </div>
              </div>

              {showExportPreview && (
                <div className="border border-border-light rounded-lg overflow-x-auto max-h-60">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-surface-tertiary/50 sticky top-0">
                        <th className="px-3 py-1.5 text-left font-medium text-content-secondary">{t('boq.ordinal', { defaultValue: 'Ordinal' })}</th>
                        <th className="px-3 py-1.5 text-left font-medium text-content-secondary">{t('boq.description', { defaultValue: 'Description' })}</th>
                        <th className="px-3 py-1.5 text-center font-medium text-content-secondary">{t('boq.unit', { defaultValue: 'Unit' })}</th>
                        <th className="px-3 py-1.5 text-right font-medium text-content-secondary">{t('boq.quantity', { defaultValue: 'Qty' })}</th>
                        {exportFormat !== 'X81' && (
                          <th className="px-3 py-1.5 text-right font-medium text-content-secondary">{t('boq.unit_rate', { defaultValue: 'Rate' })}</th>
                        )}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-light">
                      {/* GAEB export preview stays metric-canonical (interchange
                          round-trip): no measurement-system conversion. (#270) */}
                      {exportablePositions.filter((p) => !p.isSection).slice(0, 30).map((pos) => (
                        <tr key={pos.id} className="hover:bg-surface-secondary/30">
                          <td className="px-3 py-1.5 font-mono text-content-tertiary">{pos.ordinal}</td>
                          <td className="px-3 py-1.5 text-content-primary max-w-[280px] truncate">{pos.description}</td>
                          <td className="px-3 py-1.5 text-center text-content-secondary">{pos.unit}</td>
                          <td className="px-3 py-1.5 text-right tabular-nums">{fmtNumber(pos.quantity, 3)}</td>
                          {exportFormat !== 'X81' && (
                            <td className="px-3 py-1.5 text-right tabular-nums">{fmtNumber(pos.unitRate, 2)}</td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <Button
                variant="primary"
                icon={isExporting ? <Loader2 size={15} className="animate-spin" /> : <FileDown size={15} />}
                onClick={handleExport}
                disabled={isExporting}
              >
                {/* format is a GAEB exchange-phase token (X83, X84), not a word to translate. */}
                {t('gaeb.export_btn', { format: exportFormat, defaultValue: 'Export as GAEB {{format}}' })}
              </Button>
            </div>
          )}

          {exportBoqId && exportablePositions.length === 0 && (
            <div className="rounded-xl border border-border bg-surface-primary p-8 text-center">
              <FileText size={32} className="mx-auto text-content-quaternary mb-2" />
              <p className="text-sm text-content-tertiary">
                {t('gaeb.no_positions', { defaultValue: 'This BOQ has no positions to export.' })}
              </p>
            </div>
          )}
        </div>
      )}

    </div>
  );
}
