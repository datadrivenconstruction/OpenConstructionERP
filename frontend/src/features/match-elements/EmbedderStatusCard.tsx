// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Free / open-source language model readiness card for /match-elements.
//
// Surfaces BGE-M3 install state ABOVE Step 1 (model picker), because if
// the encoder is missing the rest of the workflow simply will not
// produce semantic candidates. Two states:
//
//   installed=true  → compact green pill (collapsible), "MIT · 100+
//                     languages · runs locally" reassurance + model id.
//   installed=false → amber gradient install card with one-line pip
//                     command, copy button, trust strip.
//
// Always renders 200; the backend distinguishes states from the JSON
// payload, not from HTTP status (see costs/router.py:embedder_status).

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useQuery } from '@tanstack/react-query';
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Copy,
  Cpu,
  ExternalLink,
  Loader2,
  Sparkles,
} from 'lucide-react';

import { copyToClipboard } from '@/shared/lib/browser';

import { fetchEmbedderStatus, type EmbedderStatus } from './api';

function CopyableCommand({ command }: { command: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const handle = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(handle);
  }, [copied]);

  const onCopy = async () => {
    try {
      await copyToClipboard(command);
      setCopied(true);
    } catch {
      // Fallback: select-and-prompt; clipboard may be blocked under
      // insecure origin or strict permissions policy.
      window.prompt(t('match_elements.embedder_copy_command', 'Copy command'), command);
    }
  };

  return (
    <div className="flex items-stretch gap-0 rounded-lg border border-semantic-warning/30 overflow-hidden font-mono text-sm bg-white dark:bg-surface-primary">
      <code className="flex-1 px-3 py-2 overflow-x-auto whitespace-nowrap text-content-primary select-all">
        {command}
      </code>
      <button
        type="button"
        onClick={onCopy}
        className="shrink-0 inline-flex items-center gap-1.5 px-3 border-l border-semantic-warning/30 bg-semantic-warning/10 hover:bg-semantic-warning/10 text-semantic-warning text-xs font-semibold transition"
        aria-label={t('match_elements.embedder_copy_command', 'Copy command')}
      >
        {copied ? (
          <>
            <CheckCircle2 className="w-3.5 h-3.5" />
            {t('match_elements.embedder_copied', 'Copied')}
          </>
        ) : (
          <>
            <Copy className="w-3.5 h-3.5" />
            {t('match_elements.embedder_copy_command', 'Copy command')}
          </>
        )}
      </button>
    </div>
  );
}

function TrustBadges({ status }: { status: EmbedderStatus }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-2xs">
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-semantic-success-bg border border-semantic-success/30 text-semantic-success font-medium">
        {status.license}
      </span>
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-semantic-info-bg border border-semantic-info/30 text-semantic-info font-medium">
        {t('match_elements.embedder_languages_caption', '{{n}}+ languages', {
          n: status.languages_supported,
        })}
      </span>
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-200 dark:border-indigo-800 text-indigo-800 dark:text-indigo-200 font-medium">
        {t('match_elements.embedder_runs_locally', 'Runs locally')}
      </span>
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-secondary border border-border-light text-content-secondary font-medium">
        {t('match_elements.embedder_no_api_key', 'No API key')}
      </span>
    </div>
  );
}

function LoadedState({ status }: { status: EmbedderStatus }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const sizeMb = status.int8_mode ? status.size_mb_int8 : status.size_mb_fp32;
  const precision = status.int8_mode ? 'INT8 ONNX' : 'FP32';

  return (
    <div className="rounded-xl border border-semantic-success/30 bg-semantic-success/10">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2.5 px-3 py-2 text-left"
        aria-expanded={open}
      >
        <span className="shrink-0 w-6 h-6 rounded-md bg-semantic-success text-white inline-flex items-center justify-center">
          <CheckCircle2 className="w-3.5 h-3.5" />
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-semantic-success leading-tight">
            {t('match_elements.embedder_loaded_title', 'Language model ready')}
          </div>
          <div className="text-2xs text-emerald-800/80 dark:text-emerald-200/80 truncate">
            {t(
              'match_elements.embedder_loaded_caption',
              '{{model}} · {{precision}} · ~{{size}} MB · {{license}} · {{n}}+ languages',
              {
                model: status.model_name,
                precision,
                size: sizeMb,
                license: status.license,
                n: status.languages_supported,
              },
            )}
          </div>
        </div>
        {open ? (
          <ChevronUp className="w-4 h-4 text-semantic-success shrink-0" />
        ) : (
          <ChevronDown className="w-4 h-4 text-semantic-success shrink-0" />
        )}
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 border-t border-semantic-success/30 pt-2">
          <TrustBadges status={status} />
          <div className="text-2xs text-content-tertiary">
            {t(
              'match_elements.embedder_runtime_caption',
              'Runtime: {{runtime}} · model_loaded={{loaded}}',
              {
                runtime: status.model_id_runtime,
                loaded: status.model_loaded ? 'true' : 'false',
              },
            )}
          </div>
          <a
            href={status.homepage}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-2xs text-semantic-success underline hover:opacity-80"
          >
            <ExternalLink className="w-3 h-3" />
            {t('match_elements.embedder_homepage_link', 'Model homepage')}
          </a>
        </div>
      )}
    </div>
  );
}

/**
 * Choose the sentence that tells the reader how to get the model, in their
 * language wherever that is possible.
 *
 * Three tiers, tried in order, and the last one can never come back empty:
 *
 *  1. A reason code this build recognises, which resolves to a locale string.
 *     This is the only tier that is translated, and it is why the code exists.
 *  2. Anything else - no code, or a code from a newer backend - falls back to
 *     the backend's own prose when it sent any. English, but accurate, and a
 *     frontend that ignored an unrecognised shape and rendered nothing would
 *     be worse than one showing English.
 *  3. Nothing usable at all: the general sentence, which is true on every
 *     install and is what a backend too old to carry either field produces.
 *
 * The switch is deliberately not exhaustive over
 * {@link EmbedderInstallHintCode}: the wire type is `string` precisely so a
 * value invented after this build ships lands in tier 2 rather than in a
 * branch nobody wrote.
 */
export function installSentence(status: EmbedderStatus, t: TFunction): string {
  const general = () =>
    t(
      'match_elements.embedder_required_body',
      'OpenConstructionERP uses BGE-M3 - a free, open-source multilingual encoder by BAAI. It runs entirely on your machine. No API key. No cloud calls. Install once with one command:',
    );

  if (status.install_hint_code === 'frozen_no_extra') {
    return t(
      'match_elements.embedder_required_frozen',
      'OpenConstructionERP uses BGE-M3, a free, open-source multilingual encoder by BAAI that runs entirely on your machine. This desktop build ships a fixed set of packages, so the model cannot be added here. Use the server install, or a desktop build that already includes it.',
    );
  }
  if (status.install_hint_code === 'pip') return general();

  const prose = (status.install_hint ?? '').trim();
  return prose || general();
}

function MissingState({ status }: { status: EmbedderStatus }) {
  const { t } = useTranslation();
  const sizeInt8 = status.size_mb_int8;
  const sizeFp32 = status.size_mb_fp32;
  // Whether there is a command to copy is a mechanical fact about the
  // payload, and stays separate from which sentence to show: a frozen
  // desktop build has no pip, so the backend sends an empty pip_command and
  // rendering the box anyway would offer an empty command to copy.
  const pipRoute = status.pip_command.length > 0;
  return (
    <div className="rounded-xl border border-semantic-warning/30 bg-gradient-to-br from-amber-50 via-amber-50 to-orange-50 dark:from-amber-950/40 dark:via-amber-950/30 dark:to-orange-950/30 p-4 space-y-3">
      <div className="flex items-start gap-3">
        <span className="shrink-0 w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 text-white inline-flex items-center justify-center shadow-sm shadow-amber-500/30">
          <Cpu className="w-5 h-5" />
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-semantic-warning leading-tight">
              {t(
                'match_elements.embedder_required_title',
                'Free language model required',
              )}
            </h3>
            <Sparkles className="w-3.5 h-3.5 text-semantic-warning" />
          </div>
          <div className="mt-0.5">
            <TrustBadges status={status} />
          </div>
          <p className="mt-2 text-sm text-amber-900/90 dark:text-amber-100/90 leading-relaxed">
            {installSentence(status, t)}
          </p>
        </div>
      </div>

      {pipRoute && (
        <>
          <CopyableCommand command={status.pip_command} />

          <div className="text-2xs text-amber-900/80 dark:text-amber-100/80">
            {t(
              'match_elements.embedder_install_hint_after',
              'After install, restart the backend.',
            )}{' '}
            <span className="text-amber-800/70 dark:text-amber-200/70">
              {t(
                'match_elements.embedder_size_caption',
                '~{{int8}} MB download (INT8) or ~{{fp32}} MB (FP32).',
                { int8: sizeInt8, fp32: sizeFp32 },
              )}
            </span>
          </div>
        </>
      )}

      <div className="text-2xs text-amber-900/80 dark:text-amber-100/80 pt-1 border-t border-semantic-warning/30 dark:border-amber-800/60">
        <a
          href={status.homepage}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 underline hover:opacity-80"
        >
          <ExternalLink className="w-3 h-3" />
          {t('match_elements.embedder_homepage_link', 'Model homepage')}
        </a>
      </div>
    </div>
  );
}

/** EmbedderStatusCard — language-model readiness for /match-elements.
 *  Renders nothing while loading (silent on first paint to avoid layout
 *  jitter); shows green compact pill when installed; amber install card
 *  when missing. */
export function EmbedderStatusCard() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['embedder-status'],
    queryFn: fetchEmbedderStatus,
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 1,
  });

  if (q.isLoading) {
    return (
      <div
        className="rounded-xl border border-border bg-surface-primary px-3 py-2 text-xs text-content-tertiary inline-flex items-center gap-2"
        role="status"
        aria-live="polite"
      >
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        {t('match_elements.embedder_loading', 'Checking language model…')}
      </div>
    );
  }

  if (q.isError || !q.data) {
    // Soft-fail: if /embedder/status/ itself is unreachable, the rest of
    // the page still works — render nothing rather than blocking the user.
    return null;
  }

  const status = q.data;
  return status.installed ? (
    <LoadedState status={status} />
  ) : (
    <MissingState status={status} />
  );
}
