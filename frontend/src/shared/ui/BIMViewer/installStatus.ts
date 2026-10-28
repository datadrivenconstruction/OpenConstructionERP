// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Discrete install-status bucket for the "Install status" colour mode.
 *
 * Answers the one question a site engineer asks standing in front of a model:
 * is this element installed, being installed, or still to come? It prefers the
 * schedule (a 4D-linked element's status at the current scrubber time) and
 * falls back to recorded BOQ progress when the element is not scheduled.
 */

import type { FourDStatus } from './4dStatus';

export type InstallStatus = 'installed' | 'in_progress' | 'pending' | 'none';

/**
 * Green / amber / grey - reused from the 4D + validation palettes so the
 * viewer's colour language stays consistent. `none` has no swatch: the element
 * keeps its neutral (faded) colour because we have no status for it.
 */
export const INSTALL_STATUS_HEX: Record<Exclude<InstallStatus, 'none'>, string> = {
  installed: '#10b981',
  in_progress: '#f59e0b',
  pending: '#9ca3af',
};

/**
 * Resolve an element's install status.
 *
 * Precedence is deliberate: a scheduled element follows its schedule, so a
 * 60%-measured-but-scheduled-as-complete element still reads "installed". Only
 * when the element carries no schedule link do we fall back to BOQ progress.
 *
 * @param scheduleStatus resolveElementStatus() at the current time, or null
 *   when no 4D schedule is available. `unlinked` is treated as "not scheduled".
 * @param pct latest recorded percent-complete (0-100), or null/undefined when
 *   the element has no linked + measured BOQ position.
 */
export function resolveInstallStatus(
  scheduleStatus: FourDStatus | null | undefined,
  pct: number | null | undefined,
): InstallStatus {
  if (scheduleStatus && scheduleStatus !== 'unlinked') {
    if (scheduleStatus === 'completed') return 'installed';
    if (scheduleStatus === 'in_progress') return 'in_progress';
    return 'pending'; // not_started
  }
  if (pct == null) return 'none';
  if (pct >= 100) return 'installed';
  if (pct > 0) return 'in_progress';
  return 'pending'; // pct === 0: known but not begun
}
