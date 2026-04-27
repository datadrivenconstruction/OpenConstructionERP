// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Collapsible hint panel listing the 8 supported NL → DSL patterns.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Lightbulb } from 'lucide-react';
import type { NlPattern } from './api';

interface NlPatternHintsProps {
  patterns: NlPattern[];
  /** Optional click-to-fill: passes the pattern's example back. */
  onPick?: (example: string) => void;
}

/* Hard-coded examples per pattern_id. The label/template is
   translated via the backend's `name_key`; the example string is
   intentionally a *fillable* English snippet that always parses. */
const PATTERN_EXAMPLES: Record<string, string> = {
  must_have: 'all walls must have fire_rating',
  must_not_have: 'no position can have status = draft',
  value_equals: 'every wall must have material equal to concrete',
  value_greater_than: 'every position must have quantity greater than 0',
  value_less_than: 'every wall must have thickness less than 0.5',
  value_at_least: 'every wall must have fire_rating at least 60',
  count_at_least: 'there must be at least 3 walls',
  count_zero: 'no draft positions allowed',
};

export function NlPatternHints({ patterns, onPick }: NlPatternHintsProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);

  return (
    <div
      className="rounded-lg border border-border-light bg-surface-primary"
      data-testid="nl-pattern-hints"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid="nl-pattern-hints-toggle"
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <Lightbulb size={14} className="text-oe-blue" />
          {t('compliance.nl.patterns_title', { defaultValue: 'Supported patterns' })}
        </span>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      {open && (
        <ul className="space-y-1 border-t border-border-light px-3 py-3">
          {patterns.map((p) => {
            const example = PATTERN_EXAMPLES[p.pattern_id] ?? '';
            const label = t(p.name_key, { defaultValue: p.pattern_id });
            return (
              <li
                key={p.pattern_id}
                data-testid={`nl-pattern-${p.pattern_id}`}
                className="rounded-md px-2 py-1.5 hover:bg-surface-secondary"
              >
                <div className="text-xs font-medium text-content-primary">
                  {label}
                </div>
                {example && (
                  <button
                    type="button"
                    onClick={() => onPick?.(example)}
                    className="mt-0.5 block w-full text-left font-mono text-[11px] text-content-tertiary hover:text-oe-blue"
                  >
                    {example}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
