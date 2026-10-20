// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The BIM page loads elements in skeleton mode, which leaves `boq_links`
 * empty on every row. The model-wide link roll-up (one call) is folded back
 * onto the rows here, so link-based counts such as "Unlinked" are real.
 */

import type { BIMElementData } from '@/shared/ui/BIMViewer';
import type { BIMBOQLinkBrief } from '@/shared/ui/BIMViewer/ElementManager';
import type { BIMModelBOQLinkAggregate } from './api';

export function mergeBoqLinkRollup(
  elements: BIMElementData[],
  rollup: BIMModelBOQLinkAggregate[] | undefined,
): BIMElementData[] {
  if (!rollup || rollup.length === 0) return elements;
  const byElement = new Map<string, BIMBOQLinkBrief[]>();
  for (const row of rollup) {
    const brief: BIMBOQLinkBrief = {
      id: `${row.boq_position_id}`,
      boq_position_id: row.boq_position_id,
      boq_position_ordinal: row.boq_position_ordinal,
      boq_position_description: row.boq_position_description,
      boq_position_quantity: row.boq_position_quantity,
      boq_position_unit: row.boq_position_unit,
      boq_position_unit_rate: row.boq_position_unit_rate,
      boq_position_total: row.boq_position_total,
      link_type: (row.link_type as BIMBOQLinkBrief['link_type']) || 'manual',
      confidence: row.confidence,
    };
    for (const id of row.element_ids) {
      const list = byElement.get(id);
      if (list) list.push(brief);
      else byElement.set(id, [brief]);
    }
  }
  return elements.map((el) => {
    if ((el.boq_links?.length ?? 0) > 0) return el;
    const links = byElement.get(el.id);
    return links ? { ...el, boq_links: links } : el;
  });
}
