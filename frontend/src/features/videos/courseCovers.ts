// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Which illustrated cover a course, checklist or guide gets: its first topic
// that names a subject decides, then the screen it teaches, then its kind.
// Every item resolves to a cover, so no card is ever left blank.

import type { AcademyItem } from './academyTypes';

export type CoverSubject =
  | 'takeoff'
  | 'bim'
  | 'estimate'
  | 'exchange'
  | 'tender'
  | 'schedule'
  | 'cost'
  | 'finance'
  | 'contract'
  | 'quality'
  | 'safety'
  | 'site'
  | 'carbon'
  | 'checklist'
  | 'guide';

export type CoverAccent = 'erp' | 'academy' | 'design';

/** Brand colour per subject: blue for model and quantities, green for time,
 *  money and quality, orange for the commercial and risk side. */
export const COVER_ACCENT: Record<CoverSubject, CoverAccent> = {
  takeoff: 'erp',
  bim: 'erp',
  estimate: 'erp',
  exchange: 'erp',
  site: 'erp',
  guide: 'erp',
  schedule: 'academy',
  cost: 'academy',
  finance: 'academy',
  quality: 'academy',
  carbon: 'academy',
  checklist: 'academy',
  tender: 'design',
  contract: 'design',
  safety: 'design',
};

const TOPIC_SUBJECT: Record<string, CoverSubject> = {
  'pdf takeoff': 'takeoff',
  'dwg takeoff': 'takeoff',
  takeoff: 'takeoff',
  bim: 'bim',
  'bim hub': 'bim',
  'clash detection': 'bim',
  'bim requirements (ids)': 'bim',
  'bcf issues': 'bim',
  'bim-coordination': 'bim',
  boq: 'estimate',
  estimating: 'estimate',
  'cost database': 'estimate',
  'cost-data': 'estimate',
  'markups-tax': 'estimate',
  'boq-exchange': 'exchange',
  'bid management': 'tender',
  tendering: 'tender',
  procurement: 'tender',
  'procurement-stock': 'tender',
  schedule: 'schedule',
  scheduling: 'schedule',
  cvr: 'cost',
  'earned value': 'cost',
  'budget-control': 'cost',
  'cost-control': 'cost',
  'cash-flow': 'cost',
  payments: 'finance',
  'progress-billing': 'finance',
  retention: 'finance',
  contracts: 'contract',
  variations: 'contract',
  'change-orders': 'contract',
  claims: 'contract',
  inspections: 'quality',
  ncr: 'quality',
  defects: 'quality',
  'punch list': 'quality',
  closeout: 'quality',
  handover: 'quality',
  quality: 'quality',
  safety: 'safety',
  'risk register': 'safety',
  risk: 'safety',
  'site diary': 'site',
  'site-diary': 'site',
  rfi: 'site',
  documents: 'site',
  'project-setup': 'site',
  carbon: 'carbon',
};

const ROUTE_SUBJECT: Record<string, CoverSubject> = {
  '/takeoff': 'takeoff',
  '/bim': 'bim',
  '/clash': 'bim',
  '/bcf': 'bim',
  '/requirements': 'bim',
  '/boq': 'estimate',
  '/costs': 'estimate',
  '/tendering': 'tender',
  '/bid-management': 'tender',
  '/procurement': 'tender',
  '/schedule': 'schedule',
  '/cost-control': 'cost',
  '/cvr': 'cost',
  '/full-evm': 'cost',
  '/finance': 'finance',
  '/contracts': 'contract',
  '/variations': 'contract',
  '/changeorders': 'contract',
  '/inspections': 'quality',
  '/ncr': 'quality',
  '/punchlist': 'quality',
  '/closeout': 'quality',
  '/safety': 'safety',
  '/risks': 'safety',
  '/daily-diary': 'site',
  '/documents': 'site',
  '/rfi': 'site',
  '/carbon': 'carbon',
};

export function coverSubject(item: Pick<AcademyItem, 'topics' | 'routes' | 'kind'>): CoverSubject {
  for (const topic of item.topics) {
    const s = TOPIC_SUBJECT[topic.toLowerCase()];
    if (s) return s;
  }
  for (const route of item.routes) {
    const s = ROUTE_SUBJECT[route.split('?')[0] ?? route];
    if (s) return s;
  }
  return item.kind === 'checklist' ? 'checklist' : item.kind === 'article' ? 'guide' : 'estimate';
}

/** The subject of a later topic that differs from the first, if any. */
export function secondSubject(item: Pick<AcademyItem, 'topics'>, first: CoverSubject): CoverSubject | null {
  for (const topic of item.topics) {
    const s = TOPIC_SUBJECT[topic.toLowerCase()];
    if (s && s !== first) return s;
  }
  return null;
}

/** A small stable number from the item id, so two covers of one subject differ. */
export function coverSeed(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i += 1) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
