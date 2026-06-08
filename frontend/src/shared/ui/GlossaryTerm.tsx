/**
 * <GlossaryTerm> — surfaces one shared glossary definition next to a
 * label, so a term reads identically everywhere it appears.
 *
 * It is a thin wrapper over <InfoHint>: it reads `glossary.<term>` (and
 * the optional one-line `glossary.<term>_example`) and shows them in the
 * existing (i) popover. It deliberately does NOT grow its own
 * positioning/popover code — all the behaviour lives in InfoHint.
 *
 * If the glossary key has no definition yet, the label is rendered on
 * its own (no empty popover), so adding the term to the dictionary later
 * lights up the hint without touching call sites.
 */

import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { InfoHint } from './InfoHint';

export interface GlossaryTermProps {
  /** Key suffix: `evm` reads `glossary.evm` (+ `glossary.evm_example`). */
  term: string;
  /** Optional visible label before the (i), usually "Plain (jargon)". */
  label?: ReactNode;
  className?: string;
}

export function GlossaryTerm({ term, label, className }: GlossaryTermProps) {
  const { t } = useTranslation();

  const def = t(`glossary.${term}`, { defaultValue: '' });
  const example = t(`glossary.${term}_example`, { defaultValue: '' });

  if (!def) {
    return label ? <span className={className}>{label}</span> : null;
  }

  const text = example
    ? `${def} ${t('glossary.example_prefix', { defaultValue: 'Example:' })} ${example}`
    : def;

  return (
    <span className={clsx('inline-flex items-center gap-1', className)}>
      {label}
      <InfoHint inline text={text} />
    </span>
  );
}
