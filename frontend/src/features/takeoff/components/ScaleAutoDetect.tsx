// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tier-1 drawing-scale auto-detect affordance (issue: PDF scale auto-detect).
 *
 * A small, self-contained widget that reads the explicit scale note an
 * architect already typed in the PDF's title block (via the AI-free
 * `GET /v1/takeoff/documents/{id}/detect-scale/` endpoint) and offers it as a
 * one-click "Use this" suggestion. It owns NO calibration state of its own:
 * on click it converts the detected `1:N` ratio into a metric-canonical
 * `ScaleConfig` using the shared scale helpers and hands it to the parent via
 * `onApply`, so the existing calibration/recalc path stays the single source of
 * truth (CLAUDE.md rule 7: augmented, human-confirmed - nothing auto-applies).
 *
 * Designed to be dropped in next to the viewer's scale controls. It is fully
 * decoupled from the two-click `CalibrationDialog`; mount it wherever a
 * document id + current page are in scope.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';
import { presetScale, type ScaleConfig } from '../../../modules/pdf-takeoff/data/scale-helpers';
import { Button } from '@/shared/ui';
import { takeoffApi, type ScaleDetectionCandidate } from '../api';

export interface ScaleAutoDetectProps {
  /** The uploaded takeoff document id whose text layer should be scanned. */
  documentId: string;
  /** Current 1-based page. A candidate found on this page is preferred over
   *  the document-wide best, since a per-sheet title block can carry its own
   *  scale. Defaults to 1. */
  pageNumber?: number;
  /** Called with a metric-canonical `ScaleConfig` when the user clicks
   *  "Use this". The parent applies it through its existing calibration path
   *  (e.g. `setScale`), exactly as a manual calibration would. */
  onApply: (scale: ScaleConfig) => void;
  /** Optional extra classes for the outer container so the host can position
   *  the widget within its toolbar/sidebar. */
  className?: string;
}

type DetectState =
  | { status: 'loading' }
  | { status: 'found'; candidate: ScaleDetectionCandidate }
  | { status: 'none' };

/**
 * Renders a compact scale-detection affordance for one document/page.
 *
 * Behaviour:
 *  - while the detect request is in flight: renders nothing (quiet, no strip
 *    reserved below the toolbar for a state that offers no action);
 *  - when a scale is found: "Detected scale: 1:100" + the matched evidence +
 *    a "Use this" button;
 *  - when nothing is found (or the request fails / the module is disabled):
 *    renders nothing, so the affordance never blocks the manual calibration
 *    the host already provides and never occupies space with an idle line.
 */
export function ScaleAutoDetect({
  documentId,
  pageNumber = 1,
  onApply,
  className,
}: ScaleAutoDetectProps) {
  const { t } = useTranslation();
  const [state, setState] = useState<DetectState>({ status: 'loading' });

  useEffect(() => {
    if (!documentId) {
      setState({ status: 'none' });
      return;
    }
    let cancelled = false;
    setState({ status: 'loading' });
    void (async () => {
      try {
        const res = await takeoffApi.detectScale(documentId);
        if (cancelled) return;
        if (!res) {
          // Module disabled (null) -> treat as "nothing to suggest".
          setState({ status: 'none' });
          return;
        }
        // Prefer a candidate on the page being calibrated; otherwise the
        // document-wide best. `best` is null when the drawing carries no
        // explicit scale note (an honest empty result, not a guess).
        const forPage = res.candidates.find((c) => c.page === pageNumber);
        const candidate = forPage ?? res.best ?? null;
        setState(candidate ? { status: 'found', candidate } : { status: 'none' });
      } catch {
        // Detection is a best-effort convenience; never surface an error.
        if (!cancelled) setState({ status: 'none' });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [documentId, pageNumber]);

  // Loading and empty states offer no action, so they render nothing rather
  // than occupying a strip below the toolbar on every uncalibrated page
  // (issue #387). The `t` calls above for these copies are now unused here
  // but the translation keys stay registered for any other future surface.
  if (state.status === 'loading') {
    return null;
  }

  if (state.status === 'none') {
    return null;
  }

  const { candidate } = state;

  const handleUse = () => {
    const scale = presetScale(candidate.ratio);
    // `presetScale` returns an explicitly invalid config for a non-positive
    // ratio; refuse to apply one so a bad detection can never poison the
    // viewer's measurements (it stays on the manual path instead).
    if (scale.invalid || scale.pixelsPerUnit <= 0) return;
    onApply(scale);
  };

  return (
    <div
      className={`flex items-center justify-between gap-3 rounded-lg border border-purple-500/30 bg-purple-500/5 px-3 py-2 ${className ?? ''}`}
      data-testid="scale-autodetect-found"
    >
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 text-xs font-medium text-content-primary">
          <Sparkles size={12} className="shrink-0 text-purple-500" />
          {t('takeoff.detect_scale_found', {
            defaultValue: 'Detected scale: {{label}}',
            label: candidate.label,
          })}
        </p>
        {candidate.evidence && (
          <p
            className="mt-0.5 truncate text-[10px] text-content-tertiary"
            title={candidate.evidence}
            data-testid="scale-autodetect-evidence"
          >
            {t('takeoff.detect_scale_evidence', {
              defaultValue: 'Found "{{evidence}}" on page {{page}}',
              evidence: candidate.evidence,
              page: candidate.page,
            })}
          </p>
        )}
      </div>
      <Button
        variant="secondary"
        size="sm"
        onClick={handleUse}
        data-testid="scale-autodetect-use"
      >
        {t('takeoff.detect_scale_use', { defaultValue: 'Use this' })}
      </Button>
    </div>
  );
}

export default ScaleAutoDetect;
