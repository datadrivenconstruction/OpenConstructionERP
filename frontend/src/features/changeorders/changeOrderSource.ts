// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The site record a change order was raised from, read off its metadata.
 *
 * An RFI answered with a cost impact and an NCR closed with one each raise a
 * change order: by hand through the record's own "create variation" action,
 * or automatically as a draft when the event arrives (backend
 * `app/modules/changeorders/events.py`). Both write the same keys - `source`,
 * `rfi_id` / `ncr_id` and the record's number - and the automatic one also
 * stamps `auto_drafted: true`. This is the one place that turns those keys
 * into a label and a destination, so the banner and the "Related" pill on the
 * detail view cannot disagree about where the change came from.
 *
 * `null` when the change order names no such source, so callers draw nothing
 * rather than a pill to a bare register.
 */

export type ChangeOrderSourceKind = 'rfi' | 'ncr';

export interface ChangeOrderSource {
  kind: ChangeOrderSourceKind;
  id: string;
  /** The record's own number (`RFI-012`, `NCR-004`), empty when not stamped. */
  number: string;
  /** Where the record itself opens. */
  to: string;
  /** True when the change order was drafted by the platform, not by a person. */
  autoDrafted: boolean;
}

const encode = (id: string): string => encodeURIComponent(id);

function str(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

export function changeOrderSource(
  metadata: Record<string, unknown> | null | undefined,
): ChangeOrderSource | null {
  if (!metadata) return null;
  const source = str(metadata.source);
  const autoDrafted = metadata.auto_drafted === true;
  if (source === 'rfi') {
    const id = str(metadata.rfi_id);
    if (!id) return null;
    return { kind: 'rfi', id, number: str(metadata.rfi_number), to: `/rfi/${encode(id)}`, autoDrafted };
  }
  if (source === 'ncr') {
    const id = str(metadata.ncr_id);
    if (!id) return null;
    return {
      kind: 'ncr',
      id,
      number: str(metadata.ncr_number),
      to: `/ncr?highlight=${encode(id)}`,
      autoDrafted,
    };
  }
  return null;
}
