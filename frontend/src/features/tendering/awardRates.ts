// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { TFunction } from 'i18next';

/** What `POST /packages/{id}/apply-winner/` answers. */
export interface AwardResult {
  package_id: string;
  bid_id: string;
  positions_updated: number;
  /** Why no rate went into the bill, or null when rates were written. */
  rates_skipped_reason?: 'boq_locked' | 'no_line_rates' | null;
  boq_id: string;
}

/**
 * The sentence the award toast uses for what happened to the bill.
 *
 * An award writes the winning line rates into the BOQ only where it honestly
 * can: never into a locked bill, and not at all for a bid priced as a lump sum.
 * The toast says which, so nobody opens the estimate expecting rates that were
 * never written.
 */
export function awardRatesMessage(result: AwardResult | undefined, t: TFunction): string {
  switch (result?.rates_skipped_reason) {
    case 'boq_locked':
      return t('tendering.award_rates_locked', {
        defaultValue: 'The BOQ is locked, so its rates were left as approved.',
      });
    case 'no_line_rates':
      return t('tendering.award_rates_lump_sum', {
        defaultValue: 'The winning bid has no line rates (lump sum), so the BOQ rates were not changed.',
      });
    default:
      return t('tendering.award_rates_written', {
        defaultValue: 'BOQ positions updated with the winning rates: {{n}}.',
        n: result?.positions_updated ?? 0,
      });
  }
}
