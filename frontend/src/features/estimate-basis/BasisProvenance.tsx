// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Where the numbers came from" - the second question a reviewer asks after
// "how much", and the one the basis of estimate could not answer before.
//
// Every line of a bill records how it got there (`Position.source`) and, when a
// model proposed it, how sure the model was (`Position.confidence`). Those two
// columns are basis-of-estimate facts that were sitting one module away: an
// estimate whose quantities came off a co-ordinated model is a different
// document from one typed into a spreadsheet, and no amount of qualification
// prose substitutes for saying which it is.
//
// The shares are computed over the whole estimate, not a sample, and the block
// says whether they are shares of value or of line count - a bill with no money
// in it cannot be shared out by value, and a percentage that quietly changed
// meaning is worse than no percentage.

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { AlertTriangle, Boxes, ClipboardList, Sparkles } from 'lucide-react';
import { Card, CardContent, CardHeader } from '@/shared/ui';
import { formatCurrency } from '@/shared/lib/money';
import { fmtList, fmtPercent } from '@/shared/lib/formatters';
import type { ProvenanceSummary } from './api';

export interface BasisProvenanceProps {
  provenance: ProvenanceSummary;
  currency?: string;
  /** Where a reader goes to act on what they see here. */
  boqHref: string;
}

/** Tailwind fill per family, strongest evidence first. */
const FAMILY_FILL: Record<string, string> = {
  measured: 'bg-oe-blue',
  imported: 'bg-semantic-info',
  catalogue: 'bg-semantic-success',
  manual: 'bg-content-quaternary',
};

export function BasisProvenance({ provenance, currency, boqHref }: BasisProvenanceProps) {
  const { t } = useTranslation();

  const familyLabel = (family: string): string => {
    switch (family) {
      case 'measured':
        return t('estimateBasis.provenance.family.measured', {
          defaultValue: 'Measured from a drawing or model',
        });
      case 'imported':
        return t('estimateBasis.provenance.family.imported', {
          defaultValue: 'Imported from a supplied bill',
        });
      case 'catalogue':
        return t('estimateBasis.provenance.family.catalogue', {
          defaultValue: 'From a cost database or assembly',
        });
      case 'manual':
        return t('estimateBasis.provenance.family.manual', { defaultValue: 'Entered by hand' });
      default:
        return family;
    }
  };

  const families = provenance?.families ?? [];
  if (families.length === 0) {
    return null;
  }
  const byValue = provenance.share_basis === 'value';

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <Boxes className="h-4 w-4 text-oe-blue" aria-hidden />
            {t('estimateBasis.provenance.title', { defaultValue: 'Where the numbers came from' })}
          </span>
        }
        action={
          <span className="text-xs text-content-tertiary">
            {byValue
              ? t('estimateBasis.provenance.byValue', {
                  defaultValue: 'Share of value · {{count}} line items',
                  count: provenance.total_positions,
                })
              : // No `count` interpolation here on purpose: passing one to a key
                // whose text does not use it still puts i18next into plural
                // resolution, and the singular form nobody wrote would fall
                // through the language chain and print English.
                t('estimateBasis.provenance.byCount', {
                  defaultValue: 'Share of line items - the bill carries no priced value',
                })}
          </span>
        }
      />
      <CardContent className="space-y-3">
        {/* One bar, so the split reads before any of the numbers do. */}
        <div
          className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-secondary"
          role="img"
          aria-label={fmtList(families
            .map((f) => `${familyLabel(f.family)} ${fmtPercent(f.share_pct, 1)}`))}
        >
          {families.map((f) => (
            <span
              key={f.family}
              className={FAMILY_FILL[f.family] ?? 'bg-content-quaternary'}
              style={{ width: `${Math.max(0, Math.min(100, Number(f.share_pct) || 0))}%` }}
            />
          ))}
        </div>

        <ul className="space-y-1.5">
          {families.map((f) => (
            <li key={f.family} className="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span
                className={`h-2.5 w-2.5 shrink-0 rounded-sm ${FAMILY_FILL[f.family] ?? 'bg-content-quaternary'}`}
                aria-hidden
              />
              <span className="text-content-primary">{familyLabel(f.family)}</span>
              <span className="font-medium tabular-nums text-content-primary">
                {fmtPercent(f.share_pct, 1)}
              </span>
              <span className="text-xs text-content-tertiary">
                {t('estimateBasis.provenance.lineCount', {
                  defaultValue: '{{count}} lines',
                  count: f.position_count,
                })}
                {byValue ? ` · ${formatCurrency(f.total, currency)}` : ''}
              </span>
            </li>
          ))}
        </ul>

        {(provenance.low_confidence_count > 0 ||
          provenance.model_linked_positions > 0 ||
          provenance.ai_position_count > 0) && (
          <div className="space-y-1 border-t border-border-light pt-3 text-xs">
            {provenance.ai_position_count > 0 && (
              <p className="flex items-start gap-1.5 text-content-secondary">
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-oe-blue" aria-hidden />
                {t('estimateBasis.provenance.aiLines', {
                  defaultValue: '{{count}} lines were proposed by a model and confirmed by a person.',
                  count: provenance.ai_position_count,
                })}
              </p>
            )}
            {provenance.low_confidence_count > 0 && (
              <p className="flex items-start gap-1.5 text-content-secondary">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-semantic-warning" aria-hidden />
                <Link to={boqHref} className="text-oe-blue-text underline-offset-2 hover:underline">
                  {t('estimateBasis.provenance.lowConfidence', {
                    defaultValue:
                      '{{count}} of them carry a low confidence and are qualified pending review.',
                    count: provenance.low_confidence_count,
                  })}
                </Link>
              </p>
            )}
            {provenance.model_linked_positions > 0 && (
              <p className="flex items-start gap-1.5 text-content-secondary">
                <ClipboardList className="mt-0.5 h-3.5 w-3.5 shrink-0 text-content-tertiary" aria-hidden />
                {t('estimateBasis.provenance.modelLinks', {
                  defaultValue: '{{count}} quantities are driven straight from a model.',
                  count: provenance.model_linked_positions,
                })}
                {provenance.stale_links + provenance.broken_links > 0 && (
                  <Link to={boqHref} className="text-oe-blue-text underline-offset-2 hover:underline">
                    {t('estimateBasis.provenance.staleLinks', {
                      defaultValue: '{{count}} have drifted from the current model.',
                      count: provenance.stale_links + provenance.broken_links,
                    })}
                  </Link>
                )}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
