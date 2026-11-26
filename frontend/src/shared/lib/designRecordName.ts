// Design module codes written into other modules' records (BOQ, tender packages, RFQs, addenda, change orders).
/** Neutral name codes from the design take-off rendered in the UI language; any other text is returned as is. */
import type { TFunction } from 'i18next';

type T = TFunction | ((key: string, options?: Record<string, unknown>) => unknown);

const TAKEOFF = 'design_takeoff';
const ESTIMATE = 'design_estimate';
const ADDENDUM_RE = /^design_revision_quantities:(\d+)$/;
const CHANGE_ORDER_RE = /^design_revision:(\d+)(?::([\s\S]*))?$/;
const TOKEN_RE = /\[co:(\w+)(?:\|(\{[^\]]*\}))?\]/g;

export function designRecordName(t: T, name: string | null | undefined): string {
  if (!name) return '';
  const tt = t as (key: string, options?: Record<string, unknown>) => unknown;
  if (name === TAKEOFF) return String(tt('design.takeoff.boq_name'));
  if (name === ESTIMATE) return String(tt('design.estimate.boq_name'));
  if (name.startsWith(`${TAKEOFF}:`)) {
    return String(tt('design.takeoff.package_name', { ifc_class: name.slice(TAKEOFF.length + 1) }));
  }
  const m = ADDENDUM_RE.exec(name);
  if (m) return String(tt('design.addendum.revision_title', { number: m[1] }));
  const co = CHANGE_ORDER_RE.exec(name);
  if (co) {
    const head = String(tt('design.changeorder.title', { number: co[1] }));
    return co[2] ? `${head}: ${co[2]}` : head;
  }
  return name;
}

/** Sentences the design module generated into a change order, written as `[co:key|{params}]` tokens;
 *  rendered in the UI language. Text without tokens (older records, typed text) is returned as is. */
export function designRecordText(t: T, text: string | null | undefined): string {
  if (!text) return '';
  const tt = t as (key: string, options?: Record<string, unknown>) => unknown;
  return text.replace(TOKEN_RE, (whole, key: string, json?: string) => {
    let params: Record<string, unknown> = {};
    if (json) {
      try {
        params = JSON.parse(json) as Record<string, unknown>;
      } catch {
        return whole;
      }
    }
    return String(tt(`design.changeorder.${key}`, params));
  });
}
