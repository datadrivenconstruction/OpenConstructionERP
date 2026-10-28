// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Hours on the site clock. A delivery window is planned in the time of the
// site, not of whoever happens to type it: a planner in another zone must
// see and enter the same hour as the gate keeper. The server stores instants
// and reads a time without an offset as UTC, so the conversion is done here,
// with the zone the logistics concept names.

const LOCAL = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/;

/** The wall clock a zone shows at an instant, as if it were UTC milliseconds. Throws on an unknown zone. */
function wallOf(instant: number, timeZone: string): number {
  const format = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
  const p: Record<string, number> = {};
  for (const part of format.formatToParts(new Date(instant))) {
    if (part.type !== 'literal') p[part.type] = Number(part.value);
  }
  return Date.UTC(p.year ?? 0, (p.month ?? 1) - 1, p.day ?? 1, p.hour ?? 0, p.minute ?? 0, p.second ?? 0);
}

/** An instant as `YYYY-MM-DDTHH:mm` on the site clock; null without a zone, with an unknown one or a bad instant. */
export function wallClock(iso: string | null | undefined, timeZone: string | null | undefined): string | null {
  if (!iso || !timeZone) return null;
  const instant = new Date(iso).getTime();
  if (Number.isNaN(instant)) return null;
  try {
    return new Date(wallOf(instant, timeZone)).toISOString().slice(0, 16);
  } catch {
    return null;
  }
}

/**
 * The instant a `YYYY-MM-DDTHH:mm` on the site clock names, as ISO text; null
 * without a zone, with an unknown one or a text that is not a time. The
 * offset is looked up twice, so a time just after a clock change lands on the
 * right side of it.
 */
export function instantOf(local: string, timeZone: string | null | undefined): string | null {
  const m = LOCAL.exec(local);
  if (!m || !timeZone) return null;
  const wall = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]));
  try {
    const first = wall - (wallOf(wall, timeZone) - wall);
    const instant = wall - (wallOf(first, timeZone) - first);
    return new Date(instant).toISOString();
  } catch {
    return null;
  }
}
