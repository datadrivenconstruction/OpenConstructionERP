import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, BarChart3, Loader2, Inbox } from 'lucide-react';
import { boqApi, type SensitivityItem } from './api';

/* ── Helpers ─────────────────────────────────────────────────────────── */

function createSCFormatter(locale: string) {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtCompact(n: number, fmt: Intl.NumberFormat): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) {
    return `${n < 0 ? '-' : ''}${fmt.format(abs / 1_000_000)}M`;
  }
  if (abs >= 10_000) {
    return `${n < 0 ? '-' : ''}${fmt.format(abs / 1_000)}K`;
  }
  return fmt.format(n);
}

/* ── Component ───────────────────────────────────────────────────────── */

export function SensitivityChart({ boqId, locale = 'de-DE' }: { boqId: string; locale?: string }) {
  const { t } = useTranslation();
  const fmt = useMemo(() => createSCFormatter(locale), [locale]);
  const [collapsed, setCollapsed] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['boq-sensitivity', boqId],
    queryFn: () => boqApi.getSensitivity(boqId),
    enabled: !!boqId,
  });

  const items: SensitivityItem[] = data?.items ?? [];
  const baseTotal = data?.base_total ?? 0;
  const variationPct = data?.variation_pct ?? 10;

  // Max absolute impact for scaling bars
  const maxImpact = useMemo(() => {
    if (items.length === 0) return 1;
    return Math.max(...items.map((it) => Math.abs(it.impact_high)));
  }, [items]);

  return (
    <div className="mt-6 rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden transition-all">
      {/* ── Toggle header ──────────────────────────────────────────── */}
      <button
        onClick={() => setCollapsed((prev) => !prev)}
        aria-expanded={!collapsed}
        aria-label={t('boq.sensitivity_title', { defaultValue: 'Sensitivity Analysis' })}
        className="flex w-full items-center justify-between px-5 py-3.5 hover:bg-surface-secondary/50 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <BarChart3 size={16} className="text-content-tertiary" strokeWidth={1.75} />
          <span className="text-sm font-semibold text-content-primary">
            {t('boq.sensitivity_title', { defaultValue: 'Sensitivity Analysis' })}
          </span>
          {items.length > 0 && (
            <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-surface-secondary px-1.5 text-2xs font-medium text-content-secondary tabular-nums">
              {items.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-content-tertiary">
          {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        </div>
      </button>

      {/* ── Content ────────────────────────────────────────────────── */}
      {!collapsed && (
        <div className="border-t border-border-light">
          {isLoading ? (
            <div className="px-5 py-8 text-center">
              <Loader2 size={20} className="mx-auto mb-2 animate-spin text-oe-blue" />
              <p className="text-xs text-content-tertiary">{t('common.loading')}</p>
            </div>
          ) : isError ? (
            <div className="px-5 py-8 text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-error/10 mx-auto mb-2">
                <Inbox size={18} className="text-semantic-error" />
              </div>
              <p className="text-xs text-content-secondary">
                {t('boq.sensitivity_error', { defaultValue: 'Failed to load sensitivity analysis. Please try again.' })}
              </p>
            </div>
          ) : items.length === 0 ? (
            <div className="px-5 pb-5 pt-1">
              <div className="flex flex-col items-center gap-2 py-6 text-center">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-secondary">
                  <Inbox size={18} className="text-content-tertiary" />
                </div>
                <p className="text-xs text-content-tertiary">
                  {t('boq.sensitivity_empty', {
                    defaultValue: 'Add positions with costs to see the sensitivity analysis.',
                  })}
                </p>
              </div>
            </div>
          ) : (
            <>
              {/* Header info */}
              <div className="px-5 py-3 flex items-center gap-4 text-xs text-content-secondary bg-surface-secondary/30 border-b border-border-light">
                <span>
                  {t('boq.sensitivity_base_total', { defaultValue: 'Base Total' })}:{' '}
                  <span className="font-semibold text-content-primary tabular-nums">
                    {fmtCompact(baseTotal, fmt)}
                  </span>
                </span>
                <span className="text-content-quaternary">|</span>
                <span>
                  {t('boq.sensitivity_variation', { defaultValue: 'Variation' })}:{' '}
                  <span className="font-semibold text-content-primary">
                    +/- {variationPct}%
                  </span>
                </span>
              </div>

              {/* Tornado chart */}
              <div className="px-5 py-4">
                <div className="space-y-1.5">
                  {items.map((item, idx) => {
                    const barWidthPct =
                      maxImpact > 0 ? (Math.abs(item.impact_high) / maxImpact) * 100 : 0;

                    return (
                      <div key={`${item.ordinal}-${idx}`} className="group">
                        <div className="flex items-center gap-3">
                          {/* Label */}
                          <div className="w-[220px] shrink-0 text-right pr-2">
                            <span className="text-2xs font-mono text-content-tertiary">
                              {item.ordinal}
                            </span>{' '}
                            <span
                              className="text-xs text-content-secondary truncate inline-block max-w-[160px] align-bottom"
                              title={item.description}
                            >
                              {item.description || '-'}
                            </span>
                          </div>

                          {/* Bars container: left (savings) + right (overrun) */}
                          <div className="flex-1 flex items-center h-6">
                            {/* Left bar (savings / green) */}
                            <div className="flex-1 flex justify-end">
                              <div
                                className="h-5 rounded-l-sm bg-emerald-500/70 group-hover:bg-emerald-500 transition-colors relative"
                                style={{ width: `${barWidthPct}%`, minWidth: barWidthPct > 0 ? '2px' : '0' }}
                              >
                                {barWidthPct > 15 && (
                                  <span className="absolute inset-0 flex items-center justify-center text-[10px] font-medium text-white tabular-nums">
                                    {fmtCompact(item.impact_low, fmt)}
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* Center line */}
                            <div className="w-px h-7 bg-border shrink-0" />

                            {/* Right bar (overrun / red) */}
                            <div className="flex-1 flex justify-start">
                              <div
                                className="h-5 rounded-r-sm bg-rose-500/70 group-hover:bg-rose-500 transition-colors relative"
                                style={{ width: `${barWidthPct}%`, minWidth: barWidthPct > 0 ? '2px' : '0' }}
                              >
                                {barWidthPct > 15 && (
                                  <span className="absolute inset-0 flex items-center justify-center text-[10px] font-medium text-white tabular-nums">
                                    +{fmtCompact(item.impact_high, fmt)}
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>

                          {/* Share percentage */}
                          <div className="w-14 shrink-0 text-right">
                            <span className="text-2xs font-medium text-content-tertiary tabular-nums">
                              {fmt.format(item.share_pct)}%
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Legend */}
                <div className="flex items-center justify-center gap-6 mt-4 pt-3 border-t border-border-light">
                  <div className="flex items-center gap-1.5">
                    <div className="h-2.5 w-5 rounded-sm bg-emerald-500/70" />
                    <span className="text-2xs text-content-tertiary">
                      {t('boq.sensitivity_savings', { defaultValue: 'Cost decrease' })}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <div className="h-2.5 w-5 rounded-sm bg-rose-500/70" />
                    <span className="text-2xs text-content-tertiary">
                      {t('boq.sensitivity_overrun', { defaultValue: 'Cost increase' })}
                    </span>
                  </div>
                </div>
              </div>

              {/* Detail table */}
              <div className="border-t border-border-light overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-surface-tertiary/50">
                      <th className="px-4 py-2 text-left font-medium text-content-secondary">
                        {t('boq.ordinal')}
                      </th>
                      <th className="px-4 py-2 text-left font-medium text-content-secondary">
                        {t('boq.description')}
                      </th>
                      <th className="px-4 py-2 text-right font-medium text-content-secondary">
                        {t('boq.total')}
                      </th>
                      <th className="px-4 py-2 text-right font-medium text-content-secondary">
                        {t('boq.sensitivity_share', { defaultValue: 'Share' })}
                      </th>
                      <th className="px-4 py-2 text-right font-medium text-content-secondary">
                        {t('boq.sensitivity_impact_low', { defaultValue: 'Impact (-)' })}
                      </th>
                      <th className="px-4 py-2 text-right font-medium text-content-secondary">
                        {t('boq.sensitivity_impact_high', { defaultValue: 'Impact (+)' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-light">
                    {items.map((item, idx) => (
                      <tr
                        key={`${item.ordinal}-${idx}`}
                        className={`hover:bg-surface-secondary/30 transition-colors ${
                          idx % 2 === 0 ? 'bg-surface-primary/50' : ''
                        }`}
                      >
                        <td className="px-4 py-2 font-mono text-content-tertiary">
                          {item.ordinal}
                        </td>
                        <td className="px-4 py-2 text-content-primary max-w-[240px] truncate" title={item.description}>
                          {item.description || '-'}
                        </td>
                        <td className="px-4 py-2 text-right tabular-nums text-content-primary font-medium">
                          {fmtCompact(item.total, fmt)}
                        </td>
                        <td className="px-4 py-2 text-right tabular-nums text-content-secondary">
                          {fmt.format(item.share_pct)}%
                        </td>
                        <td className="px-4 py-2 text-right tabular-nums text-emerald-600 font-medium">
                          {fmtCompact(item.impact_low, fmt)}
                        </td>
                        <td className="px-4 py-2 text-right tabular-nums text-rose-600 font-medium">
                          +{fmtCompact(item.impact_high, fmt)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
