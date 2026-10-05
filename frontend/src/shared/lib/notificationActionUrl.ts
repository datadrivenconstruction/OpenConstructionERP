// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Re-shape a stored notification `action_url` that no route declares.
 *
 * The backend fixed its producers, but a notification row keeps the link it
 * was written with. Rows written before the fix still carry paths such as
 * `/service/tickets/{id}` or `/files/{kind}/{id}?comment=`, which fall through
 * to Not Found. Each entry maps one old shape onto the page that now shows the
 * record, using only what the old link itself carries.
 *
 * Shared by the bell, the notifications page and the inbox so a stale row
 * opens the same page from all three. `notificationLinksLandOnARoute.test.ts`
 * checks that every rewrite lands on a declared route and never touches a
 * path some route does declare.
 */

type Rewrite = [RegExp, (m: RegExpMatchArray) => string];

const SEG = '([^/?#]+)';

export const ACTION_URL_REWRITES: readonly Rewrite[] = [
  // Pre-v2.9.34 shapes.
  [/^\/risk(\?.*)?$/, (m) => `/risks${m[1] ?? ''}`],
  [/^\/boq\?id=([0-9a-fA-F-]{8,})$/, (m) => `/boq/${m[1]}`],
  // Shapes the producers wrote until the route gate existed.
  [
    new RegExp(`^/files/${SEG}/${SEG}(?:\\?comment=${SEG})?$`),
    (m) => `/files?kind=${m[1]}&file=${m[2]}${m[3] ? `&comment=${m[3]}` : ''}`,
  ],
  [new RegExp(`^/projects/${SEG}/documents$`), (m) => `/projects/${m[1]}/files?kind=document`],
  [new RegExp(`^/approvals/${SEG}$`), () => '/governance?tab=approvals'],
  [new RegExp(`^/bid-management/packages/${SEG}$`), (m) => `/bid-management?highlight=${m[1]}`],
  [new RegExp(`^/bid-management/invitations/${SEG}$`), () => '/bid-management'],
  [/^\/costmodel(\?.*)?$/, () => '/5d'],
  [new RegExp(`^/file-approvals/${SEG}$`), () => '/files/approvals'],
  [new RegExp(`^/changeorders/${SEG}$`), (m) => `/changeorders?highlight=${m[1]}`],
  [/^\/discussions(\?.*)?$/, () => '/collaboration'],
  [new RegExp(`^/service/(?:tickets|work-orders)/${SEG}$`), () => '/service'],
  [new RegExp(`^/subcontractors/(?:prequalifications|payment-applications|retention)/${SEG}$`), () => '/subcontractors'],
  [new RegExp(`^/equipment/(?:damage/)?${SEG}$`), () => '/equipment'],
  [new RegExp(`^/contracts/[^/?#]*/claims/${SEG}$`), () => '/contracts?tab=claims'],
  [new RegExp(`^/contracts/${SEG}$`), (m) => `/contracts?highlight=${m[1]}`],
  [new RegExp(`^/crm/(?:leads|opportunities)/${SEG}$`), () => '/crm'],
  [new RegExp(`^/resources/assignments/${SEG}$`), () => '/resources'],
  [new RegExp(`^/resources/${SEG}$`), (m) => `/resources?resourceId=${m[1]}`],
  [new RegExp(`^/property-dev/buyers/${SEG}$`), (m) => `/property-dev?buyerId=${m[1]}`],
  [new RegExp(`^/property-dev/handovers/${SEG}$`), () => '/property-dev?tab=handovers'],
  [new RegExp(`^/property-dev/warranty/${SEG}$`), () => '/property-dev?tab=warranty'],
  [new RegExp(`^/schedule-advanced/constraints/${SEG}$`), () => '/schedule-advanced'],
  [new RegExp(`^/daily-diary/${SEG}$`), () => '/daily-diary'],
  [/^\/bi-dashboards\/(?:alerts|reports)$/, () => '/bi-dashboards'],
  // A report notification used to link the API download itself.
  [/^\/api\/v1\/bi-dashboards\/report-runs\/[^?#]+$/, () => '/bi-dashboards'],
  [new RegExp(`^/(?:procurement/(?:po|vendors)|finance/invoices|warehouses)/${SEG}$`), () => '/supplier-catalogs'],
  [new RegExp(`^/carbon/inventories/${SEG}$`), () => '/carbon'],
  [new RegExp(`^/qms/ncrs/${SEG}$`), () => '/qms'],
];

/** The link to navigate to for a stored `action_url`. */
export function normalizeActionUrl(url: string): string {
  for (const [re, build] of ACTION_URL_REWRITES) {
    const m = url.match(re);
    if (m) return build(m);
  }
  return url;
}
