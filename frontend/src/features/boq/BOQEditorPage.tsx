import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Plus,
  Trash2,
  Download,
  Upload,
  ShieldCheck,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  FileSpreadsheet,
  FileText,
  MoreHorizontal,
  Activity,
  Circle,
  Pencil,
  BarChart3,
  FileDown,
  LayoutTemplate,
  Inbox,
  Sparkles,
} from 'lucide-react';
import { Button, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  boqApi,
  groupPositionsIntoSections,
  type Position,
  type CreatePositionData,
  type UpdatePositionData,
  type SectionGroup,
  type Markup,
  type ActivityEntry,
  type ActivityAction,
  type CostAutocompleteItem,
} from './api';
import { ApiError } from '@/shared/lib/api';
import { AutocompleteInput } from './AutocompleteInput';
import { AIChatPanel } from './AIChatPanel';

/* ── Constants ───────────────────────────────────────────────────────── */

const UNITS = ['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'] as const;

const VAT_RATE = 0.19;

/** Locale-aware number formatter for currency-like values. */
function createFormatter(locale = 'de-DE') {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * Format a number to compact form for large values (e.g. 127,600 -> "127.6K").
 * Values below 10,000 are shown in full.
 */
function fmtCompact(n: number, fmt: Intl.NumberFormat): string {
  if (Math.abs(n) >= 1_000_000) {
    return `${fmt.format(n / 1_000_000)}M`;
  }
  if (Math.abs(n) >= 10_000) {
    return `${fmt.format(n / 1_000)}K`;
  }
  return fmt.format(n);
}

/* ══════════════════════════════════════════════════════════════════════ */
/*  BOQEditorPage                                                        */
/* ══════════════════════════════════════════════════════════════════════ */

export function BOQEditorPage() {
  const { t } = useTranslation();
  const { boqId } = useParams<{ boqId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fmt = useMemo(() => createFormatter(), []);

  /* ── Data fetching ─────────────────────────────────────────────────── */

  const { data: boq, isLoading } = useQuery({
    queryKey: ['boq', boqId],
    queryFn: () => boqApi.get(boqId!),
    enabled: !!boqId,
  });

  const { data: markupsData } = useQuery({
    queryKey: ['boq-markups', boqId],
    queryFn: () => boqApi.getMarkups(boqId!),
    enabled: !!boqId,
    retry: (failCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failCount < 3;
    },
  });

  const markups: Markup[] = markupsData?.markups ?? [];

  const addToast = useToastStore((s) => s.addToast);

  /* ── Mutations ─────────────────────────────────────────────────────── */

  const addMutation = useMutation({
    mutationFn: (data: CreatePositionData) => boqApi.addPosition(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
      addToast({ type: 'success', title: t('boq.position_added', { defaultValue: 'Position added' }) });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdatePositionData }) =>
      boqApi.updatePosition(id, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['boq', boqId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => boqApi.deletePosition(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['boq', boqId] }),
  });

  /* ── Collapsed sections state ──────────────────────────────────────── */

  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());

  const toggleSection = useCallback((sectionId: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  }, []);

  /* ── AI Chat panel ────────────────────────────────────────────────── */

  const [aiChatOpen, setAiChatOpen] = useState(false);

  const aiChatContext = useMemo(
    () => ({
      project_name: boq?.name ?? 'Unnamed project',
      currency: 'EUR',
      standard: 'din276',
      existing_positions_count: boq?.positions.length ?? 0,
    }),
    [boq?.name, boq?.positions.length],
  );

  const handleAIAddPositions = useCallback(
    (items: CreatePositionData[]) => {
      for (const item of items) {
        addMutation.mutate(item);
      }
    },
    [addMutation],
  );

  /* ── Activity panel ───────────────────────────────────────────────── */

  const [activityOpen, setActivityOpen] = useState(false);

  const { data: activityData } = useQuery({
    queryKey: ['boq-activity', boqId],
    queryFn: () => boqApi.getActivity(boqId!),
    enabled: !!boqId,
    retry: (failCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failCount < 3;
    },
    refetchInterval: activityOpen ? 30_000 : false,
  });

  const activities: ActivityEntry[] = activityData?.activities ?? [];

  /* ── Export dropdown ───────────────────────────────────────────────── */

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

  /* ── Computed data ─────────────────────────────────────────────────── */

  const grouped = useMemo(() => {
    if (!boq) return { sections: [], ungrouped: [] };
    return groupPositionsIntoSections(boq.positions);
  }, [boq]);

  const directCost = useMemo(() => {
    if (!boq) return 0;
    return boq.positions.reduce((sum, p) => sum + p.total, 0);
  }, [boq]);

  const markupTotals = useMemo(() => {
    let running = directCost;
    return markups.map((m) => {
      const amount = running * (m.percentage / 100);
      running += amount;
      return { ...m, amount, runningTotal: running };
    });
  }, [directCost, markups]);

  const netTotal = useMemo(() => {
    if (markupTotals.length === 0) return directCost;
    const last = markupTotals[markupTotals.length - 1];
    return last ? last.runningTotal : directCost;
  }, [directCost, markupTotals]);

  const vatAmount = netTotal * VAT_RATE;
  const grossTotal = netTotal + vatAmount;

  /* ── Handlers ──────────────────────────────────────────────────────── */

  const handleAddSection = useCallback(() => {
    if (!boqId) return;
    const sectionCount =
      grouped.sections.length + 1;
    const ordinal = String(sectionCount).padStart(2, '0');

    addMutation.mutate({
      boq_id: boqId,
      ordinal,
      description: '',
      unit: '', // empty unit = section header
      quantity: 0,
      unit_rate: 0,
    });
  }, [boqId, boq, grouped.sections.length, addMutation]);

  const handleAddPosition = useCallback(
    (parentId?: string) => {
      if (!boqId) return;
      const positions = boq?.positions ?? [];

      // Determine the parent section for ordinal generation
      let parentOrdinal = '01';
      let childCount = 0;

      if (parentId) {
        const parentSection = positions.find((p) => p.id === parentId);
        if (parentSection) {
          parentOrdinal = parentSection.ordinal;
          childCount = positions.filter((p) => p.parent_id === parentId).length;
        }
      } else {
        // Add to last section, or generate top-level
        const lastSection = grouped.sections[grouped.sections.length - 1];
        if (lastSection) {
          parentOrdinal = lastSection.section.ordinal;
          parentId = lastSection.section.id;
          childCount = lastSection.children.length;
        } else {
          childCount = grouped.ungrouped.length;
        }
      }

      const childNum = String(childCount + 1).padStart(2, '0');
      const ordinal = `${parentOrdinal}.${childNum}`;

      addMutation.mutate({
        boq_id: boqId,
        ordinal,
        description: '',
        unit: 'm2',
        quantity: 0,
        unit_rate: 0,
        parent_id: parentId,
      });
    },
    [boqId, boq, grouped, addMutation],
  );

  const handleDeleteSection = useCallback(
    (sectionGroup: SectionGroup) => {
      // Delete all children first, then the section
      for (const child of sectionGroup.children) {
        deleteMutation.mutate(child.id);
      }
      deleteMutation.mutate(sectionGroup.section.id);
    },
    [deleteMutation],
  );

  const handleExport = useCallback(
    async (format: 'excel' | 'csv') => {
      setShowExportMenu(false);
      const token = localStorage.getItem('oe_access_token');
      const r = await fetch(`/api/v1/boq/boqs/${boqId}/export/${format}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (r.ok) {
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${boq?.name ?? 'boq'}.${format === 'excel' ? 'xlsx' : 'csv'}`;
        a.click();
        URL.revokeObjectURL(url);
        addToast({ type: 'success', title: t('boq.file_downloaded', { defaultValue: 'File downloaded' }) });
      }
    },
    [boqId, boq?.name, addToast, t],
  );

  const handleValidate = useCallback(async () => {
    const token = localStorage.getItem('oe_access_token');
    try {
      const r = await fetch(`/api/v1/boq/boqs/${boqId}/validate`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const result = await r.json();
      const score = typeof result?.score === 'number' ? `${Math.round(result.score * 100)}% score` : undefined;
      addToast({ type: 'info', title: t('boq.validation_complete', { defaultValue: 'Validation complete' }), message: score });
      navigate('/validation');
    } catch {
      // Validation endpoint failed — silently handle
    }
  }, [boqId, navigate, addToast, t]);

  /* ── Smart import ───────────────────────────────────────────────────── */

  const importInputRef = useRef<HTMLInputElement>(null);
  const [isImporting, setIsImporting] = useState(false);

  const handleImportFile = useCallback(
    async (file: File) => {
      if (!boqId) return;
      setIsImporting(true);
      const token = localStorage.getItem('oe_access_token');
      const form = new FormData();
      form.append('file', file);

      try {
        const res = await fetch(`/api/v1/boq/boqs/${boqId}/import/smart`, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: form,
        });

        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(body.detail || 'Import failed');
        }

        const result: {
          imported: number;
          errors: { item?: string; error: string }[];
          total_items: number;
          method: string;
          model_used: string | null;
          cad_format?: string;
          cad_elements?: number;
        } = await res.json();

        let methodLabel: string;
        if (result.method === 'cad_ai') {
          methodLabel = ` (CAD + ${result.model_used ?? 'AI'}, ${result.cad_elements ?? 0} elements)`;
        } else if (result.method === 'ai') {
          methodLabel = ` (AI: ${result.model_used ?? 'auto'})`;
        } else {
          methodLabel = ' (direct)';
        }
        addToast({
          type: result.imported > 0 ? 'success' : 'warning',
          title: `Imported ${result.imported} of ${result.total_items} items${methodLabel}`,
          message:
            result.errors.length > 0
              ? `${result.errors.length} error(s) occurred`
              : undefined,
        });

        queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
      } catch (err) {
        addToast({
          type: 'error',
          title: t('boq.import_failed', { defaultValue: 'Import failed' }),
          message: err instanceof Error ? err.message : 'Unknown error',
        });
      } finally {
        setIsImporting(false);
      }
    },
    [boqId, addToast, queryClient, t],
  );

  const handleImportInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleImportFile(file);
      e.target.value = '';
    },
    [handleImportFile],
  );

  /* ── Loading state ─────────────────────────────────────────────────── */

  if (isLoading) {
    return (
      <div className="max-w-content mx-auto py-8 animate-fade-in">
        <div className="space-y-4">
          <div className="h-8 w-48 rounded-lg bg-surface-secondary animate-shimmer bg-gradient-to-r from-surface-secondary via-surface-tertiary to-surface-secondary bg-[length:200%_100%]" />
          <div className="h-4 w-80 rounded-md bg-surface-secondary animate-shimmer bg-gradient-to-r from-surface-secondary via-surface-tertiary to-surface-secondary bg-[length:200%_100%]" />
          <div className="mt-6 rounded-xl border border-border-light bg-surface-elevated overflow-hidden">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="h-12 border-b border-border-light animate-shimmer bg-gradient-to-r from-surface-secondary via-surface-tertiary to-surface-secondary bg-[length:200%_100%]"
                style={{ animationDelay: `${i * 80}ms` }}
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!boq) {
    return (
      <div className="max-w-content mx-auto py-16 text-center">
        <p className="text-content-secondary">BOQ not found</p>
      </div>
    );
  }

  const hasPositions = boq.positions.length > 0;

  /* ── Render ────────────────────────────────────────────────────────── */

  return (
    <div className="max-w-content mx-auto animate-fade-in pb-12">
      {/* ── Back link ──────────────────────────────────────────────────── */}
      <button
        onClick={() => navigate(-1)}
        className="mb-5 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors duration-fast"
      >
        <ArrowLeft size={14} />
        {t('boq.back_to_project')}
      </button>

      {/* ── Header bar ─────────────────────────────────────────────────── */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-content-primary truncate">{boq.name}</h1>
            <Badge
              variant={
                boq.status === 'final' ? 'success' : boq.status === 'draft' ? 'blue' : 'neutral'
              }
              size="md"
            >
              {boq.status}
            </Badge>
          </div>
          {boq.description && (
            <p className="mt-1 text-sm text-content-secondary">{boq.description}</p>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* Validate */}
          <Button variant="ghost" size="sm" icon={<ShieldCheck size={15} />} onClick={handleValidate}>
            {t('boq.validate')}
          </Button>

          {/* Smart Import */}
          <Button
            variant="ghost"
            size="sm"
            icon={<Upload size={15} />}
            onClick={() => importInputRef.current?.click()}
            loading={isImporting}
            disabled={isImporting}
          >
            {t('common.import', { defaultValue: 'Import' })}
          </Button>
          <input
            ref={importInputRef}
            type="file"
            accept=".xlsx,.csv,.pdf,.jpg,.jpeg,.png,.tiff,.rvt,.ifc,.dwg,.dgn"
            className="hidden"
            onChange={handleImportInputChange}
          />

          {/* Export dropdown */}
          <div ref={exportRef} className="relative">
            <Button
              variant="ghost"
              size="sm"
              icon={<Download size={15} />}
              onClick={() => setShowExportMenu((prev) => !prev)}
            >
              {t('boq.export')}
            </Button>
            {showExportMenu && (
              <div className="absolute right-0 top-full mt-1 z-50 w-44 rounded-lg border border-border-light bg-surface-elevated shadow-md animate-fade-in">
                <button
                  onClick={() => handleExport('excel')}
                  className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors rounded-t-lg"
                >
                  <FileSpreadsheet size={15} className="text-content-tertiary" />
                  Excel (.xlsx)
                </button>
                <button
                  onClick={() => handleExport('csv')}
                  className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm text-content-primary hover:bg-surface-secondary transition-colors rounded-b-lg"
                >
                  <FileText size={15} className="text-content-tertiary" />
                  CSV (.csv)
                </button>
              </div>
            )}
          </div>

          {/* AI Assistant toggle */}
          <Button
            variant={aiChatOpen ? 'primary' : 'ghost'}
            size="sm"
            icon={<Sparkles size={15} />}
            onClick={() => setAiChatOpen((prev) => !prev)}
          >
            {t('boq.ai_assistant', { defaultValue: 'AI Assistant' })}
          </Button>

          {/* Add Section */}
          <Button variant="secondary" size="sm" icon={<Plus size={15} />} onClick={handleAddSection}>
            {t('boq.add_section')}
          </Button>

          {/* Add Position */}
          <Button variant="primary" size="sm" icon={<Plus size={15} />} onClick={() => handleAddPosition()}>
            {t('boq.add_position')}
          </Button>
        </div>
      </div>

      {/* ── BOQ Table ──────────────────────────────────────────────────── */}
      <div className="rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            {/* ── Sticky header ──────────────────────────────────────── */}
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-border bg-surface-tertiary">
                <th className="w-[80px] px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('boq.ordinal')}
                </th>
                <th className="min-w-[300px] px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('boq.description')}
                </th>
                <th className="w-[60px] px-3 py-3 text-center text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('boq.unit')}
                </th>
                <th className="w-[100px] px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('boq.quantity')}
                </th>
                <th className="w-[100px] px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('boq.unit_rate')}
                </th>
                <th className="w-[120px] px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-content-tertiary">
                  {t('boq.total')}
                </th>
                <th className="w-[40px] px-1 py-3" />
              </tr>
            </thead>

            <tbody>
              {/* ── Ungrouped positions (no parent section) ─────────── */}
              {grouped.ungrouped.map((pos, idx) => (
                <PositionRow
                  key={pos.id}
                  position={pos}
                  onUpdate={(data) => updateMutation.mutate({ id: pos.id, data })}
                  onDelete={() => deleteMutation.mutate(pos.id)}
                  fmt={fmt}
                  isEven={idx % 2 === 0}
                />
              ))}

              {/* ── Sections with children ─────────────────────────── */}
              {grouped.sections.map((group) => {
                const isCollapsed = collapsedSections.has(group.section.id);
                return (
                  <SectionBlock
                    key={group.section.id}
                    group={group}
                    isCollapsed={isCollapsed}
                    onToggle={() => toggleSection(group.section.id)}
                    onUpdateSection={(data) =>
                      updateMutation.mutate({ id: group.section.id, data })
                    }
                    onDeleteSection={() => handleDeleteSection(group)}
                    onUpdatePosition={(id, data) => updateMutation.mutate({ id, data })}
                    onDeletePosition={(id) => deleteMutation.mutate(id)}
                    onAddPosition={() => handleAddPosition(group.section.id)}
                    fmt={fmt}
                    t={t}
                  />
                );
              })}

              {/* ── Empty state ────────────────────────────────────── */}
              {!hasPositions && (
                <tr>
                  <td colSpan={7} className="px-4 py-16 text-center">
                    <div className="flex flex-col items-center gap-3">
                      <div className="h-12 w-12 rounded-xl bg-surface-secondary flex items-center justify-center">
                        <Plus size={20} className="text-content-tertiary" />
                      </div>
                      <p className="text-sm text-content-tertiary">
                        {t('boq.no_positions')}
                      </p>
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<Plus size={14} />}
                        onClick={handleAddSection}
                      >
                        {t('boq.add_section')}
                      </Button>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>

            {/* ── Footer: Markups + Totals ────────────────────────────── */}
            {hasPositions && (
              <tfoot>
                {/* Direct Cost */}
                <tr className="border-t-2 border-border bg-surface-tertiary/50">
                  <td className="px-4 py-3" />
                  <td className="px-4 py-3 text-sm font-semibold text-content-primary uppercase tracking-wide">
                    {t('boq.direct_cost')}
                  </td>
                  <td />
                  <td />
                  <td />
                  <td className="px-4 py-3 text-right text-sm font-bold text-content-primary tabular-nums">
                    {fmtCompact(directCost, fmt)}
                  </td>
                  <td />
                </tr>

                {/* Markup lines */}
                {markupTotals.map((m) => (
                  <tr
                    key={m.id}
                    className="border-t border-border-light bg-surface-tertiary/30"
                  >
                    <td className="px-4 py-2.5" />
                    <td className="px-4 py-2.5 text-sm text-content-secondary">
                      {m.name}{' '}
                      <span className="text-content-tertiary">{fmt.format(m.percentage)}%</span>
                    </td>
                    <td />
                    <td />
                    <td />
                    <td className="px-4 py-2.5 text-right text-sm text-content-secondary tabular-nums">
                      {fmtCompact(m.amount, fmt)}
                    </td>
                    <td />
                  </tr>
                ))}

                {/* Divider before net */}
                {markups.length > 0 && (
                  <tr className="border-t border-border">
                    <td colSpan={7} className="h-0" />
                  </tr>
                )}

                {/* Net Total */}
                <tr className="border-t border-border bg-surface-tertiary/50">
                  <td className="px-4 py-3" />
                  <td className="px-4 py-3 text-sm font-semibold text-content-primary uppercase tracking-wide">
                    {t('boq.net_total')}
                  </td>
                  <td />
                  <td />
                  <td />
                  <td className="px-4 py-3 text-right text-sm font-bold text-content-primary tabular-nums">
                    {fmtCompact(netTotal, fmt)}
                  </td>
                  <td />
                </tr>

                {/* VAT */}
                <tr className="border-t border-border-light bg-surface-tertiary/30">
                  <td className="px-4 py-2.5" />
                  <td className="px-4 py-2.5 text-sm text-content-secondary">
                    {t('boq.vat')} {fmt.format(VAT_RATE * 100)}%
                  </td>
                  <td />
                  <td />
                  <td />
                  <td className="px-4 py-2.5 text-right text-sm text-content-secondary tabular-nums">
                    {fmtCompact(vatAmount, fmt)}
                  </td>
                  <td />
                </tr>

                {/* Gross Total */}
                <tr className="border-t-2 border-border bg-surface-tertiary">
                  <td className="px-4 py-4" />
                  <td className="px-4 py-4 text-base font-bold text-content-primary uppercase tracking-wide">
                    {t('boq.gross_total')}
                  </td>
                  <td />
                  <td />
                  <td />
                  <td className="px-4 py-4 text-right text-base font-bold text-content-primary tabular-nums">
                    {fmtCompact(grossTotal, fmt)}
                  </td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </div>

      {/* ── Activity Log Panel ────────────────────────────────────────── */}
      <ActivityPanel
        activities={activities}
        isOpen={activityOpen}
        onToggle={() => setActivityOpen((prev) => !prev)}
        t={t}
      />

      {/* ── AI Chat Panel ──────────────────────────────────────────────── */}
      <AIChatPanel
        boqId={boqId!}
        context={aiChatContext}
        isOpen={aiChatOpen}
        onClose={() => setAiChatOpen(false)}
        onAddPositions={handleAIAddPositions}
      />
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════ */
/*  SectionBlock                                                         */
/* ══════════════════════════════════════════════════════════════════════ */

function SectionBlock({
  group,
  isCollapsed,
  onToggle,
  onUpdateSection,
  onDeleteSection,
  onUpdatePosition,
  onDeletePosition,
  onAddPosition,
  fmt,
  t,
}: {
  group: SectionGroup;
  isCollapsed: boolean;
  onToggle: () => void;
  onUpdateSection: (data: UpdatePositionData) => void;
  onDeleteSection: () => void;
  onUpdatePosition: (id: string, data: UpdatePositionData) => void;
  onDeletePosition: (id: string) => void;
  onAddPosition: () => void;
  fmt: Intl.NumberFormat;
  t: (key: string) => string;
}) {
  const [editingDescription, setEditingDescription] = useState(false);
  const [showSectionMenu, setShowSectionMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowSectionMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const { section, children, subtotal } = group;

  return (
    <>
      {/* ── Section header row ───────────────────────────────────────── */}
      <tr className="group border-t-2 border-border bg-surface-secondary/70 hover:bg-surface-secondary transition-colors">
        {/* Ordinal */}
        <td className="px-4 py-3">
          <span className="text-sm font-bold text-content-primary font-mono">
            {section.ordinal}
          </span>
        </td>

        {/* Description + collapse toggle */}
        <td className="px-4 py-3" colSpan={4}>
          <div className="flex items-center gap-2">
            <button
              onClick={onToggle}
              className="shrink-0 h-5 w-5 flex items-center justify-center rounded text-content-tertiary hover:text-content-primary hover:bg-surface-tertiary transition-colors"
            >
              {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
            </button>

            {editingDescription ? (
              <input
                type="text"
                defaultValue={section.description}
                autoFocus
                className="flex-1 bg-transparent border-none outline-none text-sm font-bold text-content-primary uppercase tracking-wide p-0"
                onBlur={(e) => {
                  setEditingDescription(false);
                  onUpdateSection({ description: e.target.value });
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                  if (e.key === 'Escape') setEditingDescription(false);
                }}
              />
            ) : (
              <span
                onClick={() => setEditingDescription(true)}
                className="flex-1 text-sm font-bold text-content-primary uppercase tracking-wide cursor-text min-h-[20px]"
              >
                {section.description || (
                  <span className="text-content-tertiary font-normal normal-case tracking-normal">
                    {t('boq.description')}...
                  </span>
                )}
              </span>
            )}
          </div>

          {/* Subtotal label below the section name */}
          {!isCollapsed && children.length > 0 && (
            <div className="mt-0.5 ml-7 text-xs text-content-tertiary">
              {t('boq.section_subtotal')}
            </div>
          )}
        </td>

        {/* Subtotal value */}
        <td className="px-4 py-3 text-right align-top">
          <span className="text-sm font-bold text-content-primary tabular-nums">
            {fmtCompact(subtotal, fmt)}
          </span>
        </td>

        {/* Section actions */}
        <td className="px-1 py-3 align-top">
          <div ref={menuRef} className="relative">
            <button
              onClick={() => setShowSectionMenu((prev) => !prev)}
              className="opacity-0 group-hover:opacity-100 flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-tertiary transition-all"
            >
              <MoreHorizontal size={14} />
            </button>
            {showSectionMenu && (
              <div className="absolute right-0 top-full mt-1 z-50 w-44 rounded-lg border border-border-light bg-surface-elevated shadow-md animate-fade-in">
                <button
                  onClick={() => {
                    setShowSectionMenu(false);
                    onAddPosition();
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-sm text-content-primary hover:bg-surface-secondary transition-colors rounded-t-lg"
                >
                  <Plus size={14} className="text-content-tertiary" />
                  {t('boq.add_position')}
                </button>
                <button
                  onClick={() => {
                    setShowSectionMenu(false);
                    onDeleteSection();
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-sm text-semantic-error hover:bg-semantic-error-bg transition-colors rounded-b-lg"
                >
                  <Trash2 size={14} />
                  {t('common.delete')}
                </button>
              </div>
            )}
          </div>
        </td>
      </tr>

      {/* ── Child positions ──────────────────────────────────────────── */}
      {!isCollapsed &&
        children.map((pos, idx) => (
          <PositionRow
            key={pos.id}
            position={pos}
            onUpdate={(data) => onUpdatePosition(pos.id, data)}
            onDelete={() => onDeletePosition(pos.id)}
            fmt={fmt}
            isEven={idx % 2 === 0}
            isChild
          />
        ))}

      {/* ── Empty section hint ───────────────────────────────────────── */}
      {!isCollapsed && children.length === 0 && (
        <tr>
          <td colSpan={7} className="px-4 py-6 text-center">
            <button
              onClick={onAddPosition}
              className="inline-flex items-center gap-1.5 text-xs text-content-tertiary hover:text-oe-blue transition-colors"
            >
              <Plus size={12} />
              {t('boq.add_position')}
            </button>
          </td>
        </tr>
      )}
    </>
  );
}

/* ══════════════════════════════════════════════════════════════════════ */
/*  PositionRow                                                          */
/* ══════════════════════════════════════════════════════════════════════ */

function PositionRow({
  position,
  onUpdate,
  onDelete,
  fmt,
  isEven,
  isChild = false,
}: {
  position: Position;
  onUpdate: (data: UpdatePositionData) => void;
  onDelete: () => void;
  fmt: Intl.NumberFormat;
  isEven: boolean;
  isChild?: boolean;
}) {
  const [editing, setEditing] = useState<string | null>(null);

  const handleBlur = useCallback(
    (field: string, value: string) => {
      setEditing(null);
      const numFields = ['quantity', 'unit_rate'];
      const update: UpdatePositionData = {
        [field]: numFields.includes(field) ? parseFloat(value) || 0 : value,
      };
      onUpdate(update);
    },
    [onUpdate],
  );

  const handleSelectSuggestion = useCallback(
    (item: CostAutocompleteItem) => {
      setEditing(null);
      onUpdate({
        description: item.description,
        unit: item.unit,
        unit_rate: item.rate,
      });
    },
    [onUpdate],
  );

  const bgClass = isEven ? 'bg-surface-elevated' : 'bg-surface-primary/50';

  return (
    <tr
      className={`group border-t border-border-light hover:bg-oe-blue-subtle/30 transition-colors ${bgClass}`}
    >
      {/* Ordinal */}
      <td className="px-4 py-2.5">
        <EditableCell
          value={position.ordinal}
          field="ordinal"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          displayClassName={`text-sm font-mono ${isChild ? 'text-content-secondary' : 'text-content-primary'}`}
        />
      </td>

      {/* Description — with autocomplete */}
      <td className={`px-4 py-2.5 ${isChild ? 'pl-8' : ''}`}>
        {editing === 'description' ? (
          <AutocompleteInput
            value={position.description}
            onCommit={(value) => handleBlur('description', value)}
            onSelectSuggestion={handleSelectSuggestion}
            onCancel={() => setEditing(null)}
            placeholder="Enter description..."
          />
        ) : (
          <span
            onClick={() => setEditing('description')}
            className={`block min-h-[20px] cursor-text rounded px-1.5 py-0.5 -mx-1.5 -my-0.5 hover:bg-surface-secondary/80 transition-colors text-sm text-content-primary ${
              !position.description ? 'text-content-tertiary italic' : ''
            }`}
          >
            {position.description || 'Enter description...'}
          </span>
        )}
      </td>

      {/* Unit */}
      <td className="px-3 py-2.5 text-center">
        <select
          value={position.unit}
          onChange={(e) => onUpdate({ unit: e.target.value })}
          className="bg-transparent text-xs text-center cursor-pointer border-none outline-none text-content-secondary hover:text-content-primary font-mono uppercase appearance-none w-full"
        >
          {UNITS.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
      </td>

      {/* Quantity */}
      <td className="px-4 py-2.5 text-right">
        <EditableCell
          value={String(position.quantity)}
          field="quantity"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          displayClassName="text-sm text-content-primary tabular-nums text-right"
          displayValue={fmt.format(position.quantity)}
          type="number"
        />
      </td>

      {/* Unit Rate */}
      <td className="px-4 py-2.5 text-right">
        <EditableCell
          value={String(position.unit_rate)}
          field="unit_rate"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          displayClassName="text-sm text-content-secondary tabular-nums text-right"
          displayValue={fmt.format(position.unit_rate)}
          type="number"
        />
      </td>

      {/* Total (computed, read-only) */}
      <td className="px-4 py-2.5 text-right">
        <span className="text-sm font-semibold text-content-primary tabular-nums">
          {fmtCompact(position.total, fmt)}
        </span>
      </td>

      {/* Delete */}
      <td className="px-1 py-2.5">
        <button
          onClick={onDelete}
          className="opacity-0 group-hover:opacity-100 flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg transition-all"
          title="Delete"
        >
          <Trash2 size={13} />
        </button>
      </td>
    </tr>
  );
}

/* ══════════════════════════════════════════════════════════════════════ */
/*  EditableCell                                                         */
/* ══════════════════════════════════════════════════════════════════════ */

function EditableCell({
  value,
  field,
  editing,
  setEditing,
  onBlur,
  displayClassName,
  displayValue,
  placeholder,
  type = 'text',
}: {
  value: string;
  field: string;
  editing: string | null;
  setEditing: (f: string | null) => void;
  onBlur: (field: string, value: string) => void;
  displayClassName?: string;
  displayValue?: string;
  placeholder?: string;
  type?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing === field && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing, field]);

  if (editing === field) {
    return (
      <input
        ref={inputRef}
        type={type}
        defaultValue={value}
        className="w-full bg-surface-elevated border border-oe-blue/40 rounded px-1.5 py-0.5 outline-none text-sm text-content-primary ring-2 ring-oe-blue/20 tabular-nums"
        placeholder={placeholder}
        onBlur={(e) => onBlur(field, e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          if (e.key === 'Escape') setEditing(null);
          if (e.key === 'Tab') {
            // Let default tab behavior happen, but commit the edit
            (e.target as HTMLInputElement).blur();
          }
        }}
      />
    );
  }

  return (
    <span
      onClick={() => setEditing(field)}
      className={`block min-h-[20px] cursor-text rounded px-1.5 py-0.5 -mx-1.5 -my-0.5 hover:bg-surface-secondary/80 transition-colors ${
        displayClassName ?? ''
      } ${!value && placeholder ? 'text-content-tertiary italic' : ''}`}
    >
      {(displayValue ?? value) || placeholder || ''}
    </span>
  );
}

/* ══════════════════════════════════════════════════════════════════════ */
/*  ActivityPanel                                                        */
/* ══════════════════════════════════════════════════════════════════════ */

/** Map action types to icon + color for visual distinction. */
const ACTIVITY_ICON_MAP: Record<ActivityAction, { icon: React.ReactNode; color: string }> = {
  position_added: {
    icon: <Circle size={12} strokeWidth={3} />,
    color: 'text-[#34c759]',
  },
  position_updated: {
    icon: <Pencil size={12} strokeWidth={2} />,
    color: 'text-oe-blue',
  },
  position_deleted: {
    icon: <Trash2 size={12} strokeWidth={2} />,
    color: 'text-semantic-error',
  },
  quantity_updated: {
    icon: <Pencil size={12} strokeWidth={2} />,
    color: 'text-oe-blue',
  },
  rate_updated: {
    icon: <Pencil size={12} strokeWidth={2} />,
    color: 'text-oe-blue',
  },
  section_added: {
    icon: <Plus size={12} strokeWidth={2.5} />,
    color: 'text-[#34c759]',
  },
  section_deleted: {
    icon: <Trash2 size={12} strokeWidth={2} />,
    color: 'text-semantic-error',
  },
  validation_run: {
    icon: <BarChart3 size={12} strokeWidth={2} />,
    color: 'text-[#5856d6]',
  },
  excel_imported: {
    icon: <FileDown size={12} strokeWidth={2} />,
    color: 'text-[#34c759]',
  },
  csv_imported: {
    icon: <FileDown size={12} strokeWidth={2} />,
    color: 'text-[#34c759]',
  },
  boq_created: {
    icon: <Plus size={12} strokeWidth={2.5} />,
    color: 'text-oe-blue',
  },
  template_applied: {
    icon: <LayoutTemplate size={12} strokeWidth={2} />,
    color: 'text-[#5856d6]',
  },
  markup_added: {
    icon: <Plus size={12} strokeWidth={2.5} />,
    color: 'text-[#34c759]',
  },
  markup_updated: {
    icon: <Pencil size={12} strokeWidth={2} />,
    color: 'text-oe-blue',
  },
  status_changed: {
    icon: <Activity size={12} strokeWidth={2} />,
    color: 'text-[#ff9f0a]',
  },
};

/** Format a timestamp as a relative time string (e.g. "2m ago", "3h ago"). */
function formatRelativeTime(isoString: string): string {
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffMs = now - then;

  if (diffMs < 0) return 'just now';

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return 'just now';

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;

  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d`;

  const months = Math.floor(days / 30);
  return `${months}mo`;
}

function ActivityPanel({
  activities,
  isOpen,
  onToggle,
  t,
}: {
  activities: ActivityEntry[];
  isOpen: boolean;
  onToggle: () => void;
  t: (key: string, options?: Record<string, string>) => string;
}) {
  const visibleActivities = isOpen ? activities : activities.slice(0, 5);

  return (
    <div className="mt-6 rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden transition-all">
      {/* ── Toggle header ──────────────────────────────────────────── */}
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-5 py-3.5 hover:bg-surface-secondary/50 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <Activity size={16} className="text-content-tertiary" strokeWidth={1.75} />
          <span className="text-sm font-semibold text-content-primary">
            {t('boq.recent_activity', { defaultValue: 'Recent Activity' })}
          </span>
          {activities.length > 0 && (
            <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-surface-secondary px-1.5 text-2xs font-medium text-content-secondary tabular-nums">
              {activities.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-content-tertiary">
          {isOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </div>
      </button>

      {/* ── Activity list ──────────────────────────────────────────── */}
      {activities.length === 0 ? (
        <div className="px-5 pb-5 pt-1">
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-secondary">
              <Inbox size={18} className="text-content-tertiary" />
            </div>
            <p className="text-xs text-content-tertiary">
              {t('boq.no_activity', { defaultValue: 'No activity yet. Changes will appear here.' })}
            </p>
          </div>
        </div>
      ) : (
        <div className="border-t border-border-light">
          <ul className="divide-y divide-border-light">
            {visibleActivities.map((entry) => {
              const mapping = ACTIVITY_ICON_MAP[entry.action] ?? {
                icon: <Activity size={12} strokeWidth={2} />,
                color: 'text-content-tertiary',
              };

              return (
                <li
                  key={entry.id}
                  className="flex items-center gap-3 px-5 py-3 hover:bg-surface-secondary/30 transition-colors"
                >
                  {/* Icon */}
                  <div
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-surface-secondary ${mapping.color}`}
                  >
                    {mapping.icon}
                  </div>

                  {/* Description */}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-content-primary truncate">
                      {entry.description}
                    </p>
                    {entry.user_name && (
                      <p className="text-2xs text-content-tertiary mt-0.5">
                        {entry.user_name}
                      </p>
                    )}
                  </div>

                  {/* Relative time */}
                  <span className="shrink-0 text-xs text-content-tertiary tabular-nums">
                    {formatRelativeTime(entry.created_at)}
                  </span>
                </li>
              );
            })}
          </ul>

          {/* Show all link */}
          {!isOpen && activities.length > 5 && (
            <div className="border-t border-border-light px-5 py-3">
              <button
                onClick={onToggle}
                className="text-xs font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
              >
                {t('boq.show_all_activity', { defaultValue: 'Show all activity...' })}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
