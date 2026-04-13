/**
 * RenumberDialog — modern multi-option dialog for renumbering BOQ positions.
 *
 * Replaces the old `window.confirm` with a proper modal that:
 *   1. Lets the user pick one of 4 numbering schemes (gap10/gap100/sequential/dotted)
 *   2. Toggles zero-padding (`01` vs `1`)
 *   3. Shows a live "before → after" preview using the first 3 real positions
 *   4. Has a single primary action button with loading state
 *   5. Closes on Escape, on backdrop click, and on ✕
 *
 * The preview is purely client-side — it does NOT call the backend until
 * the user clicks Apply. Each scheme has a `previewBuilder` function that
 * walks the same simplified hierarchy the backend uses.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { LucideIcon } from 'lucide-react';
import { X, Hash, Check, ListOrdered, Layers, Minus, AlertTriangle } from 'lucide-react';

export type RenumberScheme = 'gap10' | 'gap100' | 'sequential' | 'dotted';

interface RenumberDialogProps {
  open: boolean;
  onClose: () => void;
  onApply: (scheme: RenumberScheme, pad: boolean) => void;
  isApplying: boolean;
  /** Real BOQ positions used for the preview. We only need ordinal + parent_id + unit. */
  samplePositions: Array<{ ordinal: string; description?: string; unit?: string; parent_id?: string | null }>;
}

interface SchemeInfo {
  id: RenumberScheme;
  icon: LucideIcon;
  titleKey: string;
  titleDefault: string;
  descKey: string;
  descDefault: string;
  example: string[];
  recommended?: boolean;
}

const SCHEMES: SchemeInfo[] = [
  {
    id: 'gap10',
    icon: Layers,
    titleKey: 'boq.renumber_scheme_gap10',
    titleDefault: 'Gap of 10',
    descKey: 'boq.renumber_scheme_gap10_desc',
    descDefault: 'Leaves room to insert positions like 01.15 between 01.10 and 01.20 later. Standard German tender output.',
    example: ['01', '01.10', '01.20', '01.30', '02', '02.10'],
    recommended: true,
  },
  {
    id: 'gap100',
    icon: Hash,
    titleKey: 'boq.renumber_scheme_gap100',
    titleDefault: 'Gap of 100',
    descKey: 'boq.renumber_scheme_gap100_desc',
    descDefault: 'Even more headroom for very large BOQs that may grow significantly post-tender.',
    example: ['01', '01.100', '01.200', '01.300', '02', '02.100'],
  },
  {
    id: 'sequential',
    icon: ListOrdered,
    titleKey: 'boq.renumber_scheme_sequential',
    titleDefault: 'Sequential',
    descKey: 'boq.renumber_scheme_sequential_desc',
    descDefault: 'Compact, traditional numbering. Best for fixed-scope BOQs that won\'t get extra positions later.',
    example: ['01', '01.01', '01.02', '01.03', '02', '02.01'],
  },
  {
    id: 'dotted',
    icon: Minus,
    titleKey: 'boq.renumber_scheme_dotted',
    titleDefault: 'Short decimal',
    descKey: 'boq.renumber_scheme_dotted_desc',
    descDefault: 'Short-form decimal numbering common in NRM-style measurement.',
    example: ['1', '1.1', '1.2', '1.3', '2', '2.1'],
  },
];

/* ── Client-side preview generator ───────────────────────────────── */

function buildPreview(
  positions: RenumberDialogProps['samplePositions'],
  scheme: RenumberScheme,
  pad: boolean,
  limit: number,
): Array<{ before: string; after: string; description: string }> {
  if (!positions.length) return [];

  const stepPerScheme: Record<RenumberScheme, number> = {
    gap10: 10,
    gap100: 100,
    sequential: 1,
    dotted: 1,
  };
  const step = stepPerScheme[scheme];
  const useDotted = scheme === 'dotted';

  const fmtSection = (idx: number) => (pad ? String(idx).padStart(2, '0') : String(idx));
  const fmtLeaf = (parentOrd: string, value: number) => {
    if (useDotted) return `${parentOrd}.${value}`;
    const width = scheme === 'gap100' ? 3 : 2;
    return `${parentOrd}.${String(value).padStart(width, '0')}`;
  };

  // Walk in the same parent-children order the backend uses.
  const byParent = new Map<string | null, typeof positions>();
  for (const p of positions) {
    const key = p.parent_id ?? null;
    const arr = byParent.get(key) ?? [];
    arr.push(p);
    byParent.set(key, arr);
  }

  const isSection = (p: (typeof positions)[number]) => {
    const u = (p.unit ?? '').trim().toLowerCase();
    return u === '' || u === 'section';
  };

  const result: Array<{ before: string; after: string; description: string }> = [];
  let sectionIdx = 0;

  const walk = (parentKey: string | null, parentOrd: string | null) => {
    if (result.length >= limit) return;
    const children = byParent.get(parentKey) ?? [];
    let leafIdx = 0;
    for (const child of children) {
      if (result.length >= limit) return;
      let newOrd: string;
      if (isSection(child)) {
        if (parentKey === null) {
          sectionIdx += 1;
          newOrd = fmtSection(sectionIdx);
        } else {
          leafIdx += 1;
          newOrd = fmtLeaf(parentOrd ?? '', leafIdx * step);
        }
      } else {
        leafIdx += 1;
        if (parentOrd) {
          newOrd = fmtLeaf(parentOrd, leafIdx * step);
        } else {
          // Top-level leaf without a section parent
          newOrd = useDotted
            ? String(leafIdx * step)
            : String(leafIdx * step).padStart(scheme === 'gap10' || scheme === 'gap100' ? 4 : 2, '0');
        }
      }
      result.push({
        before: child.ordinal || '—',
        after: newOrd,
        description: child.description?.slice(0, 60) ?? '',
      });
      walk(String((child as { id?: string }).id ?? leafIdx), newOrd);
    }
  };

  walk(null, null);
  return result;
}

/* ── Component ───────────────────────────────────────────────────── */

export function RenumberDialog({
  open,
  onClose,
  onApply,
  isApplying,
  samplePositions,
}: RenumberDialogProps) {
  const { t } = useTranslation();
  const [scheme, setScheme] = useState<RenumberScheme>('gap10');
  const [pad, setPad] = useState(true);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isApplying) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose, isApplying]);

  const preview = useMemo(
    () => buildPreview(samplePositions, scheme, pad, 5),
    [samplePositions, scheme, pad],
  );

  const handleApply = useCallback(() => {
    onApply(scheme, pad);
  }, [onApply, scheme, pad]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-card-in"
      onClick={() => !isApplying && onClose()}
      role="dialog"
      aria-modal="true"
      aria-labelledby="renumber-dialog-title"
    >
      <div
        className="relative w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl bg-surface-elevated border border-border shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="relative px-5 py-4 bg-gradient-to-br from-sky-50 via-blue-50 to-cyan-50 dark:from-sky-950/50 dark:via-blue-950/40 dark:to-cyan-950/30 border-b border-border">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-blue-600 text-white shadow-md shadow-blue-500/40">
              <ListOrdered size={18} strokeWidth={2.5} />
            </div>
            <div className="flex-1 min-w-0">
              <h2
                id="renumber-dialog-title"
                className="text-base font-bold text-content-primary"
              >
                {t('boq.renumber_dialog_title', { defaultValue: 'Renumber positions' })}
              </h2>
              <p className="text-xs text-content-secondary mt-0.5">
                {t('boq.renumber_dialog_subtitle', {
                  defaultValue: 'Pick a numbering scheme. The current order is preserved — only ordinals are rewritten.',
                })}
              </p>
            </div>
            <button
              onClick={onClose}
              disabled={isApplying}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors disabled:opacity-50"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {/* Scheme cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            {SCHEMES.map((s) => {
              const Icon = s.icon;
              const isSelected = scheme === s.id;
              return (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setScheme(s.id)}
                  disabled={isApplying}
                  className={`relative text-left rounded-xl border-2 px-3 py-3 transition-all disabled:opacity-50 ${
                    isSelected
                      ? 'border-sky-500 bg-sky-50/60 dark:bg-sky-950/40 shadow-sm shadow-sky-500/20'
                      : 'border-border bg-surface-base hover:border-sky-300 dark:hover:border-sky-700 hover:bg-surface-secondary/40'
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    <div
                      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${
                        isSelected
                          ? 'bg-gradient-to-br from-sky-500 to-blue-600 text-white shadow-sm'
                          : 'bg-surface-secondary text-content-tertiary'
                      }`}
                    >
                      <Icon size={14} strokeWidth={2.5} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`text-sm font-semibold ${
                            isSelected
                              ? 'text-blue-900 dark:text-sky-100'
                              : 'text-content-primary'
                          }`}
                        >
                          {t(s.titleKey, { defaultValue: s.titleDefault })}
                        </span>
                        {s.recommended && (
                          <span className="text-[9px] font-bold uppercase tracking-wider text-sky-600 dark:text-sky-400 bg-sky-500/15 px-1.5 py-0.5 rounded">
                            {t('common.recommended', { defaultValue: 'Recommended' })}
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-content-secondary leading-snug mt-0.5 line-clamp-2">
                        {t(s.descKey, { defaultValue: s.descDefault })}
                      </p>
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {s.example.slice(0, 4).map((ex, i) => (
                          <span
                            key={i}
                            className="text-[10px] tabular-nums font-mono text-content-secondary bg-surface-secondary px-1.5 py-0.5 rounded"
                          >
                            {ex}
                          </span>
                        ))}
                      </div>
                    </div>
                    {isSelected && (
                      <div className="absolute top-2 right-2 flex h-5 w-5 items-center justify-center rounded-full bg-sky-500 text-white shadow-sm">
                        <Check size={11} strokeWidth={3} />
                      </div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Pad toggle */}
          <label className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface-base px-3 py-2.5 cursor-pointer hover:bg-surface-secondary/40 transition-colors">
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-content-primary">
                {t('boq.renumber_pad', { defaultValue: 'Zero-pad section numbers' })}
              </div>
              <div className="text-[11px] text-content-tertiary">
                {pad
                  ? t('boq.renumber_pad_on', { defaultValue: 'Sections will be 01, 02, 03 (two-digit padded)' })
                  : t('boq.renumber_pad_off', { defaultValue: 'Sections will be 1, 2, 3 (no padding)' })}
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={pad}
              onClick={() => setPad(!pad)}
              disabled={isApplying}
              className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${
                pad ? 'bg-sky-500' : 'bg-surface-secondary border border-border'
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow-sm transition-transform ${
                  pad ? 'translate-x-5' : 'translate-x-0.5'
                }`}
              />
            </button>
          </label>

          {/* Live preview */}
          <div className="rounded-xl border border-border bg-surface-base overflow-hidden">
            <div className="px-3 py-2 border-b border-border bg-surface-secondary/40">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
                {t('boq.renumber_preview', { defaultValue: 'Preview (first 5 positions)' })}
              </div>
            </div>
            {preview.length === 0 ? (
              <div className="px-3 py-4 text-xs text-content-tertiary text-center">
                {t('boq.renumber_no_preview', { defaultValue: 'No positions to preview yet.' })}
              </div>
            ) : (
              <div className="divide-y divide-border">
                {preview.map((row) => (
                  <div
                    key={`${row.before}-${row.after}`}
                    className="grid grid-cols-[80px_20px_80px_1fr] items-center gap-2 px-3 py-1.5 text-[11px]"
                  >
                    <span className="font-mono tabular-nums text-content-tertiary line-through">
                      {row.before}
                    </span>
                    <span className="text-content-tertiary text-center">→</span>
                    <span className="font-mono tabular-nums font-semibold text-blue-600 dark:text-sky-300">
                      {row.after}
                    </span>
                    <span className="text-content-secondary truncate">{row.description}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Warning */}
          <div className="flex items-start gap-2 rounded-lg border border-amber-300/50 bg-amber-50/50 dark:border-amber-700/40 dark:bg-amber-950/20 px-3 py-2">
            <AlertTriangle
              size={14}
              className="shrink-0 mt-0.5 text-amber-600 dark:text-amber-400"
            />
            <p className="text-[11px] leading-snug text-amber-800/90 dark:text-amber-200/90">
              {t('boq.renumber_warning', {
                defaultValue:
                  'This overwrites any manually edited position numbers. The current display order is preserved — only ordinals change.',
              })}
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 bg-surface-secondary/40 border-t border-border flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            disabled={isApplying}
            className="px-3 py-1.5 text-xs font-medium text-content-secondary hover:text-content-primary hover:bg-surface-secondary rounded-md transition-colors disabled:opacity-50"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            onClick={handleApply}
            disabled={isApplying || preview.length === 0}
            className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold text-white bg-gradient-to-br from-sky-500 to-blue-600 hover:from-sky-600 hover:to-blue-700 rounded-md shadow-sm shadow-blue-500/30 ring-1 ring-blue-500/20 transition-all hover:shadow-blue-500/40 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isApplying ? (
              <>
                <span className="h-3 w-3 rounded-full border-2 border-white/50 border-t-white animate-spin" />
                {t('boq.renumbering', { defaultValue: 'Renumbering…' })}
              </>
            ) : (
              <>
                <Check size={12} strokeWidth={3} />
                {t('boq.renumber_apply', { defaultValue: 'Apply renumbering' })}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
