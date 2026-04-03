import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { boqApi, type Markup, type CreateMarkupData, type UpdateMarkupData } from './api';
import { fmtWithCurrency } from './boqHelpers';
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
  { code: 'DACH', flag: '\ud83c\udde9\ud83c\uddea', label: 'DACH', standard: 'VOB/HOAI' },
  { code: 'UK', flag: '\ud83c\uddec\ud83c\udde7', label: 'United Kingdom', standard: 'NRM/RICS' },
  { code: 'US', flag: '\ud83c\uddfa\ud83c\uddf8', label: 'United States', standard: 'RSMeans/AIA' },
  { code: 'FR', flag: '\ud83c\uddeb\ud83c\uddf7', label: 'France', standard: 'BATIPRIX' },
  { code: 'GULF', flag: '\ud83c\udde6\ud83c\uddea', label: 'Gulf / UAE', standard: 'FIDIC' },
  { code: 'IN', flag: '\ud83c\uddee\ud83c\uddf3', label: 'India', standard: 'CPWD' },
  { code: 'AU', flag: '\ud83c\udde6\ud83c\uddfa', label: 'Australia', standard: 'AIQS' },
  { code: 'JP', flag: '\ud83c\uddef\ud83c\uddf5', label: 'Japan', standard: 'MLIT' },
  { code: 'BR', flag: '\ud83c\udde7\ud83c\uddf7', label: 'Brazil', standard: 'TCU/SINAPI' },
  { code: 'NORDIC', flag: '\ud83c\uddf8\ud83c\uddea', label: 'Scandinavia', standard: 'AB 04' },
  { code: 'RU', flag: '\ud83c\uddf7\ud83c\uddfa', label: 'Russia / CIS', standard: '\u0413\u042d\u0421\u041d' },
  { code: 'CN', flag: '\ud83c\udde8\ud83c\uddf3', label: 'China', standard: '\u5efa\u6807[2013]44' },
  { code: 'KR', flag: '\ud83c\uddf0\ud83c\uddf7', label: 'South Korea', standard: '\uc870\ub2ec\uccad' },
  { code: 'DEFAULT', flag: '\ud83c\udf10', label: 'Generic International', standard: '' },
];

const CATEGORY_COLORS: Record<string, string> = {
  overhead: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  profit: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  tax: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  contingency: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
  insurance: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
  bond: 'bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-300',
  other: 'bg-gray-100 text-gray-700 dark:bg-gray-900/30 dark:text-gray-300',
};

const CATEGORIES = ['overhead', 'profit', 'tax', 'contingency', 'insurance', 'bond', 'other'] as const;

interface MarkupPanelProps {
  boqId: string;
  markups: Markup[];
  directCost: number;
  currencySymbol: string;
  currencyCode: string;
  locale: string;
  fmt: Intl.NumberFormat;
}

interface EditState {
  markupId: string;
  field: 'name' | 'percentage' | 'category';
  value: string;
}

export function MarkupPanel({ boqId, markups, directCost, currencySymbol, currencyCode, locale, fmt }: MarkupPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [isOpen, setIsOpen] = useState(true);
  const [editState, setEditState] = useState<EditState | null>(null);
  const [showRegionMenu, setShowRegionMenu] = useState(false);

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
  });

  const updateMutation = useMutation({
    mutationFn: ({ markupId, data }: { markupId: string; data: UpdateMarkupData }) =>
      boqApi.updateMarkup(boqId, markupId, data),
    onSuccess: () => invalidate(),
  });

  const deleteMutation = useMutation({
    mutationFn: (markupId: string) => boqApi.deleteMarkup(boqId, markupId),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('boq.markup_deleted', { defaultValue: 'Markup deleted' }) });
    },
  });

  const applyDefaultsMutation = useMutation({
    mutationFn: (region: string) => boqApi.applyDefaults(boqId, region),
    onSuccess: () => {
      invalidate();
      setShowRegionMenu(false);
      addToast({ type: 'success', title: t('boq.template_applied', { defaultValue: 'Regional template applied' }) });
    },
  });

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
      // Calculate impact for visual feedback
      const pct = markup.percentage ?? 0;
      const impact = directCost * (pct / 100);
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
    [updateMutation, directCost, fmt, currencySymbol],
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
      const num = parseFloat(value);
      if (!isNaN(num) && num >= 0 && num <= 100) {
        updateMutation.mutate({ markupId, data: { percentage: num } });
      }
    } else if (field === 'category') {
      updateMutation.mutate({ markupId, data: { category: value } });
    }
    setEditState(null);
  }, [editState, updateMutation]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') handleCommitEdit();
      if (e.key === 'Escape') setEditState(null);
    },
    [handleCommitEdit],
  );

  // Cascading calculation for preview
  let running = directCost;
  const calculated = markups
    .filter((m) => m.is_active !== false)
    .map((m) => {
      let amount = 0;
      if (m.markup_type === 'fixed') {
        amount = m.fixed_amount ?? 0;
      } else if (m.apply_to === 'cumulative') {
        amount = running * (m.percentage / 100);
      } else {
        amount = directCost * (m.percentage / 100);
      }
      running += amount;
      return { id: m.id, amount };
    });

  const calcMap = new Map(calculated.map((c) => [c.id, c.amount]));
  const netTotal = running;

  const categoryLabel = (cat: string) => {
    const key = `boq.markup_${cat}`;
    return t(key, { defaultValue: cat.charAt(0).toUpperCase() + cat.slice(1) });
  };

  return (
    <div className="mt-4 rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden">
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

            <button
              onClick={handleAddMarkup}
              disabled={addMutation.isPending}
              aria-label={t('boq.add_markup', { defaultValue: 'Add Markup' })}
              className="flex items-center gap-1.5 text-xs font-medium text-oe-blue hover:text-oe-blue-dark transition-colors rounded-md px-2 py-1.5 hover:bg-oe-blue-subtle whitespace-nowrap"
            >
              <Plus size={14} className="shrink-0" />
              <span>{t('boq.add_markup', { defaultValue: 'Add Markup' })}</span>
            </button>
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
                          'border-b border-border-light last:border-b-0 transition-colors',
                          !markup.is_active && 'opacity-50',
                          'hover:bg-surface-secondary/30',
                        )}
                      >
                        {/* Grip */}
                        <td className="px-2 py-2 text-content-quaternary">
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
                            <span
                              className="cursor-pointer hover:text-oe-blue transition-colors"
                              onClick={() => handleStartEdit(markup.id, 'name', markup.name)}
                            >
                              {markup.name}
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

                        {/* Percentage */}
                        <td className="px-3 py-2 text-right">
                          {isEditing && editState.field === 'percentage' ? (
                            <input
                              autoFocus
                              type="number"
                              min={0}
                              max={100}
                              step={0.1}
                              value={editState.value}
                              onChange={(e) => setEditState({ ...editState, value: e.target.value })}
                              onBlur={handleCommitEdit}
                              onKeyDown={handleKeyDown}
                              className="w-16 rounded border border-oe-blue px-1.5 py-0.5 text-sm text-right bg-surface-primary outline-none"
                            />
                          ) : (
                            <span
                              className="cursor-pointer hover:text-oe-blue transition-colors tabular-nums"
                              onClick={() => handleStartEdit(markup.id, 'percentage', String(markup.percentage))}
                            >
                              {markup.markup_type === 'fixed' ? '\u2014' : `${fmt.format(markup.percentage)}%`}
                            </span>
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
                    <span className="text-content-tertiary min-w-0 truncate">+ {m.name} ({fmt.format(m.percentage)}%)</span>
                    <span className="tabular-nums text-content-secondary whitespace-nowrap shrink-0">{fmtWithCurrency(c.amount, locale, currencyCode)}</span>
                  </div>
                );
              })}
              <div className="flex items-center justify-between gap-4 text-sm font-semibold mt-2 pt-2 border-t border-border-light">
                <span className="text-content-primary whitespace-nowrap">{t('boq.net_total', { defaultValue: 'Net Total' })}</span>
                <span className="tabular-nums text-content-primary whitespace-nowrap shrink-0">{fmtWithCurrency(netTotal, locale, currencyCode)}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
