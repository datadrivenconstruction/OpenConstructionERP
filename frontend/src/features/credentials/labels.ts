// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * How a vocabulary code becomes words on screen.
 *
 * The *set* of codes always comes from the server's `/meta` payload, never from
 * a list in the frontend, so a picker cannot offer a value the API would reject
 * and cannot fall behind a regional pack that extends the vocabulary.
 *
 * The *label* is looked up locally first and falls back to the label the server
 * sent. That order matters: `app/modules/credentials/intl.py` carries four
 * languages, the app carries all of them, so asking the locale bundle first is
 * what stops a Japanese or Polish user reading English labels beside otherwise
 * translated columns. When we have no key, the server's label is still a
 * readable word rather than a raw token like `statutory_membership`.
 */
import type { useTranslation } from 'react-i18next';
import type { CredentialsMeta, HolderKind } from './api';

type Translate = ReturnType<typeof useTranslation>['t'];

/** Last resort for a code no table knows: `statutory_membership` -> `Statutory membership`. */
export function humanise(code: string): string {
  const s = code.replace(/_/g, ' ').trim();
  return s === '' ? code : s.charAt(0).toUpperCase() + s.slice(1);
}

export function typeLabel(code: string, meta: CredentialsMeta | undefined, t: Translate): string {
  const server = meta?.credential_types.find((o) => o.code === code)?.label;
  return t(`credentials.type.${code}`, { defaultValue: server ?? humanise(code) });
}

export function statusLabel(code: string, meta: CredentialsMeta | undefined, t: Translate): string {
  const server = meta?.statuses.find((o) => o.code === code)?.label;
  return t(`credentials.status.${code}`, { defaultValue: server ?? humanise(code) });
}

export function holderKindLabel(kind: HolderKind | string, t: Translate): string {
  return t(`credentials.holder_kind.${kind}`, {
    defaultValue: kind === 'company' ? 'Company' : 'Person',
  });
}
