// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// MatchReadinessCard - says whether matching can work for the project
// BEFORE the user uploads a model and runs it.
//
// Reads GET /match_elements/readiness, which asks the same sources the run
// reads (the catalogue store, the language model, the project's binding,
// the demo flag) and returns codes. Each code becomes one plain sentence
// with the next step. Blockers ("cannot match here") and warnings ("will
// match, but worse") look different so nobody mistakes one for the other.
//
// The backend also resolves the project's region to a language and a
// recommended catalogue; the wizard reads those from the same query
// (``useMatchReadiness``) instead of re-deriving them from the region label.
//
// This is the page's only voice on the search service. A separate Qdrant
// card used to probe the GENERAL vector database and said "running" while
// the catalogue store the ranker reads was down or empty; its install and
// refresh actions live here now, shown only where they change the answer.

import { Link } from 'react-router-dom';
import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Download,
  Info,
  Loader2,
  RefreshCw,
  XCircle,
} from 'lucide-react';
import type { TFunction } from 'i18next';

import { useToastStore } from '@/stores/useToastStore';
import { setProjectCatalog } from '@/features/match/api';
import { ApiError } from '@/shared/lib/api';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import {
  fetchMatchReadiness,
  installQdrantNative,
  MatchApiError,
  type MatchReadiness,
  type MatchReadinessItem,
} from './api';
import { describeMatchError } from './matchErrors';

export function useMatchReadiness(projectId: string | null) {
  return useQuery<MatchReadiness>({
    enabled: !!projectId,
    queryKey: ['match-readiness', projectId],
    queryFn: () => fetchMatchReadiness(projectId!),
    staleTime: 30_000,
    retry: false,
    // A stopped search service can come back without anyone touching this
    // page (started from a terminal, a container restart), so keep asking
    // while it is down. Nothing else here changes on its own.
    refetchInterval: (q) =>
      q.state.data?.blockers.some((b) => b.code === 'search_unreachable') ? 30_000 : false,
  });
}

function switchErrorMessage(err: unknown, t: TFunction): string {
  if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
    return t('match_readiness.switch_forbidden', {
      defaultValue: 'Only the project owner or an administrator can change the catalogue.',
    });
  }
  return t('match_readiness.switch_failed_body', {
    defaultValue: 'Nothing was changed. Try again; if it keeps failing, reload the page.',
  });
}

function installErrorMessage(err: unknown, t: TFunction): string {
  if (err instanceof MatchApiError && (err.status === 401 || err.status === 403)) {
    return t('match_readiness.install_forbidden', {
      defaultValue:
        'Only an administrator can install the search service. Ask yours to install or start it.',
    });
  }
  // The install route words its own failures (download blocked, folder not
  // writable) for the person who has to fix them.
  if (err instanceof MatchApiError && err.kind === 'http' && err.detail) return err.detail;
  return describeMatchError(err, t);
}

/** Language name in the reader's language ("it" -> "Italiano" / "Italian"). */
function languageName(code: string | undefined, locale: string): string {
  if (!code) return '';
  try {
    return new Intl.DisplayNames([locale], { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}

function sentence(item: MatchReadinessItem, t: TFunction, locale: string): string {
  const p = item.params ?? {};
  switch (item.code) {
    case 'demo_mode':
      return t('match_readiness.demo_mode', {
        defaultValue:
          'This public demo cannot match models: it has no AI search service and no cost catalogues, so every run ends without results. Matching needs a self-hosted install of the platform.',
      });
    case 'search_client_missing':
      return t('match_readiness.search_client_missing', {
        defaultValue:
          'The AI search client is not installed on this server, so cost catalogues cannot be searched. Install it with "pip install openconstructionerp[semantic-clients]" and restart the app.',
      });
    case 'search_unreachable':
      if (p.local_install === 'available') {
        return t('match_readiness.search_unreachable_local', {
          defaultValue:
            'The AI search service that holds the cost catalogues is not installed on this computer, so there is nothing to match against. Install it below with one click (no Docker, about 30 seconds).',
        });
      }
      return t('match_readiness.search_unreachable', {
        defaultValue:
          'The AI search service that holds the cost catalogues is not answering, so there is nothing to match against. Start it again or ask your administrator.',
      });
    case 'search_not_configured':
      return t('match_readiness.search_not_configured', {
        defaultValue:
          'This installation has no AI search server for cost catalogues, so no catalogue can be installed and matching has nothing to search. An administrator runs a Qdrant server, sets CWICR_QDRANT_URL to its address and restarts the app.',
      });
    case 'no_catalogue_installed':
      return p.catalogue
        ? t('match_readiness.no_catalogue_installed', {
            defaultValue:
              'No cost catalogue is installed yet. Install {{catalogue}} under Setup & tools, then come back to match.',
            catalogue: p.catalogue,
          })
        : t('match_readiness.no_catalogue_installed_any', {
            defaultValue:
              'No cost catalogue is installed yet. Install one under Setup & tools, then come back to match.',
          });
    case 'embedder_missing':
      return t('match_readiness.embedder_missing', {
        defaultValue:
          'The free language model is not installed, so matches rely on keywords only and are less accurate. Setup & tools shows how to install it.',
      });
    case 'no_catalogue_for_language':
      return p.catalogue
        ? t('match_readiness.no_catalogue_for_language', {
            defaultValue:
              'No catalogue in {{language}} is installed, so matching searches a catalogue in another language and its rates are not from your region. Install {{catalogue}} under Setup & tools for local rates.',
            language: languageName(p.language, locale),
            catalogue: p.catalogue,
          })
        : t('match_readiness.no_catalogue_for_language_any', {
            defaultValue:
              'No catalogue in {{language}} is installed, so matching searches a catalogue in another language and its rates are not from your region.',
            language: languageName(p.language, locale),
          });
    case 'region_unknown':
      return p.region
        ? t('match_readiness.region_unknown', {
            defaultValue:
              "We could not tell the project's language from its region ({{region}}), so no catalogue is chosen automatically. Choose a catalogue in the Cost catalogue step.",
            region: p.region,
          })
        : t('match_readiness.region_unknown_empty', {
            defaultValue:
              'The project has no region or address, so no catalogue is chosen automatically. Choose a catalogue in the Cost catalogue step, or set the region in the project settings.',
          });
    case 'region_language_unknown':
      return t('match_readiness.region_language_unknown', {
        defaultValue:
          'Your project region ({{region}}) spans several languages, so no catalogue is chosen automatically. Pick one in the Cost catalogue step.',
        region: p.region ?? '',
      });
    case 'binding_language_differs':
      return t('match_readiness.binding_language_differs', {
        defaultValue:
          'Matches already confirmed in this project use {{bound}} ({{boundLanguage}}). A {{language}} catalogue is installed now: {{catalogue}}. Switching applies to new matches only.',
        bound: p.bound ?? '',
        boundLanguage: languageName(p.bound_language, locale),
        language: languageName(p.language, locale),
        catalogue: p.catalogue ?? '',
      });
    default:
      return '';
  }
}

interface Props {
  projectId: string | null;
  /** Opens the "Setup & tools" section, where catalogues and the language
   *  model are installed. */
  onOpenSetup?: () => void;
}

export function MatchReadinessCard({ projectId, onOpenSetup }: Props) {
  const { t, i18n } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const qc = useQueryClient();
  const readinessQ = useMatchReadiness(projectId);
  const locale = i18n.language || 'en';

  const switchM = useMutation({
    mutationFn: (catalogue: string) => setProjectCatalog(projectId!, catalogue),
    onSuccess: (_r, catalogue) => {
      addToast({
        type: 'success',
        title: t('match_readiness.switched', {
          defaultValue: 'Catalogue switched to {{catalogue}}',
          catalogue,
        }),
      });
      qc.invalidateQueries({ queryKey: ['match-readiness', projectId] });
    },
    onError: (e: unknown) =>
      addToast({
        type: 'error',
        title: t('match_readiness.switch_failed', {
          defaultValue: 'Could not switch the catalogue',
        }),
        message: switchErrorMessage(e, t),
      }),
  });

  const { confirm, ...confirmProps } = useConfirm();
  const handleSwitch = useCallback(
    async (catalogue: string) => {
      const ok = await confirm({
        title: t('match_readiness.switch_confirm_title', {
          defaultValue: 'Switch the catalogue to {{catalogue}}?',
          catalogue,
        }),
        message: t('match_readiness.switch_confirm_body', {
          defaultValue:
            'The switch applies to new matches only. Matches already confirmed keep the rates they were confirmed with.',
        }),
        confirmLabel: t('match_readiness.switch_confirm', { defaultValue: 'Switch catalogue' }),
        variant: 'warning',
      });
      if (ok) switchM.mutate(catalogue);
    },
    [confirm, switchM, t],
  );

  const installM = useMutation({
    mutationFn: installQdrantNative,
    onSuccess: async () => {
      // The install route reports reachability of the general vector
      // database, which is not what this card is about; readiness re-asks
      // the catalogue store and that answer is what the card shows next.
      addToast({
        type: 'success',
        title: t('qdrant_health.install_partial_title', {
          defaultValue: 'Vector database installed',
        }),
      });
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['match-readiness', projectId] }),
        qc.invalidateQueries({ queryKey: ['catalogues-v3'] }),
      ]);
    },
    onError: (e: unknown) =>
      addToast({
        type: 'error',
        title: t('qdrant_health.install_failed_title', {
          defaultValue: 'Vector database install failed',
        }),
        message: installErrorMessage(e, t),
      }),
  });

  const data = readinessQ.data;
  const readyCatalogue = useMemo(() => {
    if (!data) return null;
    if (data.recommended_catalogue?.installed) return data.recommended_catalogue.region;
    return data.bound_catalogue;
  }, [data]);

  if (!projectId) return null;

  if (readinessQ.isLoading) {
    // The check can take a few seconds against a slow search service; an
    // empty slot that later fills in reads as "nothing to worry about".
    return (
      <div
        data-testid="match-readiness-loading"
        aria-busy="true"
        className="flex items-center gap-2 rounded-xl border border-border-light bg-surface-primary px-4 py-3 text-xs text-content-tertiary"
      >
        <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
        <span>
          {t('match_readiness.checking', {
            defaultValue: 'Checking whether matching can run for this project…',
          })}
        </span>
      </div>
    );
  }

  if (readinessQ.isError || !data) {
    return (
      <div
        data-testid="match-readiness-error"
        className="flex items-start gap-2 rounded-xl border border-border-light bg-surface-primary px-4 py-3 text-xs text-content-secondary"
      >
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-content-tertiary" />
        <span>
          {t('match_readiness.check_failed', {
            defaultValue:
              'Could not check whether matching is ready on this server. You can still continue; a run will say what is missing.',
          })}
        </span>
      </div>
    );
  }

  if (data.blockers.length > 0) {
    const unreachable = data.blockers.find((b) => b.code === 'search_unreachable');
    return (
      <div
        role="alert"
        data-testid="match-readiness-blocked"
        className="rounded-xl border border-rose-200 bg-rose-50/70 px-4 py-3 dark:border-rose-800/60 dark:bg-rose-950/20"
      >
        <div className="flex items-center gap-2 text-sm font-semibold text-rose-900 dark:text-rose-100">
          <XCircle className="h-4 w-4 shrink-0" />
          {t('match_readiness.blocked_title', {
            defaultValue: 'Matching cannot run here yet',
          })}
        </div>
        {/* Why at all: without this a blocked card names what is missing but
            not what it is for, and a first-time user reads it as a fault. */}
        <p className="mt-1 pl-6 text-xs text-rose-900/90 dark:text-rose-100/90">
          {t('match_readiness.blocked_why', {
            defaultValue:
              'Matching compares every model element with a rate catalogue by meaning, so it needs two things on this server: the meaning search service and a rate catalogue for your country.',
          })}
        </p>
        <ul className="mt-1.5 space-y-1 pl-6 text-xs text-rose-800 dark:text-rose-200">
          {data.blockers.map((b) => (
            <li key={b.code} data-code={b.code}>
              {sentence(b, t, locale)}
            </li>
          ))}
        </ul>
        <div className="mt-2 ml-6 flex flex-wrap items-center gap-3">
          {unreachable?.params.local_install === 'available' && (
            <button
              type="button"
              disabled={installM.isPending}
              onClick={() => installM.mutate()}
              className="inline-flex items-center gap-1.5 rounded-md bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {installM.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Download className="h-3.5 w-3.5" />
              )}
              {installM.isPending
                ? t('qdrant_health.install_in_progress', { defaultValue: 'Installing…' })
                : t('qdrant_health.install_button', { defaultValue: 'Install Qdrant (no Docker)' })}
            </button>
          )}
          {unreachable && (
            <button
              type="button"
              disabled={readinessQ.isFetching || installM.isPending}
              onClick={() => void readinessQ.refetch()}
              className="inline-flex items-center gap-1.5 rounded-md border border-rose-300 bg-white/70 px-3 py-1.5 text-xs font-medium text-rose-800 transition-colors hover:bg-white disabled:opacity-60 dark:border-rose-700 dark:bg-rose-950/40 dark:text-rose-100 dark:hover:bg-rose-900/50"
            >
              <RefreshCw className={readinessQ.isFetching ? 'h-3.5 w-3.5 animate-spin' : 'h-3.5 w-3.5'} />
              {t('qdrant_health.refresh_button', { defaultValue: 'Refresh status' })}
            </button>
          )}
          {unreachable && unreachable.params.local_install !== 'available' && (
            <Link
              to="/settings?tab=ai"
              className="inline-flex items-center gap-1 text-xs font-semibold text-rose-900 underline-offset-2 hover:underline dark:text-rose-100"
            >
              {t('match_readiness.open_search_settings', { defaultValue: 'Set up search' })}
              <ArrowRight className="h-3 w-3" />
            </Link>
          )}
          {onOpenSetup && data.blockers.some((b) => b.code === 'no_catalogue_installed') && (
            <button
              type="button"
              onClick={onOpenSetup}
              className="inline-flex items-center gap-1 text-xs font-semibold text-rose-900 underline-offset-2 hover:underline dark:text-rose-100"
            >
              {t('match_readiness.open_setup', { defaultValue: 'Open Setup & tools' })}
              <ArrowRight className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>
    );
  }

  if (data.warnings.length > 0) {
    const switchItem = data.warnings.find((w) => w.code === 'binding_language_differs');
    const needsSetup = data.warnings.some(
      (w) => w.code === 'no_catalogue_for_language' || w.code === 'embedder_missing',
    );
    return (
      <div
        data-testid="match-readiness-warnings"
        className="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3 dark:border-amber-800/60 dark:bg-amber-950/20"
      >
        <div className="flex items-center gap-2 text-sm font-semibold text-amber-900 dark:text-amber-100">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {t('match_readiness.warnings_title', {
            defaultValue: 'Matching works, with limits',
          })}
        </div>
        <ul className="mt-1.5 space-y-1 pl-6 text-xs text-amber-800 dark:text-amber-200">
          {data.warnings.map((w) => (
            <li key={w.code} data-code={w.code}>
              {sentence(w, t, locale)}
            </li>
          ))}
        </ul>
        {switchItem && !data.can_change_catalogue && (
          <p className="mt-1.5 pl-6 text-xs text-amber-800 dark:text-amber-200">
            {t('match_readiness.switch_ask_owner', {
              defaultValue: 'Ask the project owner or an administrator to switch the catalogue.',
            })}
          </p>
        )}
        <div className="mt-2 ml-6 flex flex-wrap items-center gap-3">
          {switchItem?.params.catalogue && data.can_change_catalogue && (
            <button
              type="button"
              disabled={switchM.isPending}
              onClick={() => void handleSwitch(switchItem.params.catalogue!)}
              className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-white/90 px-2.5 py-1 text-[11px] font-semibold text-amber-900 hover:bg-amber-50 disabled:opacity-60 dark:border-amber-700/50 dark:bg-surface-primary/80 dark:text-amber-100"
            >
              {t('match_readiness.switch', {
                defaultValue: 'Switch to {{catalogue}}',
                catalogue: switchItem.params.catalogue,
              })}
            </button>
          )}
          {onOpenSetup && needsSetup && (
            <button
              type="button"
              onClick={onOpenSetup}
              className="inline-flex items-center gap-1 text-xs font-semibold text-amber-900 underline-offset-2 hover:underline dark:text-amber-100"
            >
              {t('match_readiness.open_setup', { defaultValue: 'Open Setup & tools' })}
              <ArrowRight className="h-3 w-3" />
            </button>
          )}
        </div>
        <ConfirmDialog {...confirmProps} />
      </div>
    );
  }

  return (
    <div
      data-testid="match-readiness-ready"
      className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50/60 px-4 py-2 text-xs text-emerald-900 dark:border-emerald-800/60 dark:bg-emerald-950/20 dark:text-emerald-100"
    >
      <CheckCircle2 className="h-4 w-4 shrink-0" />
      {readyCatalogue
        ? t('match_readiness.ready_with', {
            defaultValue: 'Ready to match against {{catalogue}}.',
            catalogue: readyCatalogue,
          })
        : t('match_readiness.ready', { defaultValue: 'Ready to match.' })}
    </div>
  );
}
