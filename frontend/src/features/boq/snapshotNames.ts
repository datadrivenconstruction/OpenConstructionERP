// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The reader-language name of a bill snapshot the system named itself.
 *
 * The quantity baseline takes two snapshots on its own: one the first time a
 * bill is locked, and one when a person freezes the bill from the quantity
 * check. Their names are stored as English data
 * (`LOCK_SNAPSHOT_NAME` and `FROZEN_SNAPSHOT_NAME` in
 * backend/app/modules/boq/quantity_baseline.py; a backend test holds the two
 * files to the same strings), so a German site manager would otherwise read
 * "Quantity baseline" in the middle of a German screen. A name a person typed
 * is shown as typed.
 */

/** Minimal shape of the i18next `t` used here (repo convention). */
type Translate = (key: string, opts?: Record<string, unknown>) => string;

/** Stored name of the snapshot taken when a bill is locked for the first time. */
export const LOCK_SNAPSHOT_NAME = 'Contract quantities (captured at lock)';

/** Stored name of the snapshot frozen from the quantity check. */
export const FROZEN_SNAPSHOT_NAME = 'Quantity baseline';

export function snapshotDisplayName(name: string, t: Translate): string {
  if (name === LOCK_SNAPSHOT_NAME) {
    return t('boq.snapshot_name.captured_at_lock', { defaultValue: 'Contract quantities (captured at lock)' });
  }
  if (name === FROZEN_SNAPSHOT_NAME) {
    return t('boq.snapshot_name.quantity_baseline', { defaultValue: 'Quantity baseline' });
  }
  return name;
}
