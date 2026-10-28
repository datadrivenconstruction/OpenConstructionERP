// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Deterministic-mode notice. When the run reports a degraded_reason the
// pipeline still works - it just falls back to deterministic extraction,
// signature grouping and lexical rate lookup. This banner says plainly
// what is missing and how to restore the full path, so a missing AI key
// or empty vector DB never reads as a failure. Rates are still grounded
// in the cost database in every mode; the AI never invents a number.

import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Info, ArrowRight } from 'lucide-react';
import type { DegradedReason } from '../api';

export function DegradedBanner({ reason }: { reason: DegradedReason | null | undefined }) {
  const { t } = useTranslation();
  if (!reason) return null;

  let body: string;
  let cta: { to: string; label: string } | null = null;

  switch (reason) {
    case 'no_ai_key':
      body = t('aiest.degraded.no_ai_key', {
        defaultValue:
          'AI not connected - running in deterministic mode. The agent reads, groups and matches using rule-based extraction and keyword search. Connect a provider to add AI reasoning at every stage.',
      });
      cta = {
        to: '/settings?tab=ai',
        label: t('aiest.degraded.connect', { defaultValue: 'Connect an AI provider' }),
      };
      break;
    case 'no_vectors':
      body = t('aiest.degraded.no_vectors', {
        defaultValue:
          'Semantic rate search is unavailable, so matching uses keyword lookup. Scores may be lower but every rate still comes from the cost database. Install a catalogue vector index for sharper matches.',
      });
      cta = {
        to: '/match-elements',
        label: t('aiest.degraded.install_vectors', { defaultValue: 'Manage rate retrieval' }),
      };
      break;
    case 'no_catalogue':
      body = t('aiest.degraded.no_catalogue', {
        defaultValue:
          'No cost catalogue is loaded for this currency or region, so groups come back without rates. Load a catalogue to ground the estimate - rates are never invented.',
      });
      cta = {
        to: '/costs',
        label: t('aiest.degraded.load_catalogue', { defaultValue: 'Load a catalogue' }),
      };
      break;
    default:
      body = t('aiest.degraded.generic', {
        defaultValue: 'Running in deterministic mode. Some AI features are unavailable.',
      });
  }

  return (
    <div
      role="status"
      className="flex flex-wrap items-start gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2.5 text-xs text-amber-900 dark:border-amber-700/50 dark:bg-amber-900/20 dark:text-amber-100"
    >
      <Info className="mt-0.5 h-4 w-4 shrink-0" />
      <p className="min-w-0 flex-1 leading-snug">{body}</p>
      {cta && (
        <Link
          to={cta.to}
          className="inline-flex shrink-0 items-center gap-1 rounded-full border border-amber-500/40 bg-surface-primary px-2.5 py-1 font-semibold text-amber-800 transition-colors hover:bg-amber-500 hover:text-white dark:text-amber-100"
        >
          {cta.label}
          <ArrowRight className="h-3 w-3" />
        </Link>
      )}
    </div>
  );
}
