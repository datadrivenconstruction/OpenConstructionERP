// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Readiness banner shown at the top of the AI Estimate Builder. It states
// plainly which capabilities are live and links to AI settings when the
// LLM key is missing. Never blocks the flow - the module degrades to
// deterministic matching - it only sets expectations.

import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BrainCircuit, Database, CheckCircle2, AlertTriangle, ArrowRight } from 'lucide-react';
import clsx from 'clsx';
import type { AiReadiness } from '../useAiReadiness';

function Chip({
  ready,
  icon,
  label,
  detail,
}: {
  ready: boolean;
  icon: React.ReactNode;
  label: string;
  detail: string;
}) {
  return (
    <div
      className={clsx(
        'flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs',
        ready
          ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-900/20 dark:text-emerald-200'
          : 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-200',
      )}
    >
      <span className="shrink-0">{icon}</span>
      <span className="font-medium">{label}</span>
      <span className="opacity-80">{detail}</span>
      {ready ? (
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
      ) : (
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
      )}
    </div>
  );
}

export function AiStatusBanner({ readiness }: { readiness: AiReadiness }) {
  const { t } = useTranslation();
  const { llmReady, vectorReady, preferredModel } = readiness;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2.5">
      <Chip
        ready={llmReady}
        icon={<BrainCircuit className="h-4 w-4" />}
        label={t('aiest.status.ai_label', { defaultValue: 'AI agent' })}
        detail={
          llmReady
            ? preferredModel || t('aiest.status.connected', { defaultValue: 'connected' })
            : t('aiest.status.not_connected', { defaultValue: 'not connected' })
        }
      />
      <Chip
        ready={vectorReady}
        icon={<Database className="h-4 w-4" />}
        label={t('aiest.status.vector_label', { defaultValue: 'Rate retrieval' })}
        detail={
          vectorReady
            ? t('aiest.status.vector_ready', { defaultValue: 'semantic search ready' })
            : t('aiest.status.vector_lexical', { defaultValue: 'keyword fallback' })
        }
      />
      {!llmReady && (
        <Link
          to="/settings?tab=ai"
          className="inline-flex items-center gap-1 rounded-full border border-oe-blue/30 bg-surface-primary px-3 py-1.5 text-xs font-semibold text-oe-blue transition-colors hover:bg-oe-blue hover:text-content-inverse"
        >
          {t('aiest.status.connect_ai', { defaultValue: 'Connect an AI provider' })}
          <ArrowRight className="h-3 w-3" />
        </Link>
      )}
    </div>
  );
}
