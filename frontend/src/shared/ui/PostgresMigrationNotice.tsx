// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PostgresMigrationNotice - a one-time top strip shown on version 6 installs
 * that are running on PostgreSQL.
 *
 * Version 6 moved the database engine from SQLite (v5 and earlier) to an
 * embedded PostgreSQL. That migration can surface the odd rough edge, so this
 * banner asks people to report anything off the moment they see it, through
 * the in-app feedback form (which posts straight to us). It is dismissible and
 * the dismissal is remembered, so it only shows on the first runs of v6 until
 * the user acknowledges it.
 *
 * Gating (all three must hold):
 *   - the app is on a 6.x build (the SQLite -> PostgreSQL switch is a v6 thing);
 *   - the backend reports it is actually on PostgreSQL, via
 *     ``/api/system/status`` ``database.engine``. This keeps the strip OFF the
 *     public hosted demo, which still runs on SQLite, where the message would
 *     be untrue;
 *   - the user has not dismissed it.
 *
 * The "Report a problem" action dispatches the ``oe:open-bug-report`` event
 * that the header's BugReportMenu listens for. We deliberately open that menu
 * (whose best channel files a GitHub issue) rather than the e-mail feedback
 * form, because the community build has no SMTP configured, so the form would
 * have no way to actually deliver the report.
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Database, X } from 'lucide-react';

import { apiGet } from '@/shared/lib/api';
import { APP_VERSION } from '@/shared/lib/version';

const DISMISS_KEY = 'oe.v6_pg_notice_dismissed';

interface SystemStatus {
  demo_mode?: boolean;
  database?: { engine?: string };
}

export function PostgresMigrationNotice() {
  const { t } = useTranslation();
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(DISMISS_KEY) === '1';
    } catch {
      return false;
    }
  });

  // Reuse the shared ['system-status'] query so this and the DemoBanner share
  // one /api/system/status call. demo_mode + the db engine are fixed for the
  // life of the deployment, so staleTime Infinity is correct.
  const { data } = useQuery<SystemStatus>({
    queryKey: ['system-status'],
    queryFn: () => apiGet<SystemStatus>('/system/status'),
    retry: false,
    staleTime: Infinity,
  });

  const onPostgres = data?.database?.engine === 'postgresql';
  const isV6 = /^6\./.test(APP_VERSION);

  if (dismissed || !isV6 || !onPostgres) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, '1');
    } catch {
      /* private mode / quota - dismissal just won't persist */
    }
    setDismissed(true);
  };

  return (
    <div
      role="status"
      className="sticky top-0 z-50 flex items-center justify-center gap-2 px-4 py-1.5 text-xs font-medium text-amber-950 bg-gradient-to-r from-amber-300 via-amber-200 to-amber-300 border-b border-amber-500/40 shadow-sm dark:text-amber-100 dark:from-amber-900/40 dark:via-amber-800/40 dark:to-amber-900/40 dark:border-amber-500/30"
    >
      <Database size={13} className="shrink-0" />
      <span className="text-center">
        {t('pg_notice.text', {
          defaultValue:
            'Version 6 moved the database from SQLite to PostgreSQL. While we settle that in, you may hit the odd error or off-looking number. Please tell us right away so we can fix it fast.',
        })}
      </span>
      <button
        type="button"
        onClick={() => window.dispatchEvent(new CustomEvent('oe:open-bug-report'))}
        className="ml-1 shrink-0 whitespace-nowrap underline underline-offset-2 hover:text-amber-900 dark:hover:text-amber-50"
      >
        {t('pg_notice.report', { defaultValue: 'Report a problem' })}
      </button>
      <button
        type="button"
        onClick={dismiss}
        aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
        className="ml-1 shrink-0 rounded p-0.5 hover:bg-amber-900/10 dark:hover:bg-amber-100/10"
      >
        <X size={13} />
      </button>
    </div>
  );
}
