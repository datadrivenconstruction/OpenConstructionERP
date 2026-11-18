/**
 * Roles that hold `procurement.update` on the server (minimum role: editor;
 * manager and admin sit above it). The server stays the authority; this only
 * decides whether the Edit action is shown.
 */
const CAN_UPDATE_ORDERS = new Set(['editor', 'manager', 'admin']);

export function canUpdatePurchaseOrders(role: string | null | undefined): boolean {
  return role != null && CAN_UPDATE_ORDERS.has(role);
}
