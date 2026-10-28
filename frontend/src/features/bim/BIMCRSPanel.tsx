// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BIMCRSPanel — surfaces the auto-detected Coordinate Reference System
 * (CRS) for the active BIM model.
 *
 * Three states:
 *   1. CRS detected with confidence > 0 → green chip with EPSG label.
 *   2. CRS unknown (epsg === null) → amber chip with "Set CRS" button
 *      that opens a dropdown of common EPSG codes (top 10 by region)
 *      and a manual-paste field.
 *   3. CRS missing (model didn't go through detector) → neutral chip.
 *
 * The backend persists the guess on ``BIMModel.crs_epsg`` and mirrors
 * the full guess (including alternates) into ``metadata.crs`` so we
 * can show the top-3 alternates in the "Set CRS" dropdown without an
 * extra round trip.
 *
 * See backend/app/modules/cad/crs_detector.py for the detection
 * heuristic and internal CRS-detection research notes for the table of
 * EPSG codes covered.
 */

import { useState } from 'react';
import { Globe2, ChevronDown, Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface CRSAlternate {
  epsg: number | null;
  name: string;
  confidence: number;
}

interface CRSPanelProps {
  /** EPSG code or null when auto-detection didn't decide. */
  epsg: number | null | undefined;
  /** Human-readable display name (always set). */
  name: string | null | undefined;
  /** 0..1 confidence (null = no decision). */
  confidence: number | null | undefined;
  /** Provenance: "ifc_projected_crs" / "dwg_geodata" / "bbox_heuristic" / "user_supplied". */
  method?: string | null;
  /** Alternates pulled from metadata.crs.alternatives. */
  alternatives?: CRSAlternate[];
  /** Called when the user picks a CRS from the dropdown or types an EPSG. */
  onSetCRS?: (epsg: number) => void;
}

// Top 10 common EPSG codes shown in the "Set CRS" picker when no
// alternatives were sent by the backend. Mirrors the region table in
// crs_detector.py — keep these in sync.
const COMMON_CRS: { epsg: number; label: string }[] = [
  { epsg: 4326, label: 'WGS 84 (geographic, lat-lon)' },
  { epsg: 25832, label: 'ETRS89 / UTM zone 32N (Germany W)' },
  { epsg: 25833, label: 'ETRS89 / UTM zone 33N (Germany E)' },
  { epsg: 27700, label: 'OSGB36 / British National Grid (UK)' },
  { epsg: 2154, label: 'RGF93 / Lambert-93 (France)' },
  { epsg: 32643, label: 'UTM zone 43N (India W)' },
  { epsg: 32644, label: 'UTM zone 44N (India E)' },
  { epsg: 32640, label: 'UTM zone 40N (UAE)' },
  { epsg: 32618, label: 'UTM zone 18N (US East / NYC)' },
  { epsg: 31983, label: 'SIRGAS 2000 / UTM zone 23S (Brazil)' },
];

export function BIMCRSPanel({
  epsg,
  name,
  confidence,
  method,
  alternatives,
  onSetCRS,
}: CRSPanelProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [manualValue, setManualValue] = useState('');

  const hasCRS = epsg != null && Number.isFinite(epsg);
  const confidencePct =
    confidence != null && Number.isFinite(confidence)
      ? Math.round(confidence * 100)
      : null;

  // Confidence colour bands match the dashboard traffic-light: green ≥80%,
  // amber 50-79%, red <50%.
  const confidenceClass = !hasCRS
    ? 'border-amber-300 bg-amber-50 dark:bg-amber-950/20 text-amber-700 dark:text-amber-300'
    : confidencePct == null || confidencePct >= 80
      ? 'border-emerald-300 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-300'
      : confidencePct >= 50
        ? 'border-amber-300 bg-amber-50 dark:bg-amber-950/20 text-amber-700 dark:text-amber-300'
        : 'border-red-300 bg-red-50 dark:bg-red-950/20 text-red-700 dark:text-red-300';

  const handlePick = (next: number) => {
    if (onSetCRS) onSetCRS(next);
    setOpen(false);
  };

  const handleManual = () => {
    const parsed = parseInt(manualValue.trim(), 10);
    if (Number.isInteger(parsed) && parsed > 0 && parsed < 1_000_000) {
      handlePick(parsed);
      setManualValue('');
    }
  };

  const optionsToShow =
    alternatives && alternatives.length > 0
      ? alternatives
          .filter((a) => a.epsg != null)
          .map((a) => ({ epsg: a.epsg as number, label: a.name }))
      : COMMON_CRS;

  return (
    <div
      className={`relative rounded-lg border ${confidenceClass} backdrop-blur-sm
                  shadow-md px-3 py-2 min-w-[220px] max-w-[280px] transition-all`}
      data-testid="bim-crs-panel"
    >
      <div className="flex items-center gap-1.5 mb-1">
        <Globe2 size={12} className="shrink-0" />
        <span className="text-[10px] font-semibold uppercase tracking-wide">
          {t('bim.crs.label', { defaultValue: 'Detected CRS' })}
        </span>
      </div>

      {hasCRS ? (
        <>
          <div className="text-[11px] font-semibold leading-tight truncate" title={name ?? ''}>
            {name || `EPSG:${epsg}`}
          </div>
          <div className="text-[10px] opacity-80 mt-0.5 tabular-nums">
            EPSG:{epsg}
            {confidencePct != null && (
              <>
                <span className="mx-1">·</span>
                {t('bim.crs.confidence', { defaultValue: 'confidence' })} {confidencePct}%
              </>
            )}
            {method && (
              <>
                <span className="mx-1">·</span>
                <span className="opacity-70">{method.replace(/_/g, ' ')}</span>
              </>
            )}
          </div>
        </>
      ) : (
        <div className="text-[11px] leading-snug">
          {t('bim.crs.unknown', {
            defaultValue:
              'CRS could not be auto-detected - model uses local coordinates.',
          })}
        </div>
      )}

      {onSetCRS && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="mt-1.5 inline-flex items-center gap-1 text-[10px] font-medium
                     px-2 py-0.5 rounded border border-current hover:bg-black/5 dark:hover:bg-white/10
                     transition-colors"
          data-testid="bim-crs-set-button"
        >
          {t('bim.crs.set', { defaultValue: 'Set CRS' })}
          <ChevronDown size={10} />
        </button>
      )}

      {open && (
        <div
          className="absolute top-full left-0 mt-1 z-50 w-64
                     rounded-lg border border-border-light bg-surface-primary
                     shadow-lg overflow-hidden text-content-primary"
        >
          <div className="px-3 py-2 text-[10px] uppercase tracking-wide
                          text-content-tertiary border-b border-border-light">
            {t('bim.crs.pick_or_paste', { defaultValue: 'Pick a CRS or paste EPSG' })}
          </div>
          <div className="max-h-56 overflow-y-auto">
            {optionsToShow.map((opt) => (
              <button
                key={opt.epsg}
                type="button"
                onClick={() => handlePick(opt.epsg)}
                className="w-full text-left px-3 py-1.5 hover:bg-surface-secondary
                           text-[11px] flex items-center gap-2"
              >
                {opt.epsg === epsg && <Check size={10} className="text-emerald-500" />}
                <span className="truncate flex-1">{opt.label}</span>
                <span className="text-[9px] text-content-tertiary tabular-nums">
                  EPSG:{opt.epsg}
                </span>
              </button>
            ))}
          </div>
          <div className="border-t border-border-light p-2 flex gap-1">
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              placeholder={t('bim.crs.paste_placeholder', {
                defaultValue: 'e.g. 32643',
              })}
              value={manualValue}
              onChange={(e) => setManualValue(e.target.value.replace(/\D/g, ''))}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleManual();
                }
              }}
              className="flex-1 text-[11px] px-2 py-1 rounded border border-border-light
                         bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
            <button
              type="button"
              onClick={handleManual}
              className="text-[11px] px-2 py-1 rounded bg-oe-blue text-white
                         hover:bg-oe-blue/90"
            >
              {t('bim.crs.apply', { defaultValue: 'Apply' })}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default BIMCRSPanel;
