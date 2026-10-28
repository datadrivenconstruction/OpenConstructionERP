// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ClaimPeriod — a progress claim's period, "from → to", the one way both the
// claims list and the claim's own header print it.
//
// The parsed dates come first: they are what orders the claim among the
// contract's claims, so they are the period the rest of the app works with.
// The typed string is the fallback, for a claim written before the parsed
// dates existed or one whose string the server could not read. An ISO date
// among those is still formatted; anything else is shown as it was typed,
// because the date formatter would turn it into a dash and hide the very
// thing the claim's submission check is complaining about.

import { DateDisplay } from '@/shared/ui/DateDisplay';
import type { ProgressClaimItem } from './api';

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

type PeriodFields = Pick<ProgressClaimItem, 'period_start' | 'period_end' | 'period_from' | 'period_to'>;

function Bound({ parsed, typed }: { parsed: string | null | undefined; typed: string | null }) {
  if (parsed) return <DateDisplay value={parsed} />;
  const text = typed?.trim() ?? '';
  if (ISO_DATE.test(text)) return <DateDisplay value={text} />;
  if (text) return <span>{text}</span>;
  return <span className="text-content-tertiary">&mdash;</span>;
}

export function ClaimPeriod({ claim }: { claim: PeriodFields }) {
  return (
    <>
      <Bound parsed={claim.period_from} typed={claim.period_start} />
      {' → '}
      <Bound parsed={claim.period_to} typed={claim.period_end} />
    </>
  );
}
