/**​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * Offer, on a new model version, to re-apply the quantity rules that priced
 * the version it replaces.
 *
 * Nothing is applied from here. Each button opens a BOQ's change review on
 * its BIM quantities tab, which recomputes the rules on the newest version,
 * shows old against new per position and writes only what a person accepts.
 * Applying the rules to the new model directly would create a second set of
 * links next to the old ones and count the elements twice.
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Calculator, X } from 'lucide-react';
import { fetchQuantityRuleOffer } from './api';

const DISMISS_PREFIX = 'oe.bim.ruleOfferDismissed.';

function readDismissed(modelId: string): boolean {
  try {
    return window.localStorage.getItem(DISMISS_PREFIX + modelId) === '1';
  } catch {
    return false;
  }
}

function writeDismissed(modelId: string): void {
  try {
    window.localStorage.setItem(DISMISS_PREFIX + modelId, '1');
  } catch {
    // Storage blocked: the banner still closes for this visit.
  }
}

export function QuantityRuleOfferBanner({ modelId }: { modelId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [dismissed, setDismissed] = useState(() => readDismissed(modelId));
  useEffect(() => setDismissed(readDismissed(modelId)), [modelId]);

  const offer = useQuery({
    queryKey: ['bim-quantity-rule-offer', modelId],
    queryFn: () => fetchQuantityRuleOffer(modelId),
    enabled: !dismissed,
    staleTime: 60_000,
    retry: false,
  });

  // A failed lookup shows nothing: the offer is a shortcut, and the BOQ's
  // change review button still finds the same proposals.
  if (dismissed || !offer.data || offer.data.rule_count === 0 || offer.data.boqs.length === 0) return null;

  return (
    <div className="absolute top-3 left-1/2 -translate-x-1/2 z-30 w-[calc(100%-2rem)] max-w-xl">
      <div
        role="status"
        data-testid="bim-rule-offer"
        className="flex items-start gap-3 rounded-xl border border-blue-200 dark:border-blue-800 bg-blue-50/95 dark:bg-blue-950/60 px-4 py-3 shadow-md backdrop-blur-sm"
      >
        <Calculator size={16} className="mt-0.5 shrink-0 text-oe-blue" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-content-primary">
            {t('bim.rule_offer_title', {
              count: offer.data.rule_count,
              defaultValue: 'Re-apply {{count}} quantity rules to the new version',
            })}
          </p>
          <p className="mt-0.5 text-xs text-content-secondary">
            {t('bim.rule_offer_body', {
              defaultValue:
                'They priced BOQ positions from the earlier version. Review the changed quantities first; nothing changes until you accept.',
            })}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {offer.data.boqs.map((boq) => (
              <button
                key={boq.boq_id}
                type="button"
                data-testid={`bim-rule-offer-boq-${boq.boq_id}`}
                onClick={() => navigate(`/boq/${encodeURIComponent(boq.boq_id)}?review=quantities`)}
                className="rounded-lg border border-oe-blue/40 bg-surface-primary px-2.5 py-1 text-xs font-medium text-oe-blue hover:bg-oe-blue hover:text-white transition-colors"
              >
                {t('bim.rule_offer_review', { defaultValue: 'Review in {{boq}}', boq: boq.boq_name || boq.boq_id })}
              </button>
            ))}
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            writeDismissed(modelId);
            setDismissed(true);
          }}
          aria-label={t('bim.rule_offer_dismiss', { defaultValue: 'Dismiss' })}
          className="shrink-0 rounded p-0.5 text-content-tertiary hover:text-content-primary"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
