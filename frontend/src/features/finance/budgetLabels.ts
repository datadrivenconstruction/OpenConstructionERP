// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { TFunction } from 'i18next';

/** A project WBS node (WBSResponse on the wire), as far as a label needs it. */
export interface WbsNode {
  id: string;
  code?: string | null;
  name?: string | null;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * What the Budgets table shows for a row's WBS.
 *
 * A budget row's `wbs_id` is one of three things: the id of a project WBS
 * node (a bill whose positions carry a WBS), the id of a bill section (the
 * BOQ "Create Budget" grouping), or a code a person typed on a manual line.
 * The server resolves both kinds of id into `wbs_label`; failing that, a WBS
 * node resolves to "code name"; a typed code is already readable; an id
 * nothing here can name is shortened rather than printed as 36 characters,
 * with the full id kept for the tooltip.
 */
export function wbsLabel(
  wbsId: string | null | undefined,
  nodes: Map<string, WbsNode>,
  serverLabel?: string | null,
): { text: string; title?: string } {
  const raw = (wbsId ?? '').trim();
  if (!raw) return { text: '' };
  // The server names WBS nodes and bill sections alike (`wbs_label`); the
  // node map only knows WBS nodes, so the server's name comes first.
  const named = (serverLabel ?? '').trim();
  if (named) return { text: named, title: raw };
  const node = nodes.get(raw);
  if (node) {
    const text = [node.code, node.name].filter((part) => part && String(part).trim()).join(' ');
    return { text: text || raw, title: raw };
  }
  if (UUID_RE.test(raw)) return { text: `${raw.slice(0, 8)}…`, title: raw };
  return { text: raw };
}

/**
 * A budget category in the reader's language.
 *
 * Rows arrive in two spellings: the manual form's capitalised keys
 * ("Material") and the lower-case vocabulary of the import and the bill
 * seeding ("material", "subcontractor", "estimate"). Both map to one label; a
 * value outside the vocabulary is shown as it was stored.
 */
export function budgetCategoryLabel(t: TFunction, raw: string | null | undefined): string {
  const value = (raw ?? '').trim();
  switch (value.toLowerCase()) {
    case 'material':
    case 'materials':
      return t('finance.cat_material', { defaultValue: 'Material' });
    case 'labor':
    case 'labour':
      return t('finance.cat_labor', { defaultValue: 'Labor' });
    case 'equipment':
      return t('finance.cat_equipment', { defaultValue: 'Equipment' });
    case 'subcontract':
    case 'subcontractor':
      return t('finance.cat_subcontract', { defaultValue: 'Subcontract' });
    case 'overhead':
      return t('finance.cat_overhead', { defaultValue: 'Overhead' });
    case 'contingency':
      return t('finance.cat_contingency', { defaultValue: 'Contingency' });
    case 'estimate':
      return t('finance.cat_estimate', { defaultValue: 'Bill of quantities' });
    case 'other':
    case '':
      return t('finance.cat_other', { defaultValue: 'Other' });
    default:
      return value;
  }
}
