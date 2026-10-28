// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Use imported catalogues in CAD-BIM Match": index an imported price list
 * (a regional prezzario, say) so Match can suggest its items.
 *
 * Match searches its own vector collections, which the published catalogues
 * ship with. An imported list has none until it is indexed here. The run is a
 * background job on the server; this card starts it, shows how far it got,
 * and says in plain words why it cannot run when the matching model is
 * missing or switched off. Running it again only processes changed rows.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Loader2, Sparkles } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import {
  fetchMatchIndex,
  matchIndexErrorCode,
  matchIndexKey,
  requestMatchIndex,
  type MatchIndexCatalogue,
} from './api';

/** Languages a catalogue can be written in; names come from the browser. */
const CATALOGUE_LANGUAGES = [
  'ar', 'bg', 'cs', 'da', 'de', 'el', 'en', 'es', 'et', 'fi', 'fr', 'he', 'hi', 'hr', 'hu', 'id',
  'it', 'ja', 'ko', 'nl', 'no', 'pl', 'pt', 'ro', 'ru', 'sv', 'th', 'tr', 'uk', 'vi', 'zh',
];

function isBusy(c: MatchIndexCatalogue): boolean {
  return c.job?.status === 'queued' || c.job?.status === 'running';
}

export function MatchIndexSection() {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();
  const [languages, setLanguages] = useState<Record<string, string>>({});

  const overviewQ = useQuery({
    queryKey: matchIndexKey,
    queryFn: fetchMatchIndex,
    staleTime: 10_000,
    // Poll only while something is indexing.
    refetchInterval: (query) => (query.state.data?.catalogues.some(isBusy) ? 3_000 : false),
  });

  const uiLanguage = (i18n.language || 'en').split('-')[0]!.toLowerCase();
  const languageNames = useMemo(() => {
    try {
      return new Intl.DisplayNames([i18n.language || 'en'], { type: 'language' });
    } catch {
      return null;
    }
  }, [i18n.language]);
  // Read the number locale per call, so a language change reformats at once.
  const nf = { format: (value: number) => value.toLocaleString(getNumberLocale()) };

  const errorText = (code: string | null): string => {
    switch (code) {
      case 'embedder_unavailable':
        return t('costs.match_index.error_embedder_unavailable', {
          defaultValue:
            'The matching model is not available on this server. Install the semantic search extra or ask your administrator.',
        });
      case 'indexer_disabled':
        return t('costs.match_index.error_indexer_disabled', {
          defaultValue:
            'The matching model is switched off. Turn on semantic search in Settings, or ask an administrator to enable it in the processes center.',
        });
      case 'catalogue_not_found':
      case 'catalogue_empty':
        return t('costs.match_index.error_catalogue_empty', {
          defaultValue: 'This catalogue has no active items to index.',
        });
      case 'catalogue_is_published':
        return t('costs.match_index.error_catalogue_is_published', {
          defaultValue: 'Published catalogues already come with their Match index.',
        });
      case 'store_unavailable':
        return t('costs.match_index.error_store_unavailable', {
          defaultValue: 'The search store cannot be reached. Check the vector search service and try again.',
        });
      case 'invalid_request':
        return t('costs.match_index.error_invalid_request', {
          defaultValue: 'Choose the language of the catalogue and try again.',
        });
      default:
        return t('costs.match_index.error_index_failed', {
          defaultValue: 'Indexing stopped with an error. Try again; items already indexed are kept.',
        });
    }
  };

  const indexMutation = useMutation({
    mutationFn: requestMatchIndex,
    onSuccess: (job) => {
      void queryClient.invalidateQueries({ queryKey: matchIndexKey });
      addToast({
        type: 'success',
        title: t('costs.match_index.started_title', { defaultValue: 'Indexing started' }),
        message: t('costs.match_index.started_message', {
          defaultValue: '"{{region}}" is being indexed for CAD-BIM Match in the background.',
          region: job.region,
        }),
      });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('costs.match_index.failed_title', { defaultValue: 'Indexing could not start' }),
        message: errorText(matchIndexErrorCode(err)),
      });
    },
  });

  const data = overviewQ.data;
  if (!data || data.catalogues.length === 0) return null;
  const unavailable = !data.embedder_installed || !data.indexer_enabled;

  const statusLine = (c: MatchIndexCatalogue) => {
    const job = c.job;
    if (job?.status === 'queued') {
      return {
        tone: 'busy' as const,
        text: t('costs.match_index.status_queued', { defaultValue: 'Waiting to start' }),
      };
    }
    if (job?.status === 'running') {
      return {
        tone: 'busy' as const,
        text: t('costs.match_index.status_running', {
          defaultValue: 'Indexing: {{done}} of {{total}} items checked',
          done: nf.format(job.processed),
          total: nf.format(job.total),
        }),
      };
    }
    if (job?.status === 'failed') {
      return { tone: 'error' as const, text: errorText(job.error_code) };
    }
    if (job?.status === 'interrupted') {
      return {
        tone: 'warn' as const,
        text: t('costs.match_index.status_interrupted', {
          defaultValue: 'Interrupted. Run it again to continue where it stopped.',
        }),
      };
    }
    if (c.indexed === 0) {
      return {
        tone: 'idle' as const,
        text: t('costs.match_index.status_not_indexed', { defaultValue: 'Not indexed yet' }),
      };
    }
    if (c.indexed < c.count) {
      return {
        tone: 'warn' as const,
        text: t('costs.match_index.status_partial', {
          defaultValue: 'Partly indexed: {{indexed}} of {{total}} items. Run it again to finish.',
          indexed: nf.format(c.indexed),
          total: nf.format(c.count),
        }),
      };
    }
    return {
      tone: 'ok' as const,
      text: t('costs.match_index.status_indexed', {
        defaultValue: 'Ready for CAD-BIM Match: {{indexed}} items',
        indexed: nf.format(c.indexed),
      }),
    };
  };

  return (
    <Card className="mb-6" data-testid="match-index-section">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle">
          <Sparkles size={20} className="text-oe-blue" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('costs.match_index.title', { defaultValue: 'Use imported catalogues in CAD-BIM Match' })}
          </h3>
          <p className="mt-1 text-sm text-content-secondary">
            {t('costs.match_index.subtitle', {
              defaultValue:
                'CAD-BIM Match suggests items from the catalogues it has indexed. Index an imported price list here and Match can suggest its items too. It runs in the background; running it again only processes changed items.',
            })}
          </p>

          {unavailable && (
            <div
              data-testid="match-index-unavailable"
              className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-800/50 dark:bg-amber-950/30 dark:text-amber-200"
            >
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{errorText(!data.embedder_installed ? 'embedder_unavailable' : 'indexer_disabled')}</span>
            </div>
          )}

          <ul className="mt-3 divide-y divide-border-light rounded-lg border border-border-light">
            {data.catalogues.map((c) => {
              const status = statusLine(c);
              const busy = isBusy(c);
              const language = languages[c.region] || c.language || uiLanguage;
              const pending = indexMutation.isPending && indexMutation.variables?.region === c.region;
              return (
                <li
                  key={c.region}
                  data-testid="match-index-row"
                  className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-content-primary" title={c.region}>
                      {c.region}
                    </div>
                    <div
                      className={`mt-0.5 flex items-center gap-1.5 text-xs ${
                        status.tone === 'error'
                          ? 'text-semantic-error'
                          : status.tone === 'warn'
                            ? 'text-amber-700 dark:text-amber-300'
                            : status.tone === 'ok'
                              ? 'text-emerald-700 dark:text-emerald-300'
                              : 'text-content-tertiary'
                      }`}
                    >
                      {status.tone === 'busy' && <Loader2 size={12} className="animate-spin" />}
                      {status.tone === 'ok' && <CheckCircle2 size={12} />}
                      <span>{status.text}</span>
                    </div>
                  </div>
                  <label className="flex items-center gap-2 text-xs text-content-secondary">
                    <span>{t('costs.match_index.language_label', { defaultValue: 'Language' })}</span>
                    <select
                      value={language}
                      disabled={busy || unavailable}
                      onChange={(e) => setLanguages((prev) => ({ ...prev, [c.region]: e.target.value }))}
                      className="rounded-md border border-border-light bg-surface-elevated px-2 py-1 text-xs disabled:opacity-60"
                    >
                      {[...new Set([language, ...CATALOGUE_LANGUAGES])].map((code) => (
                        <option key={code} value={code}>
                          {languageNames?.of(code) ?? code}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={busy || unavailable || indexMutation.isPending}
                    loading={pending}
                    onClick={() => indexMutation.mutate({ region: c.region, language, country: c.country || null })}
                  >
                    {c.indexed > 0
                      ? t('costs.match_index.action_update', { defaultValue: 'Update index' })
                      : t('costs.match_index.action_index', { defaultValue: 'Index for Match' })}
                  </Button>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </Card>
  );
}
