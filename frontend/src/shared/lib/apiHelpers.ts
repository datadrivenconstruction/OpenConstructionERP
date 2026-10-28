// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Normalize an API list response that may return either a bare array
 * or an object with an `items` array.  Used as a `select` transform
 * in React Query to provide a consistent array to components.
 *
 * Internal ref: ddc-lineage:a17f93c4-core-02
 */
export function normalizeListResponse<T>(data: T[] | { items: T[] } | undefined | null): T[] {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  if ('items' in data && Array.isArray(data.items)) return data.items;
  return [];
}

/** The page envelope a list route answers with. */
export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

/** Everything a caller needs to know about a paged read, including what it did not get. */
export interface PagedResult<T> {
  items: T[];
  /** True when the ceiling stopped the read, so `items` is not the whole set. */
  truncated: boolean;
  /** The ceiling that stopped it, for a message the user can act on. */
  ceiling: number;
  /**
   * How many records the server said the full set holds, when it answered with
   * a page envelope. This is the one number a partial read still knows exactly,
   * which is what lets a caller say how much of a list it is showing instead of
   * either guessing or refusing. Undefined for a route that still answers with
   * a bare array, so a caller wanting to state a denominator must handle its
   * absence rather than print one it does not have.
   */
  total?: number;
}

/**
 * Read every page of a list endpoint instead of the first one.
 *
 * List routes here cap `limit` at 100, so a single request is a page, not a
 * data set. Passing that page straight into a sum, a count or an export is the
 * bug this exists to prevent: the number looks authoritative and is short by
 * however many records sit past the cap.
 *
 * The ceiling is a memory guard, not a page size. When it is reached the result
 * says so, so a partial read can never be presented as a complete one.
 *
 * A page envelope also states how many records exist in total, and that number
 * survives being cut off. It is reported back so that a caller stopped by the
 * ceiling can still say how much of the set it read, rather than having to
 * choose between a wrong figure and no answer at all.
 */
export async function fetchAllPages<T>(
  fetchPage: (offset: number, limit: number) => Promise<T[] | { items: T[] } | undefined | null>,
  options: { pageSize?: number; ceiling?: number } = {},
): Promise<PagedResult<T>> {
  const pageSize = options.pageSize ?? 100;
  const ceiling = options.ceiling ?? 10_000;
  const items: T[] = [];
  let total: number | undefined;

  for (let offset = 0; offset < ceiling; offset += pageSize) {
    const answer = await fetchPage(offset, Math.min(pageSize, ceiling - offset));
    // Take the count off the envelope before normalizing it away, and keep the
    // first page's answer rather than the last. A register being written while
    // this loop runs would otherwise hand back a denominator that moved as it
    // was being read, and a later page's total is no more authoritative than
    // the first one's.
    if (total === undefined && answer && !Array.isArray(answer)) {
      const declared = (answer as { total?: unknown }).total;
      if (typeof declared === 'number') total = declared;
    }
    const page = normalizeListResponse<T>(answer);
    items.push(...page);
    // A short page is the end of the data. An empty one guards against a route
    // that ignores offset, which would otherwise loop until the ceiling.
    if (page.length < pageSize) return { items, truncated: false, ceiling, total };
  }

  return { items, truncated: true, ceiling, total };
}

/**
 * Reduce an update payload to the fields the user actually edited.
 *
 * Edit forms here prefill from a record that was read at some earlier point and
 * then PATCH every field back, whether or not it was touched. That silently
 * undoes somebody else's work: you open a record, change the title, save, and
 * the description you never looked at is written back as it stood when your
 * copy was loaded, overwriting an edit made in between. Nobody sees an error,
 * because from the server's side it is an ordinary write.
 *
 * The update routes are PATCH over Pydantic models dumped with
 * `exclude_unset=True`, so a field left out of the body is left alone in the
 * database. Sending only what changed therefore narrows the window from every
 * field on the form to the single field two people edited at once, which no
 * amount of client-side care can fix without a version token.
 *
 * `base` must be the form state as it was first initialized, not the raw
 * record, so that both sides have been through the same normalization. That is
 * what keeps a date rendered as `2026-08-01` from reading as different to the
 * `2026-08-01T00:00:00` it came from, and stops a currency filled in from the
 * project default from being written onto a record that never had one.
 *
 * Clearing a field is still a change: form `''` against a base holding a value
 * is dirty, and the caller's payload maps it to `null`. Only an untouched field
 * is dropped. An empty result means nothing was edited, and the resulting empty
 * PATCH is a no-op the backend already handles.
 *
 * A payload key with no field of the same name on the form is always sent. The
 * key/value types line up in the signature, but `Object.keys` runs on the real
 * object, so a payload carrying something the form does not hold - an id, a
 * value derived from elsewhere on the page - would compare `undefined` against
 * `undefined`, read as untouched and be dropped from the body. Erring towards
 * sending it costs at most one redundant field; erring the other way silently
 * removes one the caller meant to write.
 */
export function onlyChangedFields<P extends object, F extends object>(
  payload: P,
  form: F,
  base: F,
): Partial<P> {
  const changed: Partial<P> = {};
  for (const key of Object.keys(payload) as (keyof P & keyof F & string)[]) {
    if (!(key in base) || !Object.is(form[key], base[key])) changed[key] = payload[key];
  }
  return changed;
}
