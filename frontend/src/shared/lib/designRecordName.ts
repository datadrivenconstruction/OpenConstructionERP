// Design module codes written into other modules' records (BOQ, tender packages, RFQs, addenda).
/** Neutral name codes from the design take-off rendered in the UI language; any other text is returned as is. */
import type { TFunction } from 'i18next';

type T = TFunction | ((key: string, options?: Record<string, unknown>) => unknown);

const TAKEOFF = 'design_takeoff';
const ADDENDUM_RE = /^design_revision_quantities:(\d+)$/;

export function designRecordName(t: T, name: string | null | undefined): string {
  if (!name) return '';
  const tt = t as (key: string, options?: Record<string, unknown>) => unknown;
  if (name === TAKEOFF) return String(tt('design.takeoff.boq_name'));
  if (name.startsWith(`${TAKEOFF}:`)) {
    return String(tt('design.takeoff.package_name', { ifc_class: name.slice(TAKEOFF.length + 1) }));
  }
  const m = ADDENDUM_RE.exec(name);
  if (m) return String(tt('design.addendum.revision_title', { number: m[1] }));
  return name;
}
