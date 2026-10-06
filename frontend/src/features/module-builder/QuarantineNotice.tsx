// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A built module the server switched off for safety, in plain words.
 *
 * The server leaves a module unloaded when its files hold code its description
 * does not produce (`unsafe_code`, with the files in `params.files`) or when it
 * cannot check them at all (`unverifiable`, built by an older builder). Its
 * records are kept and its address answers nothing, so the screens say so and
 * point at the two ways out: remove it, or build it again under the same name.
 */
import { useTranslation } from 'react-i18next';
import { ShieldAlert } from 'lucide-react';

import { Badge } from '@/shared/ui';
import { fmtList } from '@/shared/lib/formatters';

import type { ModuleProblem } from './api';

/** Translated as `module_builder.quarantine.<code>`; any other code reads as `.other`. */
export const QUARANTINE_TEXT: Record<string, string> = {
  unsafe_code:
    'This module was switched off because its files contain code that its description does not produce ({{files}}). Its records are kept. Remove it, or build it again from the builder.',
  unverifiable:
    'This module was switched off because it was built by an older version of the builder and could not be checked. Its records are kept. Remove it, or build it again from the builder.',
};
export const QUARANTINE_FALLBACK =
  'This module was switched off for safety. Its records are kept. Remove it, or build it again from the builder.';

export function QuarantineBadge() {
  const { t } = useTranslation();
  return (
    <Badge variant="error" size="sm">
      {t('module_builder.quarantine.badge', { defaultValue: 'Switched off for safety' })}
    </Badge>
  );
}

export function QuarantineMessage({ problem, testId }: { problem: ModuleProblem | null | undefined; testId?: string }) {
  const { t } = useTranslation();
  const code = problem?.code ?? '';
  const listed = problem?.params?.files;
  const files = Array.isArray(listed)
    ? fmtList(
        listed.filter((f): f is string => typeof f === 'string'),
        'prose',
      )
    : '';
  return (
    <p className="flex items-start gap-2 text-xs text-semantic-error" role="status" data-testid={testId}>
      <ShieldAlert size={14} className="mt-px shrink-0" />
      <span>
        {t(`module_builder.quarantine.${code in QUARANTINE_TEXT ? code : 'other'}`, {
          files,
          defaultValue: QUARANTINE_TEXT[code] ?? QUARANTINE_FALLBACK,
        })}
      </span>
    </p>
  );
}
