// Design module (ERP side of the design editor link).
/** Draft change orders made from accepted revisions (card R9). The register itself is the ERP's change-order page. */

export type ChangeOrderMode = 'off' | 'ask' | 'always';
export const CHANGE_ORDER_MODES: ChangeOrderMode[] = ['off', 'ask', 'always'];

export interface ChangeOrderSettings {
  mode: ChangeOrderMode;
  /** Project manager in the ERP: may change the setting. */
  can_change: boolean;
  /** May also create change orders (the change-order module's own permission). */
  can_create: boolean;
}

export interface RevisionChangeOrder {
  revision_id: string;
  number: number;
  revision_status: string;
  mode: ChangeOrderMode;
  /** none: no snapshot (setting was off); declined: snapshot, no order; deleted: removed in the register. */
  state: 'none' | 'declined' | 'created' | 'deleted';
  snapshot: boolean;
  change_order: {
    id: string;
    code: string;
    title: string;
    status: string;
    cost_impact: string;
    currency: string | null;
    unpriced_positions: number;
    url: string;
  } | null;
}

/** Whether the confirmation asks, states, or says nothing about a change order. */
export function acceptChoice(settings: ChangeOrderSettings | undefined): 'ask' | 'always' | 'none' {
  if (!settings || settings.mode === 'off') return 'none';
  // "always" is said even without the permission: the server then refuses the accept, the note says why.
  if (settings.mode === 'ask' && !settings.can_create) return 'none';
  return settings.mode;
}

/** A draft can still be made later only from a snapshot taken at acceptance. */
export function canCreateLater(view: RevisionChangeOrder | undefined, settings: ChangeOrderSettings | undefined): boolean {
  return !!view && !!settings?.can_create && view.snapshot && (view.state === 'declined' || view.state === 'deleted');
}
