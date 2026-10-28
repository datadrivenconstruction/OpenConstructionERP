import i18n from '@/app/i18n';

/**​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * Locale display names for the built-in measurement groups (audit case-2
 * K-4-bis).
 *
 * `measurement.group` persists the canonical English name - the wire format,
 * the exports and the bucketing logic all compare against it, exactly like
 * unit codes (canonical value in data, locale only at render time; see the
 * K-13 invariant). Only the eight built-in names have translations;
 * user-created groups are free-form text and render verbatim.
 */
const CANONICAL_GROUP_KEYS: Record<string, string> = {
  General: 'takeoff_viewer.group_general',
  Structural: 'takeoff_viewer.group_structural',
  Electrical: 'takeoff_viewer.group_electrical',
  Plumbing: 'takeoff_viewer.group_plumbing',
  HVAC: 'takeoff_viewer.group_hvac',
  Finishing: 'takeoff_viewer.group_finishing',
  Excavation: 'takeoff_viewer.group_excavation',
  Concrete: 'takeoff_viewer.group_concrete',
};

/** Render a measurement group name in the UI language; canonical value stays untouched. */
export function displayGroupName(name: string): string {
  const key = CANONICAL_GROUP_KEYS[name];
  return key ? i18n.t(key, { defaultValue: name }) : name;
}
