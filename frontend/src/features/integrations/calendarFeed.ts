// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The subscription address of a project's iCalendar feed.
 *
 * The server serves one feed per project and authenticates on a token in the
 * query string:
 *
 *     GET /api/v1/integrations/calendar/{project_id}.ics/?token=...
 *
 * The integrations page used to print the origin followed by a bare
 * `feed.ics`. That addressed nothing the server has: no project in the path
 * and no token at all, so everyone who copied it into a calendar client got a
 * rejection instead of a feed, with nothing on screen to say why.
 *
 * The token is an API key and no screen issues one yet, so the address is
 * built with the placeholder left standing rather than pretending this page
 * can fill it in. A gap the reader can see and act on beats a complete looking
 * string that cannot work.
 */

/** Stands in the query string until the reader substitutes a real key. */
export const CALENDAR_TOKEN_PLACEHOLDER = 'API_KEY';

/**
 * Build the feed address for one project.
 *
 * Returns an empty string when no project is active: the route has no form
 * that omits the project, so there is no address to offer and the caller shows
 * a prompt instead of a broken one.
 */
export function calendarFeedUrl(origin: string, projectId: string): string {
  if (!projectId) return '';
  return `${origin}/api/v1/integrations/calendar/${projectId}.ics/?token=${CALENDAR_TOKEN_PLACEHOLDER}`;
}
