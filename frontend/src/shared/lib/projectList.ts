// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The one way the app reads the list of projects.
 *
 * `GET /v1/projects/` pages with `offset` and `limit`. Asked with no `limit`
 * the server answers with the first 50 and says nothing about the rest: the
 * body is a bare array with no total. Close to a hundred call sites asked for
 * it that way, each inline, so every picker, filter and fallback "first
 * project" on those pages silently worked from the first 50, while the header
 * switcher asked for `?limit=500` under a key of its own.
 *
 * Every reader now fetches through here, and the list it gets is the whole
 * list: pages of the server's maximum (`limit` is capped at 500 in
 * `backend/app/modules/projects/router.py`, `list_projects`) are read until a
 * short one comes back. Up to 500 projects that is one request, the same one
 * the switcher always made.
 */

import { apiGet } from './api';

/** Rows asked for per request, the most the server hands back in one call. */
export const PROJECT_LIST_PAGE_SIZE = 500;

const LIST_PATH = '/v1/projects/';

async function readEveryPage(extraQuery: string): Promise<unknown[]> {
  const rows: unknown[] = [];
  const seen = new Set<unknown>();
  for (let offset = 0; ; offset += PROJECT_LIST_PAGE_SIZE) {
    const query = `limit=${PROJECT_LIST_PAGE_SIZE}${offset > 0 ? `&offset=${offset}` : ''}${extraQuery}`;
    const page = await apiGet<unknown>(`${LIST_PATH}?${query}`);
    // The type argument on apiGet is a claim, not a check. Anything but a list
    // here is a contract break, and treating it as "no projects" would let a
    // reader conclude that a stored project was deleted.
    if (!Array.isArray(page)) {
      throw new TypeError(`GET ${LIST_PATH} answered with ${page === null ? 'null' : typeof page}, expected a list`);
    }
    let added = 0;
    for (const row of page) {
      const id = (row as { id?: unknown } | null)?.id;
      if (id !== undefined) {
        // A project created while the pages are read shifts the ones after it
        // by one, so the next page can repeat a row this one already had.
        if (seen.has(id)) continue;
        seen.add(id);
      }
      rows.push(row);
      added += 1;
    }
    // A short page is the last one. A full page that brought nothing new means
    // the server is not honouring `offset`, and asking again would loop.
    if (page.length < PROJECT_LIST_PAGE_SIZE || added === 0) return rows;
  }
}

/**
 * Fetch every non-archived project the user can see. The type argument is the
 * caller's claim about the rows, exactly as with `apiGet`, so each call site
 * keeps the shape it reads.
 */
export async function fetchProjectList<TResponse extends unknown[]>(): Promise<TResponse> {
  return (await readEveryPage('')) as TResponse;
}

/**
 * Fetch every project with the given status, or every project in any status
 * including archived ones for `'all'`.
 */
export async function fetchProjectListByStatus<TResponse extends unknown[]>(status: string): Promise<TResponse> {
  return (await readEveryPage(`&status=${encodeURIComponent(status)}`)) as TResponse;
}
