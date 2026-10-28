// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Why the closed buttons of a record are closed, as text beside them. A
// tooltip alone is invisible on a touch screen and to anyone who does not
// hover, so the server's reason is also written out, once per reason.
//
// A reason every row of a list shares is written once above the list and
// left off the rows, so a reader without edit rights does not read the same
// sentence on every line.

import { useTranslation } from 'react-i18next';

import type { Capable } from './api';
import { humanizeCode } from './labels';
import { closedReasons } from './rules';

/** The sentences of the given reason codes; nothing when there are none. */
export function ReasonLines({ codes, testId = 'closed-reason' }: { codes: readonly string[]; testId?: string }) {
  const { t } = useTranslation();
  if (codes.length === 0) return null;
  return (
    <p className="w-full basis-full text-xs text-content-tertiary" data-testid={testId}>
      {codes.map((code) => (
        <span key={code} className="block">
          {t(`quality_concept.errors.${code}`, { defaultValue: humanizeCode(code) })}
        </span>
      ))}
    </p>
  );
}

/** The reasons of one record's closed buttons, minus those already written above its list. */
export function ClosedReasons({
  row,
  actions,
  skip = [],
}: {
  row: Capable | null | undefined;
  actions: readonly string[];
  skip?: readonly string[];
}) {
  return <ReasonLines codes={closedReasons(row, actions).filter((code) => !skip.includes(code))} />;
}

/** The reasons every row of a list shares, written once above it. */
export function SharedReasons({ codes }: { codes: readonly string[] }) {
  return <ReasonLines codes={codes} testId="closed-reason-shared" />;
}
