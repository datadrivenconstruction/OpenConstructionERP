// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SystemChooser - pick the formwork system, with the consequences on screen.
 *
 * Choosing the system is the decision the formwork module exists to support:
 * the same wall in a different system has a different rate and a different
 * cycle. Until this component the choice was a bare `<select>` at the bottom of
 * a table showing nothing but a name, so there was no way to tell which system
 * to pick or what picking it would do.
 *
 * The shape of the fix is three visible steps, left to right, top to bottom:
 *
 *   1. What are you forming? A wall, a slab, a column, a beam - this filters
 *      the catalogue to systems that form that thing.
 *   2. How much of it, over how many uses? Contact area, reuses, waste.
 *   3. Which system? Every candidate priced side by side against the SAME
 *      assumptions, cheapest first, with the ones that cannot survive the
 *      assumed reuse count flagged rather than quietly recommended.
 *
 * All arithmetic is server-side (`POST /systems/compare`). Nothing here
 * computes a rate: the numbers shown while choosing must be the numbers that
 * land in the bill, and the only way to guarantee that is for one function to
 * produce both. Values arrive as Decimal-as-string and are parsed to numbers
 * only to be formatted for display.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Check, Layers, Ruler, Sparkles, TrendingDown } from 'lucide-react';

import { Badge, Button, Card, EmptyState, Input, SkeletonTable } from '@/shared/ui';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import {
  compareSystems,
  type FormworkCompareCandidate,
  type FormworkMaterial,
  type FormworkRateBasis,
  type FormworkSystemType,
} from './api';

/* ── Vocabulary ────────────────────────────────────────────────────────── */

/**
 * Every system type the catalogue can hold, in the order an estimator walks a
 * concrete frame: the vertical work first, then what carries the slab.
 *
 * Generic engineering categories only. Formwork is dominated by a handful of
 * manufacturers and this platform names none of them - a system is described
 * by what it IS. `beam` and `props` are deliberately separate: `beam` is the
 * mould around a downstand beam, `props` is the falsework standing under a
 * slab holding it up.
 */
export const SYSTEM_TYPE_ORDER: FormworkSystemType[] = [
  'wall',
  'column',
  'beam',
  'slab',
  'table',
  'props',
  'climbing',
  'tunnel',
  'foundation',
  'custom',
];

/** English labels for the system types, for `t(key, { defaultValue })`. */
export const SYSTEM_TYPE_LABELS: Record<FormworkSystemType, string> = {
  wall: 'Wall panel system',
  column: 'Column form',
  beam: 'Beam form',
  slab: 'Slab deck panel',
  table: 'Table form',
  props: 'Slab props and beams',
  climbing: 'Climbing formwork',
  tunnel: 'Tunnel form',
  foundation: 'Foundation form',
  custom: 'Site-made formwork',
};

/** English labels for the panel materials. */
export const MATERIAL_LABELS: Record<FormworkMaterial, string> = {
  plywood: 'Plywood',
  steel: 'Steel',
  aluminium: 'Aluminium',
  composite: 'Composite',
  timber: 'Timber',
  other: 'Other',
};

/** English labels for the rate bases. */
export const RATE_BASIS_LABELS: Record<FormworkRateBasis, string> = {
  purchase: 'Bought',
  hire_per_use: 'Hired per use',
  subcontract: 'Supply and fix',
};

/* ── Debounce ──────────────────────────────────────────────────────────── */

/**
 * A value that settles before it is used as a query key.
 *
 * The comparison inputs are free-typed numbers, so keying the request off them
 * directly sends one request per keystroke: typing "1200" asks the server to
 * price the whole catalogue at 1, 12, 120 and 1200. React Query would cancel
 * the stale ones, but the requests are still made and the grid flickers
 * through three wrong answers on the way to the right one.
 */
function useSettled<T>(value: T, delayMs = 350): T {
  const [settled, setSettled] = useState(value);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer.current);
  }, [value, delayMs]);

  return settled;
}

/* ── Formatting ────────────────────────────────────────────────────────── */

/** Decimal-as-string to a locale-formatted number, for display only. */
function fmt(value: string | number, locale: string, digits = 2): string {
  const n = typeof value === 'number' ? value : Number.parseFloat(value || '0');
  if (!Number.isFinite(n)) return String(value);
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);
}

/* ── Candidate card ────────────────────────────────────────────────────── */

interface CandidateCardProps {
  candidate: FormworkCompareCandidate;
  selected: boolean;
  isBestBuildable: boolean;
  locale: string;
  onSelect: () => void;
}

/**
 * One system, priced, as a clickable card.
 *
 * The card leads with the unit rate rather than the name, because the rate is
 * what is being compared; the name only says which thing carries it. The rate
 * build-up underneath is the split a quantity surveyor checks first: how much
 * of this is panels amortising away, and how much is labour paid every time.
 */
function CandidateCard({
  candidate,
  selected,
  isBestBuildable,
  locale,
  onSelect,
}: CandidateCardProps) {
  const { t } = useTranslation();
  const blocked = candidate.exceeds_reuses_max;

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={[
        'text-left rounded-xl border p-3 transition-colors w-full',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
        selected
          ? 'border-oe-blue ring-2 ring-oe-blue bg-oe-blue-subtle'
          : 'border-border bg-surface-primary hover:border-oe-blue',
        // Not hidden and not disabled: seeing WHY a system is wrong is the
        // comparison. It is only de-emphasised so it cannot be mistaken for
        // a recommendation.
        blocked && !selected ? 'opacity-70' : '',
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-content-primary truncate">
            {candidate.name}
          </div>
          <div className="text-xs text-content-secondary mt-0.5">
            {t(`formwork.material.${candidate.material}`, {
              defaultValue: candidate.material,
            })}
            {' · '}
            {t(`formwork.basis.${candidate.rate_basis}`, {
              defaultValue: RATE_BASIS_LABELS[candidate.rate_basis] ?? candidate.rate_basis,
            })}
          </div>
        </div>
        {selected && <Check size={16} className="text-oe-blue shrink-0 mt-0.5" />}
      </div>

      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-lg font-semibold text-content-primary tabular-nums">
          {fmt(candidate.unit_cost, locale)}
        </span>
        <span className="text-xs text-content-secondary">
          {candidate.currency
            ? t('formwork.chooser.perM2WithCurrency', {
                defaultValue: '{{currency}} per m2',
                currency: candidate.currency,
              })
            : t('formwork.chooser.perM2', { defaultValue: 'per m2' })}
        </span>
      </div>

      {/* The rate build-up: what amortises against what is paid every use. */}
      <div className="mt-1 text-xs text-content-secondary tabular-nums">
        {t('formwork.chooser.buildUp', {
          defaultValue: '{{panels}} panels + {{labour}} erect and strike',
          panels: fmt(candidate.material_unit_cost, locale),
          labour: fmt(candidate.labour_unit_cost, locale),
        })}
      </div>

      <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-xs text-content-secondary">
        <span>
          {t('formwork.chooser.cycle', {
            defaultValue: 'Cycle {{days}} d',
            days: fmt(candidate.cycle_days, locale, 1),
          })}
        </span>
        <span>
          {t('formwork.chooser.strip', {
            defaultValue: 'Strike after {{days}} d',
            days: candidate.strip_time_days,
          })}
        </span>
        <span className="col-span-2">
          {candidate.typical_reuses != null
            ? t('formwork.chooser.reusesTypical', {
                defaultValue: 'Usually {{typical}} uses, max {{max}}',
                typical: candidate.typical_reuses,
                max: candidate.reuses_max,
              })
            : t('formwork.chooser.reusesMaxOnly', {
                defaultValue: 'Max {{max}} uses',
                max: candidate.reuses_max,
              })}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge variant="neutral" size="sm">
          {t('formwork.chooser.totalForArea', {
            defaultValue: 'Total {{total}}',
            total: fmt(candidate.total, locale),
          })}
        </Badge>
        {isBestBuildable && (
          <Badge variant="success" size="sm">
            <TrendingDown size={11} className="mr-1 inline" />
            {t('formwork.chooser.bestRate', { defaultValue: 'Best rate' })}
          </Badge>
        )}
        {blocked && (
          <Badge variant="error" size="sm">
            <AlertTriangle size={11} className="mr-1 inline" />
            {t('formwork.chooser.overReuseLimit', {
              defaultValue: 'Only survives {{max}} uses',
              max: candidate.reuses_max,
            })}
          </Badge>
        )}
        {!blocked && candidate.above_typical_reuses && (
          <Badge variant="warning" size="sm">
            {t('formwork.chooser.aboveTypical', { defaultValue: 'Optimistic' })}
          </Badge>
        )}
      </div>
    </button>
  );
}

/* ── Chooser ───────────────────────────────────────────────────────────── */

export interface SystemChooserProps {
  /** True when the catalogue is empty, so the chooser can say so usefully. */
  catalogueEmpty: boolean;
  /** Offer to install the starter catalogue. */
  onSeedCatalogue: () => void;
  seeding: boolean;
  /** Add the chosen system to the project on the stated assumptions. */
  onAdd: (choice: {
    systemId: string;
    areaM2: string;
    reuseCount: number;
    wastePct: string;
  }) => void;
  adding: boolean;
}

/**
 * The visible answer to "which system, and where do I choose it".
 *
 * Deliberately at the TOP of the project tab and always expanded. The previous
 * arrangement put the choice in a `<select>` under an assignments table, which
 * on an empty project is below an empty state - a control nobody would find,
 * offering options nobody had loaded.
 */
export function SystemChooser({
  catalogueEmpty,
  onSeedCatalogue,
  seeding,
  onAdd,
  adding,
}: SystemChooserProps) {
  const { t } = useTranslation();
  const locale = getNumberLocale();

  const [elementType, setElementType] = useState<FormworkSystemType>('wall');
  const [area, setArea] = useState('500');
  const [reuses, setReuses] = useState('10');
  const [waste, setWaste] = useState('5.00');
  const [selectedId, setSelectedId] = useState('');

  const reuseCount = Math.max(1, Number.parseInt(reuses || '1', 10) || 1);
  const areaValid = Number.parseFloat(area || '0') > 0;

  // The element type is a click, so it queries at once; the three typed fields
  // wait until they stop changing.
  const settledArea = useSettled(area);
  const settledReuses = useSettled(reuseCount);
  const settledWaste = useSettled(waste);

  const { data: comparison, isLoading } = useQuery({
    queryKey: ['formwork', 'compare', elementType, settledArea, settledReuses, settledWaste],
    queryFn: () =>
      compareSystems({
        area_m2: settledArea || '0',
        reuse_count: settledReuses,
        waste_pct: settledWaste || '0',
        system_type: elementType,
      }),
    enabled: !catalogueEmpty && Number.parseFloat(settledArea || '0') > 0,
  });

  const candidates = useMemo(() => comparison?.candidates ?? [], [comparison]);
  const selected = candidates.find((c) => c.system_id === selectedId) ?? null;

  // True while a typed change has not reached the priced result yet. The
  // summary and the Add button read the SETTLED figures, so without this a
  // fast click could add 1200 m2 under a price computed for 120.
  const settling =
    area !== settledArea || waste !== settledWaste || reuseCount !== settledReuses;

  return (
    <Card className="p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-content-primary flex items-center gap-2">
            <Layers size={15} />
            {t('formwork.chooser.title', { defaultValue: 'Choose a formwork system' })}
          </h2>
          <p className="text-xs text-content-secondary mt-1 max-w-2xl">
            {t('formwork.chooser.subtitle', {
              defaultValue:
                'The same wall costs a different rate and runs a different cycle in a different system. Pick what you are forming, state the area and how many times the set turns around, and compare.',
            })}
          </p>
        </div>
      </div>

      {catalogueEmpty ? (
        <EmptyState
          icon={<Sparkles size={22} />}
          title={t('formwork.chooser.emptyTitle', {
            defaultValue: 'No formwork systems yet',
          })}
          description={t('formwork.chooser.emptyDesc', {
            defaultValue:
              'Load the starter catalogue to get wall panels, column and beam forms, slab tables, climbing and tunnel systems and slab props, each with a rate, a reuse limit and a cycle you can edit.',
          })}
          action={
            <Button variant="primary" loading={seeding} onClick={onSeedCatalogue}>
              {t('formwork.catalogue.seed', { defaultValue: 'Add starter systems' })}
            </Button>
          }
        />
      ) : (
        <>
          {/* Step 1 - what are you forming? */}
          <div>
            <div className="text-xs font-medium text-content-secondary mb-1.5">
              {t('formwork.chooser.step1', { defaultValue: '1. What are you forming?' })}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {SYSTEM_TYPE_ORDER.map((type) => (
                <button
                  key={type}
                  type="button"
                  aria-pressed={elementType === type}
                  onClick={() => {
                    setElementType(type);
                    setSelectedId('');
                  }}
                  className={[
                    'px-2.5 h-8 rounded-lg border text-xs font-medium transition-colors',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                    elementType === type
                      ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                      : 'border-border bg-surface-primary text-content-secondary hover:border-oe-blue',
                  ].join(' ')}
                >
                  {t(`formwork.type.${type}`, { defaultValue: SYSTEM_TYPE_LABELS[type] })}
                </button>
              ))}
            </div>
          </div>

          {/* Step 2 - the assumptions every candidate is priced against. */}
          <div>
            <div className="text-xs font-medium text-content-secondary mb-1.5">
              {t('formwork.chooser.step2', {
                defaultValue: '2. How much, and how many times?',
              })}
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
              <Input
                label={t('formwork.chooser.contactArea', {
                  defaultValue: 'Contact area m2',
                })}
                hint={t('formwork.chooser.contactAreaHint', {
                  defaultValue: 'The face the concrete touches',
                })}
                type="number"
                min={0}
                step="0.01"
                value={area}
                onChange={(e) => setArea(e.target.value)}
              />
              <Input
                label={t('formwork.chooser.reusesAssumed', {
                  defaultValue: 'Reuses assumed',
                })}
                hint={t('formwork.chooser.reusesAssumedHint', {
                  defaultValue: 'Same figure for every system compared',
                })}
                type="number"
                min={1}
                value={reuses}
                onChange={(e) => setReuses(e.target.value)}
              />
              <Input
                label={t('formwork.col.waste', { defaultValue: 'Waste %' })}
                hint={t('formwork.chooser.wasteHint', {
                  defaultValue: 'Loads the panel cost only',
                })}
                type="number"
                min={0}
                max={100}
                step="0.01"
                value={waste}
                onChange={(e) => setWaste(e.target.value)}
              />
            </div>
          </div>

          {/* Step 3 - the comparison. */}
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
              <div className="text-xs font-medium text-content-secondary">
                {t('formwork.chooser.step3', { defaultValue: '3. Which system?' })}
              </div>
              {candidates.length > 0 && (
                <div className="text-xs text-content-secondary">
                  {t('formwork.chooser.pricedAt', {
                    defaultValue: '{{count}} systems, all priced at {{reuses}} uses',
                    count: candidates.length,
                    reuses: reuseCount,
                  })}
                </div>
              )}
            </div>

            {!areaValid ? (
              <p className="text-xs text-content-secondary py-3">
                {t('formwork.chooser.needArea', {
                  defaultValue: 'Enter a contact area to compare systems.',
                })}
              </p>
            ) : isLoading ? (
              <SkeletonTable rows={3} />
            ) : candidates.length === 0 ? (
              <EmptyState
                icon={<Ruler size={20} />}
                title={t('formwork.chooser.noneForTypeTitle', {
                  defaultValue: 'No system in the catalogue forms this',
                })}
                description={t('formwork.chooser.noneForTypeDesc', {
                  defaultValue:
                    'Add one on the Catalogue tab, or load the starter systems to get a row for every element type.',
                })}
              />
            ) : (
              <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                {candidates.map((candidate) => (
                  <CandidateCard
                    key={candidate.system_id}
                    candidate={candidate}
                    selected={candidate.system_id === selectedId}
                    isBestBuildable={
                      candidate.system_id === comparison?.cheapest_buildable_system_id
                    }
                    locale={locale}
                    onSelect={() => setSelectedId(candidate.system_id)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* What picking it will do, spelled out before it is done. */}
          {selected && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface-secondary p-3">
              <div className="text-xs text-content-secondary">
                {t('formwork.chooser.summary', {
                  defaultValue:
                    '{{name}}: {{area}} m2 at {{rate}} per m2 over {{reuses}} uses, {{total}} total.',
                  name: selected.name,
                  area: fmt(settledArea, locale),
                  rate: fmt(selected.unit_cost, locale),
                  reuses: settledReuses,
                  total: fmt(selected.total, locale),
                })}
                {selected.exceeds_reuses_max && (
                  <span className="block text-semantic-error mt-1">
                    {t('formwork.chooser.blockedHint', {
                      defaultValue:
                        'These panels only survive {{max}} uses, so this rate cannot be built. Lower the reuses or pick another system.',
                      max: selected.reuses_max,
                    })}
                  </span>
                )}
              </div>
              <Button
                variant="primary"
                loading={adding || settling}
                disabled={!areaValid || settling || selected.exceeds_reuses_max}
                onClick={() =>
                  onAdd({
                    // The figures that were actually priced, so the assignment
                    // stores what the card on screen said it would cost.
                    systemId: selected.system_id,
                    areaM2: settledArea,
                    reuseCount: settledReuses,
                    wastePct: settledWaste || '0',
                  })
                }
              >
                {t('formwork.chooser.addToProject', { defaultValue: 'Add to project' })}
              </Button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
