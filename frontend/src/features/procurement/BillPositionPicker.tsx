// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Attach a purchase-order line to the bill position it is being bought for.
 *
 * The buyer sees bill positions and never a cost line. What comes back out of
 * this control is a `boq_position_id`, which the server resolves to the cost
 * line when the order line is written; deriving the money link is our job, not
 * theirs. See `backend/app/modules/procurement/cost_spine.py`.
 *
 * Renders nothing at all when the project's cost spine is empty. That is the
 * ordinary state of a project that has never generated one, and an empty
 * dropdown with an explanation under it would put a permanent piece of
 * furniture on the order form for a choice that cannot be made. The same
 * silence covers the case where the cost model module is not installed, since
 * a plugin that is not there answers nothing rather than answering zero.
 *
 * Searching goes to the server. A bill can hold thousands of positions against
 * a page of two hundred, and a filter that could only see the loaded page would
 * tell a buyer their position does not exist while the register holds it. Three
 * consequences follow and each is deliberate:
 *
 * Whether to render at all is decided by the unsearched list and never by the
 * current results, so a search that matches nothing leaves the control in place
 * to be corrected instead of making it vanish mid-keystroke.
 *
 * The unsearched list is one page and may be partial, so it says so rather than
 * presenting itself as the whole register.
 *
 * The current selection is fetched by its own id when the page does not contain
 * it. A control that cannot find its own value renders as unselected, and the
 * next save would write that back, which is the quiet way an attribution made
 * months ago disappears.
 */

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import {
  SPINE_PAGE_SIZE,
  fetchBillPositions,
  fetchPositionLine,
  type CostSpineLine,
} from './costSpineApi';

/**
 * Above this many positions the plain dropdown stops being usable and the
 * search box is shown with it. Below it the list is short enough to read, and
 * a search box over eight rows is clutter.
 */
const SEARCH_THRESHOLD = 12;

/** Long enough that ordinary typing makes one request, short enough to feel live. */
const SEARCH_DEBOUNCE_MS = 300;

/**
 * Value that settles once typing pauses. Local to this file on purpose: the
 * only other implementations live in `shared/ui` and in another feature, and a
 * feature must not import a hook this small out of a sibling feature.
 */
function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return settled;
}

export interface BillPositionPickerProps {
  /** Project whose cost spine is offered. */
  projectId: string;
  /** Currently selected bill position, or null when the line is unattributed. */
  value: string | null;
  /** Called with the chosen position id, or null when the buyer clears it. */
  onChange: (boqPositionId: string | null) => void;
  /**
   * Line number within the order, used for the accessible name. A form with
   * eight identical "Bill position" controls is unusable with a screen reader,
   * so each says which line it belongs to.
   */
  line?: number;
  disabled?: boolean;
}

/** `1.1 - Reinforced concrete C30/37 (m3)`, the way it reads in the bill. */
export function optionLabel(option: CostSpineLine): string {
  const unit = option.unit ? ` (${option.unit})` : '';
  return `${option.code} - ${option.description}${unit}`;
}

export function BillPositionPicker({
  projectId,
  value,
  onChange,
  line,
  disabled = false,
}: BillPositionPickerProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const term = useDebouncedValue(query.trim(), SEARCH_DEBOUNCE_MS);

  // The unsearched page. Decides whether this control exists at all, so it is
  // kept as its own query rather than being the search query with an empty
  // term: a search matching nothing must not read as a project with no spine.
  const base = useQuery({
    queryKey: ['procurement', 'billPositions', projectId, ''],
    queryFn: () => fetchBillPositions(projectId),
    enabled: Boolean(projectId),
    // The spine changes when somebody regenerates it from the bill, which is
    // not something that happens while an order is being typed.
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const searched = useQuery({
    queryKey: ['procurement', 'billPositions', projectId, term],
    queryFn: () => fetchBillPositions(projectId, term),
    enabled: Boolean(projectId) && term.length > 0,
    staleTime: 60 * 1000,
    retry: false,
  });

  const page = term ? searched.data : base.data;
  const listed = page?.positions ?? [];

  // The selection, when the page on screen does not carry it. Waiting for the
  // unsearched page to arrive before deciding matters: an empty list is the
  // state every picker is in for its first frame, and treating that as "the
  // selection is missing" would fire this request on every mount, including
  // the ordinary case where the position is on the very page still loading.
  const listedHere = listed.some((o) => o.boq_position_id === value);
  const selected = useQuery({
    queryKey: ['procurement', 'billPosition', projectId, value],
    queryFn: () => fetchPositionLine(projectId, value as string),
    enabled: Boolean(projectId) && Boolean(value) && base.isSuccess && !listedHere,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  // Nothing to choose from, so nothing to show. Covers three cases that all
  // mean the same thing to the buyer: the spine has not been generated, the
  // request failed, and the cost model module is not installed.
  if (base.isLoading || base.isError || (base.data?.positions.length ?? 0) === 0) return null;

  const label = t('procurement.item_position', { defaultValue: 'Bill position' });
  const ariaLabel =
    line === undefined
      ? label
      : t('procurement.item_position_for', {
          defaultValue: 'Bill position for line {{line}}',
          line,
        });

  // A selection the current list does not hold is still the selection, and
  // dropping it from the options would make the control render as unlinked.
  // The resolved line stays cached against the value, so narrowing the search
  // past it keeps the label rather than blanking the buyer's own attribution.
  const options = !listedHere && selected.data ? [selected.data, ...listed] : listed;

  const showSearch =
    (base.data?.positions.length ?? 0) > SEARCH_THRESHOLD || (base.data?.truncated ?? false);

  return (
    <div className="flex flex-col gap-1">
      {showSearch && (
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={disabled}
          // The placeholder is the accessible name here on purpose. Giving the
          // search box the same aria-label as the select next to it would put
          // two controls with one name on the form, which is worse for a screen
          // reader than the fallback the placeholder already provides.
          placeholder={label}
          className="w-full rounded border border-border-light px-2 py-1 text-sm"
        />
      )}
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={disabled}
        aria-label={ariaLabel}
        className="w-full rounded border border-border-light px-2 py-1 text-sm"
      >
        <option value="">
          {t('procurement.item_position_none', { defaultValue: 'Not linked to the estimate' })}
        </option>
        {options.map((option) => (
          <option key={option.id} value={option.boq_position_id as string}>
            {optionLabel(option)}
          </option>
        ))}
      </select>
      {/* A page of a longer register must never read as the whole register. */}
      {(page?.truncated ?? false) && (
        <p className="text-[11px] leading-tight text-content-tertiary">
          {t('procurement.item_position_truncated', {
            defaultValue: 'Showing the first {{count}}. Search to reach the rest of the bill.',
            count: SPINE_PAGE_SIZE,
          })}
        </p>
      )}
    </div>
  );
}
