// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * <AnchorDriftIndicator> — surfaces address-vs-anchor drift.
 *
 * When a user edits the project address AFTER the first geocode the
 * project's typed address and the cached ``anchor.address`` (which is
 * the Nominatim ``display_name`` of the original lookup) drift apart.
 * Without a hint the user has no way to know the pin on the map is
 * stale.
 *
 * This component compares the two strings (case-insensitive,
 * whitespace-tolerant) and renders:
 *
 *   - Address: "<typed>"
 *   - Anchored: "<cached>" + cached chip
 *   - Yellow "Re-anchor" CTA when the strings diverge
 *
 * Pure presentational — re-geocoding is owned by the parent (which calls
 * autoAnchorFromAddress with ``force=true`` then re-invalidates the
 * map-config query).
 */

import { useTranslation } from 'react-i18next';
import { History, MapPin, AlertCircle } from 'lucide-react';

interface AnchorDriftIndicatorProps {
  /** Free-text address the user typed on the project. */
  projectAddressText: string | null | undefined;
  /** Cached Nominatim display_name stored on the anchor. */
  anchoredAddress: string | null | undefined;
  /** Called when the user clicks "Re-anchor". */
  onReanchor?: () => void;
  /** When true, the re-anchor button shows a spinner. */
  isReanchoring?: boolean;
  /** Optional compact mode — drops the labels for tight chrome. */
  compact?: boolean;
}

function _normalise(value: string | null | undefined): string {
  if (!value) return '';
  return value.toLowerCase().replace(/[\s,]+/g, ' ').trim();
}

/**
 * Heuristic: the strings drift when more than ~30% of the typed
 * address tokens are absent from the anchored address. Exact match
 * after normalisation is the obvious "in sync" case; a missing comma
 * or extra postal code shouldn't fire the warning.
 */
export function detectDrift(
  projectAddressText: string | null | undefined,
  anchoredAddress: string | null | undefined,
): boolean {
  const a = _normalise(projectAddressText);
  const b = _normalise(anchoredAddress);
  if (!a || !b) return false;
  if (a === b) return false;
  if (b.includes(a) || a.includes(b)) return false;
  const tokens = a.split(' ').filter((t) => t.length >= 2);
  if (tokens.length === 0) return false;
  const missing = tokens.filter((t) => !b.includes(t)).length;
  return missing / tokens.length > 0.3;
}

export function AnchorDriftIndicator({
  projectAddressText,
  anchoredAddress,
  onReanchor,
  isReanchoring,
  compact,
}: AnchorDriftIndicatorProps) {
  const { t } = useTranslation();
  const drift = detectDrift(projectAddressText, anchoredAddress);

  // Nothing to show if either side is missing — the user has either
  // never typed an address or the anchor was hand-placed (display_name
  // is null on manual anchors).
  if (!projectAddressText && !anchoredAddress) return null;

  if (compact) {
    if (!drift) return null;
    return (
      <button
        type="button"
        onClick={onReanchor}
        disabled={isReanchoring}
        className={[
          'inline-flex items-center gap-1 rounded-full px-2 py-0.5',
          'border border-amber-300 bg-amber-50 text-2xs font-semibold text-amber-800',
          'hover:bg-amber-100 disabled:opacity-60 disabled:cursor-wait',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-300',
        ].join(' ')}
        title={t('geo_hub.drift.title', {
          defaultValue: 'Address changed since last anchor',
        })}
        data-testid="geo-drift-chip"
      >
        <AlertCircle size={10} strokeWidth={2.25} />
        {t('geo_hub.drift.short_cta', { defaultValue: 'Re-anchor' })}
      </button>
    );
  }

  return (
    <div
      className={[
        'space-y-1 rounded-md border border-border bg-surface-secondary/40',
        'px-3 py-2 text-2xs text-content-secondary',
        drift ? 'border-amber-300 bg-amber-50/60' : '',
      ].join(' ')}
      data-testid="geo-drift-indicator"
    >
      {projectAddressText && (
        <div className="flex items-start gap-1.5">
          <MapPin
            size={11}
            strokeWidth={2}
            className="mt-0.5 shrink-0 text-content-tertiary"
          />
          <div className="min-w-0 flex-1">
            <span className="font-semibold uppercase tracking-[0.10em] text-content-tertiary">
              {t('geo_hub.drift.address_label', { defaultValue: 'Address' })}:
            </span>{' '}
            <span className="text-content-primary">{projectAddressText}</span>
          </div>
        </div>
      )}
      {anchoredAddress && (
        <div className="flex items-start gap-1.5">
          <History
            size={11}
            strokeWidth={2}
            className="mt-0.5 shrink-0 text-content-tertiary"
          />
          <div className="min-w-0 flex-1">
            <span className="font-semibold uppercase tracking-[0.10em] text-content-tertiary">
              {t('geo_hub.drift.anchored_label', { defaultValue: 'Anchored' })}:
            </span>{' '}
            <span className="text-content-secondary">{anchoredAddress}</span>
            <span className="ml-1 inline-flex items-center rounded-sm bg-surface-tertiary px-1 py-px text-2xs uppercase tracking-wider">
              {t('geo_hub.drift.cached_chip', { defaultValue: 'cached' })}
            </span>
          </div>
        </div>
      )}
      {drift && onReanchor && (
        <div className="mt-1 flex items-center gap-2 pt-1">
          <AlertCircle
            size={11}
            strokeWidth={2.25}
            className="text-amber-600"
            aria-hidden
          />
          <span className="flex-1 text-amber-800">
            {t('geo_hub.drift.warning', {
              defaultValue:
                'Address text changed since the last geocode - anchor may be stale.',
            })}
          </span>
          <button
            type="button"
            onClick={onReanchor}
            disabled={isReanchoring}
            className={[
              'inline-flex items-center gap-1 rounded-md border border-amber-300',
              'bg-amber-100 px-2 py-0.5 text-2xs font-semibold text-amber-900',
              'hover:bg-amber-200 disabled:opacity-60 disabled:cursor-wait',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400',
            ].join(' ')}
            data-testid="geo-drift-reanchor"
          >
            {t('geo_hub.drift.reanchor', { defaultValue: '↻ Re-anchor' })}
          </button>
        </div>
      )}
    </div>
  );
}

export default AnchorDriftIndicator;
