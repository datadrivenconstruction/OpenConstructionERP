// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PropertySearchPanel — DuckDB-backed property search for the BIM viewer
 * (v3.12.0 / Stream D).
 *
 * Lets the user query the full DDC Parquet (1000+ columns per element) with
 * a tiny filter builder (property / operator / value) and pipe the matching
 * elements into the 3D viewport via the caller-supplied ``onIsolate``
 * callback. The backend does the heavy lifting in
 * ``POST /models/{id}/dataframe/query/``; the operator rules (contains and
 * equality ignore case and surrounding spaces, "not equal" keeps elements
 * where the property is empty) live in ``dataframe_store.py``. Numbers for
 * the comparisons are read here, in the reader's number convention, and sent
 * as JSON numbers; a server refusal arrives as a code we translate.
 *
 * Ids: a Parquet row is keyed by the CAD element id (the Revit ElementId for
 * a DDC export, stored on the element as ``mesh_ref``). The viewer keys its
 * meshes by the element's DATABASE id, so hits are translated through
 * ``mapSearchHitsToElementIds`` before they reach ``onIsolate``. Forwarding
 * the raw ElementIds isolated nothing the viewer could find.
 *
 * Property names: the DDC import lowercases every header, so queries use the
 * lowercase key (``phase created``) while the list shows the header as the
 * converter wrote it (``Phase Created``) when the sidecar stored it.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Search, Loader2, X } from 'lucide-react';
import { compareNames } from '@/shared/lib/collator';
import { fmtNumber } from '@/shared/lib/formatters';
import { useNumberLocale } from '@/stores/usePreferencesStore';
import {
  BIMDataframeError,
  fetchBIMDataframeColumnValues,
  fetchBIMSidecarState,
  type BIMSidecarState,
  fetchBIMDataframeSchema,
  queryBIMDataframe,
  type BIMDataframeColumn,
  type BIMDataframeFilter,
  type BIMDataframeValueCount,
} from './api';
import { SearchCombobox, type ComboOption } from './SearchCombobox';
import {
  columnLabel,
  formatReadAs,
  isNumericSearchOp,
  mapSearchHitsToElementIds,
  parseSearchNumber,
  pickIdColumn,
  type PropertySearchElement,
} from './propertySearch';

interface PropertySearchPanelProps {
  modelId: string;
  /** Elements loaded in the viewer. Used to translate Parquet hits (CAD
   *  element ids) into the element ids the viewer isolates by. */
  elements: readonly PropertySearchElement[];
  /** Called with the viewer ids of the matching elements. Never called with
   *  an empty list: zero matches leave the view as it is. */
  onIsolate: (elementIds: string[]) => void;
  /** Called when the user clears the search — the parent should drop any
   *  active isolation set so the user sees the full model again. */
  onClear?: () => void;
  /** Optional list of child model IDs for federated viewers. When supplied
   *  with 2+ entries the panel renders an additional "Target model" picker
   *  so the user chooses WHICH constituent model to search — the dataframe
   *  endpoints are per-model, not federation-wide. When undefined or
   *  single-entry the panel falls back to ``modelId`` and the picker is
   *  hidden. Forward-compatible for FederationsPage / FederatedViewer; the
   *  single-model BIMPage mount leaves it unset. */
  childModelIds?: string[];
}

type SearchOp = BIMDataframeFilter['op'];

/** Server-side cap of ``/dataframe/query/``; reaching it means "maybe more". */
const QUERY_LIMIT = 50000;
/** How many distinct values the value dropdown loads per property. */
const VALUE_OPTIONS_LIMIT = 200;

const OPS: SearchOp[] = ['LIKE', '=', '!=', '>', '>=', '<', '<='];

type SearchOutcome =
  | { kind: 'hits'; elementCount: number; unmatched: number; truncated: boolean }
  | { kind: 'none' }
  | { kind: 'unplaced'; rowCount: number };

export default function PropertySearchPanel({
  modelId,
  elements,
  onIsolate,
  onClear,
  childModelIds,
}: PropertySearchPanelProps) {
  const { t } = useTranslation();
  const numberLocale = useNumberLocale();
  const [schema, setSchema] = useState<BIMDataframeColumn[]>([]);
  const [column, setColumn] = useState<string>('');
  const [columnText, setColumnText] = useState<string>('');
  const [op, setOp] = useState<SearchOp>('LIKE');
  const [value, setValue] = useState<string>('');
  const [valueOptions, setValueOptions] = useState<BIMDataframeValueCount[]>([]);
  const [valueOffset, setValueOffset] = useState(0);
  const [valueRequest, setValueRequest] = useState(0);
  const [valueTotal, setValueTotal] = useState(0);
  const [valuesLoading, setValuesLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  // Text we wrote, or a failure translated when it renders.
  const [error, setError] = useState<string | Error | null>(null);
  const [outcome, setOutcome] = useState<SearchOutcome | null>(null);
  /** How a number that reads two ways ("1.500") was read for the last search. */
  const [readAs, setReadAs] = useState<string | null>(null);
  /** Whether the model's property table still holds the properties the
   *  import's 30-per-element cap left out of the database. */
  const [sidecar, setSidecar] = useState<BIMSidecarState>('full');
  /** Federation-aware target model id — see ``childModelIds`` prop. When the
   *  parent only knows about one model (the common single-viewer case) this
   *  collapses to ``modelId`` and the per-model picker stays hidden. */
  const hasChildPicker = !!childModelIds && childModelIds.length > 1;
  const [targetModelId, setTargetModelId] = useState<string>(
    () => (hasChildPicker ? childModelIds![0]! : modelId),
  );
  // Keep the target in sync if the parent swaps the active model wholesale
  // (e.g. user picks a different federation from a sidebar). Single-model
  // mounts also benefit — refresh after upload completes triggers re-fetch.
  useEffect(() => {
    setTargetModelId(hasChildPicker ? childModelIds![0]! : modelId);
  }, [modelId, hasChildPicker, childModelIds]);

  const idColumn = useMemo(() => pickIdColumn(schema), [schema]);

  /** Searchable properties, by the label the user knows them by. */
  const columnOptions = useMemo<ComboOption[]>(
    () =>
      schema
        .map((c) => ({ value: c.name, label: columnLabel(c) }))
        .sort((a, b) => compareNames(a.label, b.label)),
    [schema],
  );
  const selectedLabel = useMemo(
    () => columnOptions.find((o) => o.value === column)?.label ?? '',
    [columnOptions, column],
  );

  const selectColumn = useCallback((key: string, label: string) => {
    setColumn(key);
    setColumnText(label);
    setValueOptions([]);
  }, []);

  useEffect(() => {
    if (!targetModelId) return;
    let cancelled = false;
    const ctrl = new AbortController();
    setError(null);
    // Reset the column when the target switches so a stale column name from
    // a previous model's schema cannot poison the next query (column names
    // diverge across disciplines: ARC vs MEP vs STR rarely share full sets).
    setSchema([]);
    setColumn('');
    setColumnText('');
    setValueOptions([]);
    setOutcome(null);
    setSidecar('full');
    // Best-effort: without an answer the panel claims nothing.
    fetchBIMSidecarState(targetModelId, ctrl.signal)
      .then((state) => {
        if (!cancelled) setSidecar(state);
      })
      .catch(() => {});
    fetchBIMDataframeSchema(targetModelId, ctrl.signal)
      .then((rows) => {
        if (cancelled) return;
        setSchema(rows);
        // Preselect a sensible default — prefer common DDC keys, otherwise
        // the first property. The id column is never the default: nobody
        // filters by Revit ElementId first.
        const preferred = ['storey', 'level', 'category', 'name', 'type name'];
        const idCol = pickIdColumn(rows);
        const candidates = rows.filter((r) => r.name !== idCol);
        const found =
          preferred
            .map((p) => candidates.find((r) => r.name.toLowerCase() === p))
            .find((r) => r !== undefined) ?? candidates[0];
        if (found) {
          setColumn(found.name);
          setColumnText(columnLabel(found));
        }
      })
      .catch((e: unknown) => {
        // Ignore AbortError when the user switches targets mid-flight —
        // there's no real "error" to display, just a superseded request.
        if (cancelled) return;
        if (e instanceof DOMException && e.name === 'AbortError') return;
        const reason = e instanceof Error ? e.message : String(e);
        setError(new BIMDataframeError(reason, 'schema_failed'));
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [targetModelId]);

  // Values present in the model, for "=" and "!=". Best-effort: without them
  // the value field is a plain text input.
  const wantsValues = op === '=' || op === '!=';
  useEffect(() => {
    setValueOffset(0);
    setValueOptions([]);
    setValueTotal(0);
  }, [wantsValues, column, targetModelId]);
  useEffect(() => {
    if (!wantsValues || !column || !targetModelId) {
      setValueOptions([]);
      return;
    }
    let cancelled = false;
    const ctrl = new AbortController();
    setValuesLoading(true);
    fetchBIMDataframeColumnValues(targetModelId, column, VALUE_OPTIONS_LIMIT, ctrl.signal, valueOffset)
      .then((page) => {
        if (!cancelled) {
          setValueOptions((previous) => valueOffset === 0 ? page.items : [...previous, ...page.items]);
          setValueTotal(page.total);
        }
      })
      .catch(() => {
        if (!cancelled && valueOffset === 0) setValueOptions([]);
      })
      .finally(() => { if (!cancelled) setValuesLoading(false); });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [wantsValues, column, targetModelId, valueOffset, valueRequest]);

  const valueComboOptions = useMemo<ComboOption[]>(
    () => valueOptions.map((v) => ({ value: v.value, label: v.value, hint: fmtNumber(v.count, 0) })),
    [valueOptions],
  );

  // The server's 400 carries a code; the reader gets our text for it, never
  // the server's English.
  const describeError = useCallback(
    (e: unknown): string => {
      const code = e instanceof BIMDataframeError ? e.code : '';
      switch (code) {
        case 'unknown_column':
          return t('bim.property_search_error_unknown_column', {
            defaultValue: 'The model has no property "{{column}}".',
            column: e instanceof BIMDataframeError ? (e.params.column ?? '') : '',
          });
        case 'needs_number':
          return t('bim.property_search_error_needs_number', {
            defaultValue: 'This comparison needs a number, for example {{example}}.',
            example: formatReadAs(1234.5, numberLocale),
          });
        case 'bad_filter':
        case 'needs_list':
        case 'needs_single_value':
        case 'unsupported_operator':
          return t('bim.property_search_error_bad_filter', {
            defaultValue: 'This operator cannot be used with this value.',
          });
        case 'schema_failed':
          return t('bim.property_search_error_schema', {
            defaultValue: 'The property list of this model could not be loaded.',
          });
        default:
          return t('bim.property_search_error_failed', {
            defaultValue: 'The property search could not run. Try again, or pick another property.',
          });
      }
    },
    [t, numberLocale],
  );

  const handleSearch = useCallback(async () => {
    if (!column || value.trim() === '') return;
    if (!idColumn) {
      setError(
        t('bim.property_search_no_id_column', {
          defaultValue: 'This model has no element id column, so matches cannot be shown in the 3D view.',
        }),
      );
      return;
    }
    // Numbers are read here in the reader's convention, so "1.500" in Italian
    // is 1500, and the server never reads the text as a number of its own. A
    // comparison sends the number and refuses text that is none; "=" and "!="
    // send the text with the number beside it (null when it is no number).
    let filter: BIMDataframeFilter = { column, op, value };
    let reading: string | null = null;
    const parsed = parseSearchNumber(value, numberLocale);
    if (isNumericSearchOp(op)) {
      if (!parsed) {
        setOutcome(null);
        setReadAs(null);
        setError(new BIMDataframeError(`Not a number: ${value}`, 'needs_number'));
        return;
      }
      filter = { column, op, value: parsed.value };
    } else if (op === '=' || op === '!=') {
      filter = { column, op, value, number: parsed ? parsed.value : null };
    }
    if (parsed?.ambiguous && op !== 'LIKE') reading = formatReadAs(parsed.value, numberLocale);
    setLoading(true);
    setError(null);
    setOutcome(null);
    setReadAs(reading);
    try {
      const columns = schema.some((c) => c.name === 'stable_id') && idColumn !== 'stable_id'
        ? [idColumn, 'stable_id']
        : [idColumn];
      const rows = await queryBIMDataframe(targetModelId, {
        columns,
        filters: [filter],
        limit: QUERY_LIMIT,
      });
      const mapped = mapSearchHitsToElementIds(rows, idColumn, elements);
      if (mapped.rowCount === 0) {
        // Zero matches leave the view alone and say so. Isolating nothing
        // used to fall through to "show everything", which read as "the
        // filter did nothing".
        setOutcome({ kind: 'none' });
      } else if (mapped.elementIds.length === 0) {
        setOutcome({ kind: 'unplaced', rowCount: mapped.rowCount });
      } else {
        setOutcome({
          kind: 'hits',
          elementCount: mapped.elementIds.length,
          unmatched: mapped.unmatchedCount,
          truncated: mapped.rowCount >= QUERY_LIMIT,
        });
        onIsolate(mapped.elementIds);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setLoading(false);
    }
  }, [targetModelId, column, op, value, idColumn, schema, elements, onIsolate, t, numberLocale]);

  const handleClear = useCallback(() => {
    setValue('');
    setOutcome(null);
    setReadAs(null);
    setError(null);
    onClear?.();
  }, [onClear]);

  // A property must end on a real column: on blur, accept an exact name typed
  // by hand, otherwise put the current choice back.
  const handleColumnBlur = useCallback(() => {
    const typed = columnText.trim().toLowerCase();
    const exact = columnOptions.find(
      (o) => o.label.toLowerCase() === typed || o.value.toLowerCase() === typed,
    );
    if (exact) selectColumn(exact.value, exact.label);
    else setColumnText(selectedLabel);
  }, [columnText, columnOptions, selectColumn, selectedLabel]);

  const canSearch = !!column && value.trim() !== '' && !loading;

  // A property the user looks for and the model's table lacks, on a model
  // whose table lost what the import's cap left out: say a re-import brings
  // it back, instead of leaving "no property matches" or "no element" to read
  // as "the model has none". (An empty table has its own hint below.)
  const typedColumn = columnText.trim().toLowerCase();
  const columnNotFound =
    typedColumn !== '' &&
    !columnOptions.some((o) => o.label.toLowerCase().includes(typedColumn) || o.value.toLowerCase().includes(typedColumn));
  const showCappedNotice =
    sidecar !== 'full' && schema.length > 0 && !error && (columnNotFound || outcome?.kind === 'none');

  const opLabel = (o: SearchOp): string => {
    switch (o) {
      case 'LIKE':
        return t('bim.property_search_op_contains', { defaultValue: 'contains' });
      case '=':
        return t('bim.property_search_op_equals', { defaultValue: 'equals' });
      case '!=':
        return t('bim.property_search_op_not_equals', { defaultValue: 'does not equal' });
      default:
        return o;
    }
  };

  return (
    <div className="flex flex-col gap-2 p-3" data-testid="property-search-panel">
      <h3 className="text-xs font-semibold text-content-primary uppercase tracking-wide">
        {t('bim.property_search_title', { defaultValue: 'Property search' })}
      </h3>
      <p className="text-[10px] text-content-tertiary">
        {t('bim.property_search_hint', {
          defaultValue:
            'Filter the full DDC dataframe (1000+ columns). Matches isolate in the 3D view.',
        })}
      </p>

      {/* Federation target-model picker — only when the parent passed 2+
          child model ids. The dataframe endpoints are scoped to a single
          model (the URL ``/bim/<id>`` for a federation is the federation
          id, NOT a model id, so searches MUST resolve to a constituent
          model before they hit the backend). */}
      {hasChildPicker && (
        <>
          <label className="block text-[10px] font-medium text-content-secondary">
            {t('bim.property_search_target', { defaultValue: 'Target model' })}
          </label>
          <select
            value={targetModelId}
            onChange={(e) => setTargetModelId(e.target.value)}
            disabled={loading}
            className="w-full min-w-0 px-2 py-1 text-[11px] rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue disabled:opacity-50"
            data-testid="property-search-target"
          >
            {childModelIds!.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </>
      )}

      {/* Property picker: type to narrow a list that runs to 1000+ entries. */}
      <span className="block text-[10px] font-medium text-content-secondary">
        {t('bim.property_search_column', { defaultValue: 'Column' })}
      </span>
      <SearchCombobox
        inputValue={columnText}
        onInputChange={setColumnText}
        options={columnOptions}
        selectedValue={column}
        onSelect={(o) => selectColumn(o.value, o.label)}
        onBlur={handleColumnBlur}
        // Enter on a partial name puts the current choice back, as blur does,
        // so the box never shows a column the search would not use.
        onEnter={handleColumnBlur}
        ariaLabel={t('bim.property_search_column', { defaultValue: 'Column' })}
        placeholder={
          schema.length === 0
            ? t('bim.property_search_no_schema', { defaultValue: 'No schema available' })
            : t('bim.property_search_column_placeholder', { defaultValue: 'Type to find a property…' })
        }
        disabled={loading || schema.length === 0}
        testId="property-search-column"
        emptyText={t('bim.property_search_no_column_match', {
          defaultValue: 'No property matches what you typed.',
        })}
      />
      {/* Empty-schema hint — without this, the user just sees a disabled
          picker saying "No schema available" and assumes the panel is
          broken. The most common reason is a model imported without the
          DDC Parquet sidecar (legacy upload path / converter unavailable).
          Surface that explicitly so the user knows what to do next. */}
      {schema.length === 0 && !error && (
        <p
          className="text-[10px] text-content-tertiary leading-tight"
          data-testid="property-search-empty-hint"
        >
          {t('bim.property_search_no_schema_hint', {
            defaultValue:
              'This model has no DDC dataframe - re-import via the CAD/BIM converter to enable property search.',
          })}
        </p>
      )}

      {/* Operator + value */}
      <div className="flex items-center gap-1.5 min-w-0">
        <select
          value={op}
          onChange={(e) => setOp(e.target.value as SearchOp)}
          disabled={loading}
          aria-label={t('bim.property_search_operator', { defaultValue: 'Operator' })}
          className="shrink-0 px-2 py-1 text-[11px] rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
          data-testid="property-search-op"
        >
          {OPS.map((o) => (
            <option key={o} value={o}>
              {opLabel(o)}
            </option>
          ))}
        </select>
        <SearchCombobox
          className="flex-1"
          inputValue={value}
          onInputChange={setValue}
          options={wantsValues ? valueComboOptions : []}
          selectedValue={value}
          onSelect={(o) => setValue(o.value)}
          onEnter={() => {
            if (canSearch) void handleSearch();
          }}
          ariaLabel={t('bim.property_search_value', { defaultValue: 'Value' })}
          placeholder={t('bim.property_search_value_placeholder', {
            defaultValue: 'Value…',
          })}
          testId="property-search-value"
          emptyText={t('bim.property_search_no_value_match', {
            defaultValue: 'No value in the model matches. Search runs with what you typed.',
          })}
        />
      </div>

      {wantsValues && valueOptions.length < valueTotal && (
        <button
          type="button"
          disabled={valuesLoading}
          onClick={() => { setValueOffset(valueOptions.length); setValueRequest((n) => n + 1); }}
          data-testid="property-search-values-more"
          className="text-xs text-oe-blue disabled:opacity-50"
        >
          {t('boq.load_more', { defaultValue: 'Load more' })} ({valueOptions.length} / {valueTotal})
        </button>
      )}

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={handleSearch}
          disabled={!canSearch}
          className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-md bg-oe-blue px-2 py-1 text-[11px] font-medium text-white hover:bg-oe-blue-dark disabled:opacity-50 disabled:cursor-not-allowed"
          data-testid="property-search-submit"
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : <Search size={11} />}
          {t('bim.property_search_run', { defaultValue: 'Search & isolate' })}
        </button>
        {outcome !== null && (
          <button
            type="button"
            onClick={handleClear}
            className="shrink-0 inline-flex items-center gap-1 rounded-md border border-border-light bg-surface-primary px-2 py-1 text-[11px] text-content-secondary hover:bg-surface-tertiary"
            data-testid="property-search-clear"
          >
            <X size={11} />
            {t('common.clear', { defaultValue: 'Clear' })}
          </button>
        )}
      </div>

      {outcome?.kind === 'hits' && !error && (
        <div role="status" className="flex flex-col gap-0.5">
          <p className="text-[10px] text-content-secondary" data-testid="property-search-result-count">
            {t('bim.property_search_results', {
              defaultValue_one: '{{count}} matching element',
              defaultValue_other: '{{count}} matching elements',
              count: outcome.elementCount,
            })}
          </p>
          {outcome.unmatched > 0 && (
            <p className="text-[10px] text-amber-700 dark:text-amber-400" data-testid="property-search-unmatched">
              {t('bim.property_search_unmatched', {
                defaultValue_one: '{{count}} more match has no element in the 3D view.',
                defaultValue_other: '{{count}} more matches have no element in the 3D view.',
                count: outcome.unmatched,
              })}
            </p>
          )}
          {outcome.truncated && (
            <p className="text-[10px] text-content-tertiary" data-testid="property-search-truncated">
              {t('bim.property_search_truncated', {
                defaultValue: 'Only the first {{limit}} matches are shown. Narrow the search to see the rest.',
                limit: fmtNumber(QUERY_LIMIT, 0),
              })}
            </p>
          )}
        </div>
      )}
      {outcome?.kind === 'none' && !error && (
        <p className="text-[10px] text-content-secondary" role="status" data-testid="property-search-no-match">
          {t('bim.property_search_no_match', {
            defaultValue: 'No element matches this search. The 3D view is unchanged.',
          })}
        </p>
      )}
      {outcome?.kind === 'unplaced' && !error && (
        <p className="text-[10px] text-amber-700 dark:text-amber-400" role="status" data-testid="property-search-unplaced">
          {t('bim.property_search_unplaced', {
            defaultValue_one: '{{count}} element matches, but none of them is in the 3D view. The view is unchanged.',
            defaultValue_other:
              '{{count}} elements match, but none of them is in the 3D view. The view is unchanged.',
            count: outcome.rowCount,
          })}
        </p>
      )}
      {showCappedNotice && (
        <p
          className="text-[10px] text-amber-700 dark:text-amber-400"
          role="status"
          data-testid="property-search-capped-properties"
        >
          {t('bim_rules.sandbox_capped_properties', {
            defaultValue:
              'This model only has the 30 properties per element kept in the database, because its full property table was rebuilt or is missing. Re-import the model to get every property back.',
          })}
        </p>
      )}
      {readAs !== null && outcome !== null && !error && (
        <p className="text-[10px] text-content-tertiary" data-testid="property-search-read-as">
          {t('bim.property_search_read_as', { defaultValue: 'Read as {{number}}', number: readAs })}
        </p>
      )}
      {error && (
        <p
          className="text-[10px] text-rose-600 dark:text-rose-400"
          role="alert"
          data-testid="property-search-error"
        >
          {typeof error === 'string' ? error : describeError(error)}
        </p>
      )}
    </div>
  );
}
