// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * ElementCostMatchPanel - the ONE shared "match a selected element to a
 * cost position" surface embedded in every file/model viewer (BIM, PDF
 * takeoff, DWG/DXF). Given a selected element it:
 *
 *   1. sends the element's properties to POST /v1/match/element, which
 *      searches every loaded CWICR catalogue and ranks candidates;
 *   2. renders the ranked candidates via <MatchSuggestionsPanel>;
 *   3. on Accept, calls POST /v1/match/accept to create (or update) a
 *      priced BOQ position from the chosen candidate in one transaction,
 *      optionally linking a BIM element, then runs an optional viewer-
 *      specific back-link (onApplied) so the element also shows as linked
 *      inside its own viewer (PDF measurement, DWG annotation).
 *
 * The search/rank/feedback panel below is already source-agnostic; this
 * wrapper owns the target-BOQ picker and the accept-and-link step so a
 * viewer only has to hand in its selected element. Keeping this in one
 * place stops the BIM, PDF and DWG integrations from drifting into three
 * near-identical copies.
 *
 * The parent decides WHEN to render this (only when an element is
 * selected) - the wrapper assumes it is given a real element.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { MatchSuggestionsPanel } from './MatchSuggestionsPanel';
import { useAcceptMatch } from './queries';
import type {
  ElementEnvelope,
  MatchAcceptResponse,
  MatchCandidate,
  MatchSource,
} from './types';
import { boqApi, type BOQ } from '@/features/boq/api';
import { useToastStore } from '@/stores/useToastStore';

/** Fields the wrapper needs to rebuild the match envelope on accept. The
 *  raw search payload (``rawElementData``) is separate because the backend
 *  extractor promotes known keys out of the free-form shape at search time,
 *  while accept persists an explicit, normalised envelope. */
export interface ElementCostMatchEnvelope {
  category: string;
  description: string;
  properties?: Record<string, unknown>;
  quantities?: Record<string, number>;
  sourceLang?: string;
  unitHint?: string | null;
}

export interface ElementCostMatchPanelProps {
  source: MatchSource;
  projectId: string;
  /** Stable id of the selected element; remounts the panel per element and
   *  resets the panel's per-element rejection accumulator. */
  elementKey: string;
  /** Free-form element payload for POST /v1/match/element (backend extracts
   *  description / category / quantities / properties from the shape). */
  rawElementData: Record<string, unknown>;
  /** Fields used to build the normalised envelope written on accept. */
  envelope: ElementCostMatchEnvelope;
  /** When set, match/accept links this BIM element to the new position in
   *  the same transaction (BIM viewer). PDF/DWG leave this null and do
   *  their own native back-link via ``onApplied``. */
  bimElementId?: string | null;
  /** Quantity stamped on the created position (the measured value for PDF
   *  and DWG). Null lets the backend infer it from the element quantities. */
  quantityOverride?: number | null;
  /** Viewer-specific native back-link, run after the position is created
   *  (e.g. link a PDF measurement or a DWG annotation to the new position).
   *  Throwing here is non-fatal - the priced position still exists. */
  onApplied?: (
    result: MatchAcceptResponse,
    candidate: MatchCandidate,
  ) => void | Promise<void>;
  compact?: boolean;
  className?: string;
}

export function ElementCostMatchPanel({
  source,
  projectId,
  elementKey,
  rawElementData,
  envelope,
  bimElementId = null,
  quantityOverride = null,
  onApplied,
  compact = false,
  className,
}: ElementCostMatchPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const acceptMutation = useAcceptMatch();

  // Target BOQ - the position has to land somewhere. A project can hold
  // several BOQs (variants, packages, versions), so default to the first
  // but let the user switch.
  const boqsQuery = useQuery({
    queryKey: ['boqs-for-link', projectId],
    queryFn: () => boqApi.list(projectId),
    enabled: Boolean(projectId),
  });
  const boqs: BOQ[] = useMemo(() => boqsQuery.data ?? [], [boqsQuery.data]);
  const [userSelectedBOQId, setUserSelectedBOQId] = useState<string | null>(null);
  const selectedBOQId = useMemo<string | null>(() => {
    if (userSelectedBOQId && boqs.some((b) => b.id === userSelectedBOQId)) {
      return userSelectedBOQId;
    }
    return boqs[0]?.id ?? null;
  }, [boqs, userSelectedBOQId]);

  const handleAccept = async (candidate: MatchCandidate) => {
    if (!selectedBOQId) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: t('match.no_boq_picked', {
          defaultValue:
            'Pick a target BOQ before accepting a match - there is no BOQ in this project yet.',
        }),
      });
      return;
    }

    const builtEnvelope: ElementEnvelope = {
      source,
      source_lang: envelope.sourceLang ?? 'en',
      category: envelope.category ?? '',
      description: envelope.description ?? '',
      properties: envelope.properties ?? {},
      quantities: envelope.quantities ?? {},
      unit_hint: envelope.unitHint ?? null,
      classifier_hint: null,
    };

    try {
      const result = await acceptMutation.mutateAsync({
        project_id: projectId,
        element_envelope: builtEnvelope,
        accepted_candidate: candidate,
        rejected_candidates: [],
        boq_id: selectedBOQId,
        bim_element_id: bimElementId,
        quantity_override: quantityOverride,
      });

      // Viewer-specific native back-link (PDF measurement / DWG annotation).
      // The BIM viewer links server-side via ``bim_element_id`` and passes
      // no ``onApplied``. A back-link failure is non-fatal - the priced
      // position is already in the BOQ either way.
      if (onApplied) {
        try {
          await onApplied(result, candidate);
        } catch {
          /* non-critical: the priced position is already in the BOQ */
        }
      }

      addToast({
        type: 'success',
        title: t('match.accept_toast_title', { defaultValue: 'Match accepted' }),
        // i18next-strict typing: when the key isn't statically known the
        // overload resolver picks the 2-arg ``[key, defaultValue]`` form and
        // rejects the interpolation object. Cast to ``string`` so we can pass
        // the rich options form - runtime behaviour is identical.
        message: (t as (k: string, opts: Record<string, unknown>) => string)(
          'match.accept_position_toast',
          {
            defaultValue:
              'Position {{ordinal}} created - {{code}}: {{description}}',
            ordinal: result.position_ordinal,
            code: candidate.code,
            description: candidate.description,
          },
        ),
      });
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message ?? String(err);
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: msg,
      });
    }
  };

  return (
    <div className={clsx('flex flex-col h-full', className)}>
      <div className="px-3 py-2 border-b border-border-light bg-surface-secondary">
        <label className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-1">
          {t('match.target_boq', { defaultValue: 'Target BOQ' })}
        </label>
        <select
          value={selectedBOQId ?? ''}
          onChange={(e) => setUserSelectedBOQId(e.target.value || null)}
          disabled={boqs.length === 0}
          className="w-full px-2 py-1 text-xs rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
          data-testid="match-target-boq-select"
        >
          {boqs.length === 0 ? (
            <option value="">
              {t('match.no_boqs', { defaultValue: 'No BOQs in this project yet' })}
            </option>
          ) : (
            boqs.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))
          )}
        </select>
      </div>
      <div className="flex-1 min-h-0">
        <MatchSuggestionsPanel
          key={elementKey}
          source={source}
          projectId={projectId}
          rawElementData={rawElementData}
          onAccept={handleAccept}
          autoFetch
          compact={compact}
        />
      </div>
    </div>
  );
}

export default ElementCostMatchPanel;
