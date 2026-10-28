// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One registered connector on the Document Connectors page. Beyond the name,
// kind and watched path, it surfaces the outcome of the source's most recent
// sync straight from the row the backend already stores (last_synced_at +
// last_result): when it last ran and how the scanned files were partitioned
// into found / imported / already-on-record / duplicate. A sync triggered from
// this card also shows a one-line confirmation (or the error) for that run, so
// the admin gets immediate feedback without re-reading the counts.

import type { LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Copy,
  FileDown,
  Files,
  FolderCheck,
  HardDrive,
  Info,
  RefreshCw,
} from 'lucide-react';

import { Badge } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import type { ConnectorSource, ConnectorSyncResult } from './types';
import { formatAbsolute, formatSyncAgo } from './utils';

type Translate = (key: string, opts: { defaultValue: string } & Record<string, unknown>) => string;

/**
 * The plain-language summary of the last sync. Kept as the canonical sentence
 * (found / imported / already-in counts) that screen readers hear in place of
 * the visual chips; sighted users read the chips below.
 */
function lastSyncLabel(t: Translate, source: ConnectorSource): string {
  if (!source.last_synced_at || !source.last_result) {
    return t('connectors.never_synced', { defaultValue: 'Not synced yet' });
  }
  const r = source.last_result;
  return t('connectors.last_sync', {
    defaultValue: 'Last sync: {{created}} new, {{duplicate}} duplicate, {{known}} already in',
    created: r.created,
    duplicate: r.duplicate,
    known: r.already_known,
  });
}

/** One count from a sync run, as a small tinted pill with an explanatory title. */
function CountChip({
  icon: Icon,
  label,
  value,
  title,
  tone = 'neutral',
}: {
  icon: LucideIcon;
  label: string;
  value: number;
  title: string;
  tone?: 'neutral' | 'blue' | 'success';
}) {
  const toneClass =
    tone === 'blue'
      ? 'bg-oe-blue-subtle text-oe-blue-text'
      : tone === 'success'
        ? 'bg-semantic-success-bg text-semantic-success'
        : 'bg-surface-secondary text-content-secondary';
  return (
    <span
      title={title}
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium',
        toneClass,
      )}
    >
      <Icon className="h-3 w-3 shrink-0" aria-hidden />
      <span className="opacity-80">{label}</span>
      <span className="font-semibold tabular-nums">{value}</span>
    </span>
  );
}

export interface SourceCardProps {
  source: ConnectorSource;
  onSync: (id: string) => void;
  /** This card's sync is in flight. */
  syncing: boolean;
  /** The error from this card's most recent sync attempt, if it failed. */
  syncError?: unknown;
  /** The result of this card's most recent successful sync, for confirmation. */
  syncResult?: ConnectorSyncResult | null;
}

export function SourceCard({ source, onSync, syncing, syncError, syncResult }: SourceCardProps) {
  const { t } = useTranslation();
  const r = source.last_result;
  const ago = formatSyncAgo(source.last_synced_at, t);

  return (
    <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <HardDrive className="h-4 w-4 shrink-0 text-content-tertiary" />
        <span className="text-sm font-semibold text-content-primary">{source.name}</span>
        <Badge variant="neutral" size="sm">
          {source.kind}
        </Badge>
        {source.enabled ? (
          <Badge variant="success" size="sm" dot>
            {t('connectors.enabled', { defaultValue: 'Enabled' })}
          </Badge>
        ) : (
          <Badge variant="warning" size="sm" dot>
            {t('connectors.disabled', { defaultValue: 'Disabled' })}
          </Badge>
        )}
        <button
          type="button"
          onClick={() => onSync(source.id)}
          disabled={syncing}
          className="ms-auto inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={clsx('h-4 w-4', syncing && 'animate-spin')} />
          {syncing
            ? t('connectors.syncing', { defaultValue: 'Syncing...' })
            : t('connectors.sync_now', { defaultValue: 'Sync now' })}
        </button>
      </div>

      <code className="mt-2 block truncate rounded bg-surface-secondary px-2 py-1 text-xs text-content-secondary">
        {source.root_path}
      </code>

      <div className="mt-2 space-y-1.5">
        {/* Status line: when it last ran, or a "not synced" / error state. */}
        {syncError ? (
          <div className="flex items-start gap-1.5 text-xs text-semantic-error">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>
              {t('connectors.sync_failed', { defaultValue: 'Last sync failed' })}:{' '}
              {getErrorMessage(syncError)}
            </span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-xs text-content-tertiary">
            <Clock className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span title={formatAbsolute(source.last_synced_at)}>
              {ago
                ? t('connectors.synced_ago', { defaultValue: 'Synced {{rel}}', rel: ago })
                : t('connectors.never_synced', { defaultValue: 'Not synced yet' })}
            </span>
          </div>
        )}

        {/* Visual breakdown of the last run. The equivalent sentence is offered
            to assistive tech below, so this row is hidden from it to avoid the
            counts being read out twice. */}
        {r ? (
          <>
            <div className="flex flex-wrap items-center gap-1.5" aria-hidden>
              <CountChip
                icon={Files}
                label={t('connectors.found', { defaultValue: 'Found' })}
                value={r.total}
                title={t('connectors.found_tip', {
                  defaultValue: 'Files scanned in the folder on the last sync',
                })}
              />
              <CountChip
                icon={FileDown}
                label={t('connectors.imported', { defaultValue: 'Imported' })}
                value={r.created}
                tone={r.created > 0 ? 'blue' : 'neutral'}
                title={t('connectors.imported_tip', {
                  defaultValue: 'New files brought onto the project as documents',
                })}
              />
              <CountChip
                icon={FolderCheck}
                label={t('connectors.skipped', { defaultValue: 'On record' })}
                value={r.already_known}
                title={t('connectors.skipped_tip', {
                  defaultValue: 'Files already imported by this connector, left untouched',
                })}
              />
              {r.duplicate > 0 ? (
                <CountChip
                  icon={Copy}
                  label={t('connectors.duplicate', { defaultValue: 'Duplicate' })}
                  value={r.duplicate}
                  title={t('connectors.duplicate_tip', {
                    defaultValue: 'Same content as another file, so not imported again',
                  })}
                />
              ) : null}
            </div>
            <span className="sr-only">{lastSyncLabel(t, source)}</span>
          </>
        ) : null}

        {/* One-line confirmation for a sync just triggered from this card. */}
        {syncResult ? (
          syncResult.created > 0 ? (
            <div className="flex items-center gap-1.5 text-xs text-semantic-success" role="status">
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
              <span>
                {t('connectors.just_imported', {
                  count: syncResult.created,
                  defaultValue_one: 'Imported {{count}} new document',
                  defaultValue_other: 'Imported {{count}} new documents',
                })}
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-content-tertiary" role="status">
              <Info className="h-3.5 w-3.5 shrink-0" aria-hidden />
              <span>{t('connectors.nothing_new', { defaultValue: 'No new files this sync' })}</span>
            </div>
          )
        ) : null}
      </div>
    </div>
  );
}
