// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { boqApi, type Markup, type CreateMarkupData, type UpdateMarkupData } from './api';
import { fmtWithCurrency } from './boqHelpers';
import { toNum } from '@/shared/lib/money';
import { parseDecimalInput } from '@/shared/lib/parseDecimal';
import { useToastStore } from '@/stores/useToastStore';
import clsx from 'clsx';
import {
  ChevronDown,
  Plus,
  Trash2,
  Globe,
  GripVertical,
} from 'lucide-react';

/** Regional templates — code must match backend DEFAULT_MARKUP_TEMPLATES keys. */
const REGIONS: { code: string; flag: string; label: string; standard: string }[] = [
  // Europe
  { code: 'DACH', flag: '\ud83c\udde9\ud83c\uddea', label: 'DACH', standard: 'VOB/HOAI' },
  { code: 'UK', flag: '\ud83c\uddec\ud83c\udde7', label: 'United Kingdom', standard: 'NRM/RICS' },
  { code: 'FR', flag: '\ud83c\uddeb\ud83c\uddf7', label: 'France', standard: 'BATIPRIX' },
  { code: 'ES', flag: '\ud83c\uddea\ud83c\uddf8', label: 'Spain', standard: 'CTE' },
  { code: 'IT', flag: '\ud83c\uddee\ud83c\uddf9', label: 'Italy', standard: 'Prezzario' },
  { code: 'NL', flag: '\ud83c\uddf3\ud83c\uddf1', label: 'Netherlands', standard: 'STABU' },
  { code: 'PL', flag: '\ud83c\uddf5\ud83c\uddf1', label: 'Poland', standard: 'KNR' },
  { code: 'BE', flag: '\ud83c\udde7\ud83c\uddea', label: 'Belgium', standard: 'BSAB' },
  { code: 'CZ', flag: '\ud83c\udde8\ud83c\uddff', label: 'Czech Republic', standard: 'TSP' },
  { code: 'RO', flag: '\ud83c\uddf7\ud83c\uddf4', label: 'Romania', standard: 'DevGen' },
  { code: 'GR', flag: '\ud83c\uddec\ud83c\uddf7', label: 'Greece', standard: 'ATOE' },
  { code: 'HU', flag: '\ud83c\udded\ud83c\uddfa', label: 'Hungary', standard: 'TERC' },
  { code: 'UA', flag: '\ud83c\uddfa\ud83c\udde6', label: 'Ukraine', standard: '\u041a\u041d\u0423' },
  { code: 'PT', flag: '\ud83c\uddf5\ud83c\uddf9', label: 'Portugal', standard: 'ProNIC' },
  { code: 'NORDIC', flag: '\ud83c\uddf8\ud83c\uddea', label: 'Scandinavia', standard: 'AB 04' },
  // Americas
  { code: 'US', flag: '\ud83c\uddfa\ud83c\uddf8', label: 'United States', standard: 'MasterFormat/AIA' },
  { code: 'CA', flag: '\ud83c\udde8\ud83c\udde6', label: 'Canada', standard: 'CCDC' },
  { code: 'BR', flag: '\ud83c\udde7\ud83c\uddf7', label: 'Brazil', standard: 'TCU/SINAPI' },
  { code: 'AR', flag: '\ud83c\udde6\ud83c\uddf7', label: 'Argentina', standard: 'CAC' },
  { code: 'CL', flag: '\ud83c\udde8\ud83c\uddf1', label: 'Chile', standard: 'CDT' },
  { code: 'CO', flag: '\ud83c\udde8\ud83c\uddf4', label: 'Colombia', standard: 'NTC' },
  { code: 'PE', flag: '\ud83c\uddf5\ud83c\uddea', label: 'Peru', standard: 'CAPECO' },
  // Asia-Pacific
  { code: 'CN', flag: '\ud83c\udde8\ud83c\uddf3', label: 'China', standard: 'GB50500' },
  { code: 'IN', flag: '\ud83c\uddee\ud83c\uddf3', label: 'India', standard: 'CPWD' },
  { code: 'JP', flag: '\ud83c\uddef\ud83c\uddf5', label: 'Japan', standard: 'MLIT' },
  { code: 'KR', flag: '\ud83c\uddf0\ud83c\uddf7', label: 'South Korea', standard: 'KICT' },
  { code: 'AU', flag: '\ud83c\udde6\ud83c\uddfa', label: 'Australia', standard: 'AIQS' },
  { code: 'NZ', flag: '\ud83c\uddf3\ud83c\uddff', label: 'New Zealand', standard: 'NZIQS' },
  { code: 'SG', flag: '\ud83c\uddf8\ud83c\uddec', label: 'Singapore', standard: 'BCA' },
  { code: 'MY', flag: '\ud83c\uddf2\ud83c\uddfe', label: 'Malaysia', standard: 'JKR' },
  { code: 'TH', flag: '\ud83c\uddf9\ud83c\udded', label: 'Thailand', standard: 'EIT' },
  { code: 'ID', flag: '\ud83c\uddee\ud83c\udde9', label: 'Indonesia', standard: 'SNI' },
  { code: 'PH', flag: '\ud83c\uddf5\ud83c\udded', label: 'Philippines', standard: 'DPWH' },
  { code: 'VN', flag: '\ud83c\uddfb\ud83c\uddf3', label: 'Vietnam', standard: 'BXD' },
  // Middle East / Africa
  { code: 'GULF', flag: '\ud83c\udde6\ud83c\uddea', label: 'Gulf / UAE', standard: 'FIDIC' },
  { code: 'IL', flag: '\ud83c\uddee\ud83c\uddf1', label: 'Israel', standard: 'SI' },
  { code: 'TR', flag: '\ud83c\uddf9\ud83c\uddf7', label: 'Turkey', standard: 'BIB' },
  { code: 'NG', flag: '\ud83c\uddf3\ud83c\uddec', label: 'Nigeria', standard: 'BQSM' },
  { code: 'ZA', flag: '\ud83c\uddff\ud83c\udde6', label: 'South Africa', standard: 'ASAQS' },
  { code: 'KE', flag: '\ud83c\uddf0\ud83c\uddea', label: 'Kenya', standard: 'IQSK' },
  { code: 'MA', flag: '\ud83c\uddf2\ud83c\udde6', label: 'Morocco', standard: 'BPU' },
  // CIS
  { code: 'RU', flag: '\ud83c\uddf7\ud83c\uddfa', label: 'Russia / CIS', standard: '\u0413\u042d\u0421\u041d' },
  // Generic
  { code: 'DEFAULT', flag: '\ud83c\udf10', label: 'Generic International', standard: '' },
];

const CATEGORY_COLORS: Record<string, string> = {
  overhead: 'bg-blue-100 text-blue-700 dark:text-blue-300 dark:bg-blue-900/30',
  profit: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  tax: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  contingency: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
  insurance: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
  bond: 'bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-300',
  other: 'bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-300',
};

const CATEGORIES = ['overhead', 'profit', 'tax', 'contingency', 'insurance', 'bond', 'other'] as const;

/**
 * Charge each tranche of `base` at its own band rate and add them up.
 *
 * Mirrors `_banded_amount` in `backend/app/modules/boq/service.py`, which is
 * the authority. Progressive, not flat: a base of 1,500,000 against "first
 * 1,000,000 at 2.5 %, rest at 1 %" pays 25,000 on the first million and 5,000
 * on the remainder. A base sitting exactly on a band edge belongs entirely to
 * the lower band, the way a card that says "up to" reads.
 *
 * The card is user data arriving as JSON, so an entry this cannot read is
 * dropped rather than allowed to make the whole panel render nothing.
 */
export function bandedAmount(base: number, metadata: unknown): number {
  if (!metadata || typeof metadata !== 'object') return 0;
  const raw = (metadata as Record<string, unknown>).bands;
  if (!Array.isArray(raw)) return 0;

  // Bands arrive as JSON of unknown shape, so numbers are read defensively
  // rather than through ``toNum``, which is typed for wire money fields.
  const num = (v: unknown): number | null => {
    const n = typeof v === 'number' ? v : Number(String(v));
    return Number.isFinite(n) ? n : null;
  };

  const bands: { ceiling: number | null; rate: number }[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const row = entry as Record<string, unknown>;
    const rate = num(row.percentage ?? 0);
    if (rate === null) continue;
    const rawCeiling = row.up_to;
    if (rawCeiling === null || rawCeiling === undefined || String(rawCeiling).trim() === '') {
      bands.push({ ceiling: null, rate });
      continue;
    }
    const ceiling = num(rawCeiling);
    if (ceiling === null) continue;
    bands.push({ ceiling, rate });
  }

  // Ceilings ascending, the open-ended band last however it was written.
  bands.sort((a, b) => {
    if (a.ceiling === null) return b.ceiling === null ? 0 : 1;
    if (b.ceiling === null) return -1;
    return a.ceiling - b.ceiling;
  });

  let total = 0;
  let lower = 0;
  for (const { ceiling, rate } of bands) {
    const top = ceiling === null ? base : Math.min(base, ceiling);
    if (top <= lower) continue;
    total += ((top - lower) * rate) / 100;
    lower = top;
    if (lower >= base) break;
  }
  return total;
}

interface SectionEntry {
  id: string;
  ordinal: string;
  description: string;
}

interface MarkupPanelProps {
  boqId: string;
  markups: Markup[];
  directCost: number;
  currencySymbol: string;
  currencyCode: string;
  locale: string;
  fmt: Intl.NumberFormat;
  /**
   * Bumped by the host (the toolbar "Markups / OH&P" jump) to force this
   * panel open. The panel is collapsible and defaults open; bumping the
   * signal re-expands it after a manual collapse so the jump always lands
   * on visible content.
   */
  openSignal?: number;
  /** Available sections for scoping markups to a specific section. */
  sections?: SectionEntry[];
}

interface EditState {
  markupId: string;
  field: 'name' | 'percentage' | 'category';
  value: string;
}

export function MarkupPanel({ boqId, markups, directCost, currencySymbol, currencyCode, locale, fmt, openSignal, sections }: MarkupPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [isOpen, setIsOpen] = useState(true);
  const [editState, setEditState] = useState<EditState | null>(null);
  const [showRegionMenu, setShowRegionMenu] = useState(false);

  // Re-expand when the host bumps openSignal (toolbar "Markups / OH&P" jump).
  // Ignore the initial 0 so a user who manually collapsed the panel is not
  // re-opened on mount.
  useEffect(() => {
    if (openSignal && openSignal > 0) setIsOpen(true);
  }, [openSignal]);

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['boq-markups', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq-cost-breakdown', boqId] });
  }, [queryClient, boqId]);

  const addMutation = useMutation({
    mutationFn: (data: CreateMarkupData) => boqApi.addMarkup(boqId, data),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('boq.markup_added', { defaultValue: 'Markup added' }) });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('boq.markup_add_failed', { defaultValue: 'Failed to add markup' }), message: err.message });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ markupId, data }: { markupId: string; data: UpdateMarkupData }) =>
      boqApi.updateMarkup(boqId, markupId, data),
    onSuccess: () => invalidate(),
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('boq.markup_update_failed', { defaultValue: 'Failed to update markup' }), message: err.message });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (markupId: string) => boqApi.deleteMarkup(boqId, markupId),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('boq.markup_deleted', { defaultValue: 'Markup deleted' }) });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('boq.markup_delete_failed', { defaultValue: 'Failed to delete markup' }), message: err.message });
    },
  });

  const applyDefaultsMutation = useMutation({
    mutationFn: (region: string) => boqApi.applyDefaults(boqId, region),
    onSuccess: () => {
      invalidate();
      setShowRegionMenu(false);
      addToast({ type: 'success', title: t('boq.template_applied', { defaultValue: 'Regional template applied' }) });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('boq.apply_defaults_failed', { defaultValue: 'Failed to apply template' }), message: err.message });
    },
  });

  // Cascading calculation, used both for the per-row Amount column and for the
  // toggle flash so the flash matches what a row actually contributes (fixed
  // amounts and cumulative bases included). Memoised so the toggle handler can
  // read a row's real contribution without recomputing. Defensive against
  // malformed server payloads - Apply-Regional-Template used to crash the panel
  // when a markup came back without a numeric percentage.
  //
  // TWO PRODUCERS, NAMED. This cascade is a line-for-line mirror of the
  // authoritative server one, ``_calculate_markup_amounts`` in
  // ``backend/app/modules/boq/service.py`` (running sum, ``cumulative``/
  // ``subtotal`` on direct cost + preceding markups, ``fixed`` taking
  // ``fixed_amount``, inactive rows contributing zero). The SERVER IS
  // AUTHORITATIVE - ``GET /boqs/{id}/cost-breakdown/`` returns exactly
  // ``directCost + Σ(every active markup)`` as ``grand_total``, and that is
  // what the toolbar's Grand-Total card and the Cost Breakdown panel print.
  // It is duplicated here only because the panel needs a per-markup amount
  // keyed by markup id, which the server payload does not carry, and because
  // the toggle flash has to react before the round-trip lands. Change one, and
  // change the other.
  //
  // Two of the four markup types are mirrored with local arithmetic and two
  // are not, and the difference is about what the browser can honestly know.
  // ``percentage`` and ``fixed`` are reproduced outright. ``banded`` is too,
  // because the rate card travels on the row. ``escalation`` is NOT: the
  // factor comes from a cost-index series the browser does not hold, so the
  // server resolves it once and sends it on the row as ``escalation_factor``
  // and this block multiplies. Do not add a period lookup here.
  //
  // The cascade matches; the INPUT need not. ``directCost`` here is the
  // editor's live sum (``resourceAwareTotalInBase``, which trusts a position's
  // stored ``total`` whenever its resources are all base-currency), while the
  // server re-derives direct cost from the resources themselves and so heals a
  // stale stored ``total``. When those two disagree, so will this figure and
  // the server's - the server wins, and the gap is a direct-cost bug upstream
  // of this block, not a markup bug inside it.
  //
  // What this sum is NOT is a *net* total: it runs over every active markup,
  // ``category === 'tax'`` included, so with any of the 13 regional templates
  // applied it is the gross figure. It used to be labelled "Net Total", which
  // put a second, VAT-inclusive "Net Total" on the same screen as the grid
  // footer's real one. Net-of-tax lives in exactly one place now: the grid
  // footer in ``BOQEditorPage`` (``markupTotals`` filters ``category !== 'tax'``).
  const { calcMap, grandTotal, calculated } = useMemo(() => {
    let running = directCost;
    const calculated = (Array.isArray(markups) ? markups : [])
      .filter((m) => m && m.is_active !== false)
      .map((m) => {
        let amount = 0;
        const pct = typeof m.percentage === 'number' && Number.isFinite(m.percentage) ? m.percentage : 0;
        const base = m.apply_to === 'cumulative' || m.apply_to === 'subtotal' ? running : directCost;
        if (m.markup_type === 'fixed') {
          // fixed_amount arrives as a Decimal-as-string ("500.00"), so a
          // ``typeof === 'number'`` guard rejected it and rendered every fixed
          // markup as 0. Coerce through the shared money primitive instead.
          amount = toNum(m.fixed_amount);
        } else if (m.markup_type === 'banded') {
          // A bond's rate card, charged tranche by tranche. This one IS mirrored
          // locally because the card is on the row: no server round-trip and no
          // date arithmetic involved, just the same progressive sum.
          amount = bandedAmount(base, m.metadata);
        } else if (m.markup_type === 'escalation') {
          // The factor is resolved server-side from the cost-index series and
          // arrives on the row. The browser must NOT work one out: it holds no
          // series, and a second implementation of the period lookup is exactly
          // what the backend went out of its way not to have. A line with no
          // factor is worth nothing here, which is what the server reports too.
          const factor = toNum(m.escalation_factor ?? 0);
          amount = factor > 0 ? base * (factor - 1) : 0;
        } else if (m.apply_to === 'cumulative' || m.apply_to === 'subtotal') {
          // The backend treats 'subtotal' identically to 'cumulative' (base =
          // direct cost + the markups before it); GAEB import persists tax
          // markups as 'subtotal', so basing it on directCost here would
          // under-state the Amount column and the grand total against the server.
          amount = running * (pct / 100);
        } else {
          amount = directCost * (pct / 100);
        }
        running += amount;
        return { id: m.id, amount };
      });
    return { calcMap: new Map(calculated.map((c) => [c.id, c.amount])), grandTotal: running, calculated };
  }, [markups, directCost]);

  const handleAddMarkup = useCallback(() => {
    addMutation.mutate({
      name: t('boq.new_markup', { defaultValue: 'New Markup' }),
      percentage: 5,
      category: 'overhead',
      sort_order: markups.length,
    });
  }, [addMutation, markups.length, t]);

  const handleToggleActive = useCallback(
    (markup: Markup) => {
      // Impact for the brief visual flash. Prefer the exact cascade amount the
      // panel already computed for this row (this respects fixed_amount markups
      // and cumulative bases); fall back to a flat estimate only when the row is
      // currently inactive and therefore absent from the cascade map.
      let impact = calcMap.get(markup.id);
      if (impact === undefined) {
        if (markup.markup_type === 'fixed') {
          // Decimal-as-string wire value; coerce instead of a typeof guard.
          impact = toNum(markup.fixed_amount);
        } else if (markup.markup_type === 'banded') {
          impact = bandedAmount(directCost, markup.metadata);
        } else if (markup.markup_type === 'escalation') {
          const factor = toNum(markup.escalation_factor ?? 0);
          impact = factor > 0 ? directCost * (factor - 1) : 0;
        } else {
          const pct = markup.percentage ?? 0;
          impact = directCost * (pct / 100);
        }
      }
      const sign = markup.is_active ? '-' : '+';
      updateMutation.mutate(
        { markupId: markup.id, data: { is_active: !markup.is_active } },
        {
          onSuccess: () => {
            if (impact > 0) {
              const formatted = fmt.format(impact);
              const msg = `${sign}${currencySymbol}${formatted} (${markup.name})`;
              // Brief inline feedback via data attribute (consumed by CSS animation)
              const el = document.querySelector(`[data-markup-id="${markup.id}"]`);
              if (el) {
                el.setAttribute('data-delta', msg);
                setTimeout(() => el.removeAttribute('data-delta'), 3000);
              }
            }
          },
        },
      );
    },
    [updateMutation, directCost, calcMap, fmt, currencySymbol],
  );

  const handleStartEdit = useCallback((markupId: string, field: 'name' | 'percentage' | 'category', value: string) => {
    setEditState({ markupId, field, value });
  }, []);

  const handleCommitEdit = useCallback(() => {
    if (!editState) return;
    const { markupId, field, value } = editState;

    if (field === 'name') {
      updateMutation.mutate({ markupId, data: { name: value } });
    } else if (field === 'percentage') {
      const num = parseDecimalInput(value);
      if (num === null || num < 0 || num > 100) {
        // Keep the editor open and explain, rather than silently reverting the
        // typed value with no feedback (a number input's min/max does not block
        // out-of-range typing).
        addToast({
          type: 'error',
          title: t('boq.markup_pct_invalid_title', {
            defaultValue: 'Enter a percentage from 0 to 100',
          }),
          message: t('boq.markup_pct_invalid_msg', {
            defaultValue: 'The markup percentage must be a number between 0 and 100.',
          }),
        });
        return; // leave editState intact so the field stays editable
      }
      updateMutation.mutate({ markupId, data: { percentage: num } });
    } else if (field === 'category') {
      updateMutation.mutate({ markupId, data: { category: value } });
    }
    setEditState(null);
  }, [editState, updateMutation, addToast, t]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') handleCommitEdit();
      if (e.key === 'Escape') setEditState(null);
    },
    [handleCommitEdit],
  );

  const categoryLabel = (cat: string) => {
    const key = `boq.markup_${cat}`;
    return t(key, { defaultValue: cat.charAt(0).toUpperCase() + cat.slice(1) });
  };

  /**
   * What goes in the rate column for a line that has no single percentage.
   *
   * An escalation shows what the index actually did, because that is the
   * number an estimator wants to see and it is not one they can type. A banded
   * line shows how many tranches its card has, since no single figure is
   * honest for it. A fixed line has a rate of nothing at all.
   */
  const rateLabel = (markup: Markup): string => {
    if (markup.markup_type === 'escalation') {
      const factor = toNum(markup.escalation_factor ?? 0);
      if (!(factor > 0)) return t('boq.markup_escalation_unresolved', { defaultValue: 'no index' });
      const movement = (factor - 1) * 100;
      return `${movement >= 0 ? '+' : ''}${fmt.format(movement)}%`;
    }
    if (markup.markup_type === 'banded') {
      const bands = Array.isArray((markup.metadata as Record<string, unknown> | undefined)?.bands)
        ? ((markup.metadata as Record<string, unknown>).bands as unknown[]).length
        : 0;
      return t('boq.markup_band_count', { count: bands, defaultValue: '{{count}} bands' });
    }
    return '—';
  };

  return (
    <div id="boq-markups-panel" className="mt-4 rounded-xl border border-border-light bg-surface-elevated shadow-xs scroll-mt-28">
      {/* Header */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-label={t('boq.markups_title', { defaultValue: 'Markups & Overheads' })}
        className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-surface-secondary/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-content-primary">
            {t('boq.markups_title', { defaultValue: 'Markups & Overheads' })}
          </span>
          {markups.length > 0 && (
            <span className="text-2xs text-content-tertiary bg-surface-secondary rounded-full px-2 py-0.5">
              {markups.length}
            </span>
          )}
        </div>
        <ChevronDown
          size={16}
          className={clsx(
            'text-content-tertiary transition-transform duration-150',
            !isOpen && '-rotate-90',
          )}
        />
      </button>

      {isOpen && (
        <div className="border-t border-border-light">
          {/* Toolbar: Regional template + Add */}
          <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-2.5 bg-surface-secondary/30">
            {/* Regional template dropdown */}
            <div className="relative">
              <button
                onClick={() => setShowRegionMenu(!showRegionMenu)}
                aria-expanded={showRegionMenu}
                aria-haspopup="true"
                aria-label={t('boq.apply_template', { defaultValue: 'Apply Regional Template' })}
                className="flex items-center gap-1.5 text-xs text-content-secondary hover:text-content-primary transition-colors rounded-md px-2 py-1.5 hover:bg-surface-secondary"
              >
                <Globe size={14} className="shrink-0" />
                <span className="whitespace-nowrap">{t('boq.apply_template', { defaultValue: 'Apply Regional Template' })}</span>
                <ChevronDown size={12} className="shrink-0" />
              </button>
              {showRegionMenu && (
                <div className="absolute top-full left-0 mt-1 z-20 min-w-[280px] max-h-[400px] overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-lg py-1">
                  {REGIONS.map((region) => (
                    <button
                      key={region.code}
                      onClick={() => {
                        if (markups.length > 0 && !confirm(t('boq.confirm_replace_markups', { defaultValue: 'This will replace existing markups. Continue?' }))) {
                          setShowRegionMenu(false);
                          return;
                        }
                        applyDefaultsMutation.mutate(region.code);
                      }}
                      disabled={applyDefaultsMutation.isPending}
                      className="w-full text-left px-3 py-2 text-sm hover:bg-surface-secondary transition-colors flex items-center gap-2.5"
                    >
                      <span className="text-base leading-none">{region.flag}</span>
                      <div className="min-w-0">
                        <div className="text-content-primary font-medium truncate">{region.label}</div>
                        {region.standard && (
                          <div className="text-2xs text-content-tertiary">{region.standard}</div>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="flex items-center gap-1">
              <button
                onClick={handleAddMarkup}
                disabled={addMutation.isPending}
                aria-label={t('boq.add_markup', { defaultValue: 'Add Markup' })}
                className="flex items-center gap-1.5 text-xs font-medium text-oe-blue-text hover:text-oe-blue-text transition-colors rounded-md px-2 py-1.5 hover:bg-oe-blue-subtle whitespace-nowrap"
              >
                <Plus size={14} className="shrink-0" />
                <span>{t('boq.add_markup', { defaultValue: 'Add Markup' })}</span>
              </button>
              {sections && sections.length > 0 && (
                <select
                  onChange={(e) => {
                    if (!e.target.value) return;
                    const sec = sections.find((s) => s.id === e.target.value);
                    addMutation.mutate({
                      name: `${t('boq.new_markup', { defaultValue: 'New Markup' })} (${sec?.ordinal ?? ''})`,
                      percentage: 5,
                      category: 'overhead',
                      sort_order: markups.length,
                      scope_position_id: e.target.value,
                    });
                    e.target.value = '';
                  }}
                  className="h-7 rounded-md border border-border bg-surface-primary px-1.5 text-2xs text-content-tertiary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  defaultValue=""
                  title={t('boq.add_scoped_markup', { defaultValue: 'Add markup for section' })}
                >
                  <option value="" disabled>{t('boq.scope_to_section', { defaultValue: 'Scope to section...' })}</option>
                  {sections.map((sec) => (
                    <option key={sec.id} value={sec.id}>{sec.ordinal} {sec.description}</option>
                  ))}
                </select>
              )}
            </div>
          </div>

          {/* Markup table */}
          {markups.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm whitespace-nowrap">
                <thead>
                  <tr className="border-b border-border-light bg-surface-secondary/20 text-content-tertiary text-xs">
                    <th className="w-6 px-2 py-2" />
                    <th className="text-left px-3 py-2 font-medium">{t('boq.markup_name', { defaultValue: 'Name' })}</th>
                    <th className="text-left px-3 py-2 font-medium">{t('boq.markup_category', { defaultValue: 'Category' })}</th>
                    <th className="text-right px-3 py-2 font-medium w-20">{t('boq.markup_percentage', { defaultValue: '%' })}</th>
                    <th className="text-right px-3 py-2 font-medium w-32">{t('boq.markup_amount', { defaultValue: 'Amount' })}</th>
                    <th className="text-center px-3 py-2 font-medium w-16">{t('boq.markup_active', { defaultValue: 'Active' })}</th>
                    <th className="w-10 px-2 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {markups.map((markup) => {
                    const amount = calcMap.get(markup.id) ?? 0;
                    const isEditing = editState?.markupId === markup.id;

                    return (
                      <tr
                        key={markup.id}
                        data-markup-id={markup.id}
                        className={clsx(
                          'group border-b border-border-light last:border-b-0 transition-colors',
                          !markup.is_active && 'opacity-50',
                          'hover:bg-surface-secondary/30',
                        )}
                      >
                        {/* Grip. Rests at `secondary`, the same step the assembly
                            editor settled on: quaternary and tertiary are three
                            hex units apart per channel in both themes, so a grip
                            resting at either one is a grey the user never sees. */}
                        <td
                          data-testid="markup-drag-grip"
                          className="px-2 py-2 text-content-secondary group-hover:text-content-primary transition-colors"
                        >
                          <GripVertical size={14} className="cursor-grab" />
                        </td>

                        {/* Name */}
                        <td className="px-3 py-2">
                          {isEditing && editState.field === 'name' ? (
                            <input
                              autoFocus
                              value={editState.value}
                              onChange={(e) => setEditState({ ...editState, value: e.target.value })}
                              onBlur={handleCommitEdit}
                              onKeyDown={handleKeyDown}
                              className="w-full rounded border border-oe-blue px-1.5 py-0.5 text-sm bg-surface-primary outline-none"
                            />
                          ) : (
                            <span className="flex items-center gap-1.5 min-w-0">
                              <span
                                className="cursor-pointer hover:text-oe-blue transition-colors truncate"
                                onClick={() => handleStartEdit(markup.id, 'name', markup.name)}
                              >
                                {markup.name}
                              </span>
                              {/* A scoped line is an exception to the company
                                  standard and has to read as one. Without this
                                  it is just another row, and an estimator
                                  scanning the stack cannot tell which numbers
                                  apply to the whole bill and which to one
                                  section. */}
                              {markup.scope_position_id && (
                                <span
                                  data-testid="markup-scope-badge"
                                  title={
                                    markup.overrides_id
                                      ? t('boq.markup_override_hint', {
                                          defaultValue: 'Replaces a bill-wide line inside one section',
                                        })
                                      : t('boq.markup_section_only_hint', {
                                          defaultValue: 'Applies to one section only',
                                        })
                                  }
                                  className="shrink-0 rounded-full border border-oe-blue/40 bg-oe-blue/10 px-1.5 py-0.5 text-2xs font-medium text-oe-blue"
                                >
                                  {markup.overrides_id
                                    ? t('boq.markup_override', { defaultValue: 'Override' })
                                    : t('boq.markup_section_only', { defaultValue: 'Section only' })}
                                </span>
                              )}
                            </span>
                          )}
                        </td>

                        {/* Category badge */}
                        <td className="px-3 py-2">
                          {isEditing && editState.field === 'category' ? (
                            <select
                              autoFocus
                              value={editState.value}
                              onChange={(e) => {
                                setEditState({ ...editState, value: e.target.value });
                              }}
                              onBlur={handleCommitEdit}
                              className="rounded border border-oe-blue px-1 py-0.5 text-xs bg-surface-primary outline-none"
                            >
                              {CATEGORIES.map((cat) => (
                                <option key={cat} value={cat}>
                                  {categoryLabel(cat)}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <span
                              className={clsx(
                                'inline-block rounded-full px-2 py-0.5 text-2xs font-medium cursor-pointer',
                                CATEGORY_COLORS[markup.category] ?? CATEGORY_COLORS.other,
                              )}
                              onClick={() => handleStartEdit(markup.id, 'category', markup.category)}
                            >
                              {categoryLabel(markup.category)}
                            </span>
                          )}
                        </td>

                        {/* Percentage. Only a percentage line has one to edit:
                            a fixed line carries an amount, a banded line a rate
                            card, and an escalation line a factor the index
                            decided. Offering an editable percentage on those
                            would take a number the estimator typed and price
                            nothing with it. */}
                        <td className="px-3 py-2 text-right">
                          {isEditing && editState.field === 'percentage' ? (
                            <input
                              autoFocus
                              type="text"
                              inputMode="decimal"
                              value={editState.value}
                              onChange={(e) => setEditState({ ...editState, value: e.target.value })}
                              onBlur={handleCommitEdit}
                              onKeyDown={handleKeyDown}
                              className="w-16 rounded border border-oe-blue px-1.5 py-0.5 text-sm text-right bg-surface-primary outline-none"
                            />
                          ) : markup.markup_type === 'percentage' ? (
                            <span
                              className="cursor-pointer hover:text-oe-blue transition-colors tabular-nums"
                              onClick={() => handleStartEdit(markup.id, 'percentage', String(markup.percentage))}
                            >
                              {`${fmt.format(markup.percentage)}%`}
                            </span>
                          ) : (
                            <span className="tabular-nums text-content-secondary">{rateLabel(markup)}</span>
                          )}
                        </td>

                        {/* Amount */}
                        <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                          {fmtWithCurrency(amount, locale, currencyCode)}
                        </td>

                        {/* Active toggle */}
                        <td className="px-3 py-2 text-center">
                          <button
                            onClick={() => handleToggleActive(markup)}
                            className={clsx(
                              'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
                              markup.is_active ? 'bg-oe-blue' : 'bg-gray-300 dark:bg-gray-600',
                            )}
                            aria-label={t('boq.markup_active', { defaultValue: 'Active' })}
                          >
                            <span
                              className={clsx(
                                'inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform',
                                markup.is_active ? 'translate-x-[18px]' : 'translate-x-[3px]',
                              )}
                            />
                          </button>
                        </td>

                        {/* Delete */}
                        <td className="px-2 py-2 text-center">
                          <button
                            onClick={() => deleteMutation.mutate(markup.id)}
                            disabled={deleteMutation.isPending}
                            className="text-content-quaternary hover:text-red-500 transition-colors"
                            aria-label={t('common.delete', { defaultValue: 'Delete' })}
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="px-5 py-6 text-center text-sm text-content-tertiary">
              {t('boq.no_markups', { defaultValue: 'No markups yet. Add one or apply a regional template.' })}
            </div>
          )}

          {/* Totals summary */}
          {markups.length > 0 && (
            <div className="border-t border-border-light px-5 py-3 bg-surface-secondary/20">
              <div className="flex items-center justify-between gap-4 text-sm">
                <span className="text-content-tertiary whitespace-nowrap">{t('boq.direct_cost', { defaultValue: 'Direct Cost' })}</span>
                <span className="tabular-nums text-content-secondary whitespace-nowrap shrink-0">{fmtWithCurrency(directCost, locale, currencyCode)}</span>
              </div>
              {calculated.map((c) => {
                const m = markups.find((mk) => mk.id === c.id);
                if (!m) return null;
                return (
                  <div key={c.id} className="flex items-center justify-between gap-4 text-sm mt-1">
                    {/* A fixed, banded or escalation line has no single
                        percentage, and printing ``0%`` beside a real amount
                        made the summary contradict the row above it. */}
                    <span className="text-content-tertiary min-w-0 truncate">
                      + {m.name} ({m.markup_type === 'percentage' ? `${fmt.format(m.percentage)}%` : rateLabel(m)})
                    </span>
                    <span className="tabular-nums text-content-secondary whitespace-nowrap shrink-0">{fmtWithCurrency(c.amount, locale, currencyCode)}</span>
                  </div>
                );
              })}
              <div className="flex items-center justify-between gap-4 text-sm font-semibold mt-2 pt-2 border-t border-border-light">
                <span className="text-content-primary whitespace-nowrap">{t('boq.grand_total', { defaultValue: 'Grand Total' })}</span>
                <span className="tabular-nums text-content-primary whitespace-nowrap shrink-0">{fmtWithCurrency(grandTotal, locale, currencyCode)}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
