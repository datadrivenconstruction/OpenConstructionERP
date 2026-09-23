// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The one way the app reads the list of projects.
 *
 * `GET /v1/projects/` pages. With no `limit` the server answers with the first
 * 50 and says nothing about the rest: the body is a bare array with no total.
 * Roughly seventy call sites asked for it that way, each inline, so every
 * picker, filter and fallback "first project" on those pages silently worked
 * from the first 50, while the header switcher asked for `?limit=500` under a
 * key of its own. Same bytes up to 50 projects, two requests on every page,
 * and past 50 a switcher that could see projects the page next to it could not.
 *
 * Every reader now fetches through here, and the ones that cache under
 * `['projects']` share one entry with the switcher. 500 is the server's
 * maximum (`backend/app/modules/projects/router.py`, `list_projects`).
 */

import { apiGet } from './api';

/** The page size asked for, and the most the server will hand back in one call. */
export const PROJECT_LIST_LIMIT = 500;

/** Path of the full, non-archived project list. */
export const PROJECT_LIST_PATH = `/v1/projects/?limit=${PROJECT_LIST_LIMIT}`;

/**
 * Fetch the project list. The type argument is the caller's claim about the
 * body, exactly as with `apiGet`, so each call site keeps the shape it reads.
 */
export function fetchProjectList<TResponse>(): Promise<TResponse> {
  return apiGet<TResponse>(PROJECT_LIST_PATH);
}

/**
 * True when a list came back full, which means there may be more projects than
 * it holds. The response carries no total, so a full page is the only signal;
 * a reader that treats this list as complete (to show "all", or to decide a
 * stored project no longer exists) has to check this first.
 */
export function isProjectListTruncated(list: unknown): boolean {
  return Array.isArray(list) && list.length >= PROJECT_LIST_LIMIT;
}
