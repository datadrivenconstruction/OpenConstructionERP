// Design module (ERP side of the design editor link).
/** The take-off writes neutral name codes into the BOQ, tender packages and RFQs; this renders them in the UI language. */
import { tr } from '../BriefFields';

type T = Parameters<typeof tr>[0];
const PREFIX = 'design_takeoff';

export function takeoffName(t: T, name: string | null | undefined): string {
  if (!name) return '';
  if (name === PREFIX) return tr(t, 'design.takeoff.boq_name');
  if (name.startsWith(`${PREFIX}:`)) return tr(t, 'design.takeoff.package_name', { ifc_class: name.slice(PREFIX.length + 1) });
  return name;
}
