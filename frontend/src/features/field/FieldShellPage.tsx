// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Field-worker mobile shell.
 *
 * Implements the bottom-nav + thumb-zone layout described in
 * `docs/architecture/FIELD_WORKER_MOBILE_DESIGN.md` §6. The `/field` route in
 * `App.tsx` lazy-loads this chunk.
 *
 * What lives HERE:
 *   - Full-viewport shell with no sidebar / no desktop AppLayout
 *   - Bottom-nav with 4 fixed tabs (Today / Capture / Crew / Profile)
 *   - 56 px sticky header with current project name + offline/sync badge
 *   - Safe-area-aware padding via `env(safe-area-inset-*)`
 *   - Today / Capture / Crew tab bodies wired to the field-diary API; writes
 *     captured through the shared offline mutation queue (no second queue).
 *
 * What lives ELSEWHERE:
 *   - PIN-redemption screen at `/field/{token}` → separate `FieldAuthPage`
 *     (persists the session into sessionStorage; this shell reads it).
 *
 * Touch-target rule: every interactive element on this shell stays at
 * ≥48×48 px (WCAG 2.2 SC 2.5.8 AAA + Apple HIG + Material 3).
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  Clock,
  Camera,
  Users,
  User,
  AlertTriangle,
  Smartphone,
  ClipboardList,
  RefreshCw,
  Network,
} from 'lucide-react';
import { registerFieldServiceWorker } from '@/shared/lib/offline';
import { ModuleGuideButton } from '@/shared/ui';
import { useFieldSync } from './useFieldSync';
import { OfflineStatusBadge } from './OfflineStatusBadge';
import { SyncQueuePanel } from './SyncQueuePanel';
import { readFieldSession } from './fieldApi';
import { TodayTab, CaptureTab, CrewTab } from './FieldTabs';
import { FieldRaiseIssueTab } from './FieldRaiseIssueTab';
import { fieldGuide } from './fieldGuide';

/**
 * Auth headers for replayed field writes. The field session token + PIN are
 * stored in sessionStorage by the (future) PIN-redemption screen
 * (`FieldAuthPage`); reading them here keeps this offline slice self-contained
 * and free of a cross-lane store dependency. Returns an empty object when no
 * session is present, so the queue still drains harmlessly in that state.
 */
function fieldAuthHeaders(): Record<string, string> {
  try {
    const token = sessionStorage.getItem('oe_field_session_token');
    const pin = sessionStorage.getItem('oe_field_session_pin');
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (pin) headers['X-Field-PIN'] = pin;
    return headers;
  } catch {
    return {};
  }
}

type FieldTab = 'today' | 'capture' | 'crew' | 'issue' | 'profile';

interface FieldTabDef {
  key: FieldTab;
  label: string;
  Icon: typeof Clock;
}

const TABS: readonly FieldTabDef[] = [
  { key: 'today', label: 'Today', Icon: Clock },
  { key: 'capture', label: 'Capture', Icon: Camera },
  { key: 'crew', label: 'Crew', Icon: Users },
  { key: 'issue', label: 'Issue', Icon: AlertTriangle },
  { key: 'profile', label: 'Me', Icon: User },
] as const;

/* ── How-it-works flow + office integrations ───────────────────────────── */

/**
 * A compact "what this app does and where it connects" card for the field
 * worker's Me tab. It explains the capture-then-sync flow in plain language and
 * links to the office modules the captured work flows into (schedule progress,
 * payroll hours, inspections and safety). Uses the shell's own slate palette so
 * it stays consistent with this always-light mobile surface rather than the
 * themed design tokens the desktop pages use.
 */
function HowFieldWorks() {
  const { t } = useTranslation();

  const steps = [
    {
      icon: <Smartphone size={14} className="text-sky-600" />,
      title: t('field.flow_1_title', { defaultValue: 'Sign in' }),
      desc: t('field.flow_1_desc', {
        defaultValue: 'Open the link from your SMS and enter your PIN - no password needed.',
      }),
    },
    {
      icon: <ClipboardList size={14} className="text-sky-600" />,
      title: t('field.flow_2_title', { defaultValue: 'Log today' }),
      desc: t('field.flow_2_desc', {
        defaultValue: 'Record your hours and the progress on the jobs you worked today.',
      }),
    },
    {
      icon: <Camera size={14} className="text-sky-600" />,
      title: t('field.flow_3_title', { defaultValue: 'Capture' }),
      desc: t('field.flow_3_desc', {
        defaultValue: 'Add site photos and notes - it all works even with no signal.',
      }),
    },
    {
      icon: <RefreshCw size={14} className="text-sky-600" />,
      title: t('field.flow_4_title', { defaultValue: 'Auto-sync' }),
      desc: t('field.flow_4_desc', {
        defaultValue: 'Saved offline and sent to the office automatically when you are back online.',
      }),
    },
  ];

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
        <Network size={15} className="text-sky-600" />
        {t('field.flow_title', { defaultValue: 'How field work connects' })}
      </h2>
      <p className="mt-1 text-xs text-slate-500">
        {t('field.flow_intro', {
          defaultValue: 'Capture your day on site and it flows straight through to the office.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2">
        {steps.map((s, i) => (
          <li
            key={s.title}
            className="flex items-start gap-2 rounded-lg border border-slate-200 bg-white p-3"
          >
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sky-50 text-2xs font-bold text-sky-600">
              {i + 1}
            </span>
            <div className="min-w-0">
              <span className="flex items-center gap-1 text-xs font-semibold text-slate-900">
                {s.icon}
                {s.title}
              </span>
              <p className="mt-0.5 text-2xs leading-relaxed text-slate-500">{s.desc}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="mt-3 border-t border-slate-200 pt-3 text-2xs text-slate-500">
        <span className="font-medium text-slate-600">
          {t('field.flow_feeds', { defaultValue: 'Feeds the office:' })}
        </span>{' '}
        <Link to="/schedule" className="font-medium text-sky-600 hover:underline">
          {t('field.mod_schedule', { defaultValue: 'Schedule' })}
        </Link>{' '}
        ·{' '}
        <Link to="/payroll" className="font-medium text-sky-600 hover:underline">
          {t('field.mod_payroll', { defaultValue: 'Payroll' })}
        </Link>{' '}
        ·{' '}
        <Link to="/inspections" className="font-medium text-sky-600 hover:underline">
          {t('field.mod_inspections', { defaultValue: 'Inspections' })}
        </Link>{' '}
        ·{' '}
        <Link to="/safety" className="font-medium text-sky-600 hover:underline">
          {t('field.mod_safety', { defaultValue: 'Safety' })}
        </Link>
      </div>
    </div>
  );
}

export function FieldShellPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<FieldTab>('today');
  const session = readFieldSession();

  // Stable headers provider so the queue sender is constructed once.
  const getHeaders = useCallback(() => fieldAuthHeaders(), []);
  const { online, pending, pendingOps, syncing, syncNow, enqueue, discard, lastResults } =
    useFieldSync(getHeaders);

  // Register the scoped field service worker so the shell + last-viewed data
  // load offline. Best-effort: a failure does not affect the IndexedDB queue.
  useEffect(() => {
    void registerFieldServiceWorker();
  }, []);

  return (
    <div
      className="flex min-h-screen flex-col bg-white"
      style={{
        // iOS safe-area inset so the bottom nav doesn't sit under the
        // home indicator on iPhone X+ in standalone PWA mode.
        paddingBottom: 'env(safe-area-inset-bottom)',
        paddingTop: 'env(safe-area-inset-top)',
      }}
    >
      {/* Sticky 56 px header — project name placeholder + offline/sync badge. */}
      <header className="sticky top-0 z-10 flex h-14 items-center justify-between gap-2 border-b border-slate-200 bg-white px-4">
        <span className="min-w-0 truncate text-base font-semibold text-slate-900">
          {session
            ? t('field.header', { defaultValue: 'Field time' })
            : t('field.header_no_session', { defaultValue: 'Field - sign in' })}
        </span>
        <div className="flex shrink-0 items-center gap-2">
          <OfflineStatusBadge
            online={online}
            pending={pending}
            syncing={syncing}
            onSyncNow={() => {
              void syncNow();
            }}
          />
          <ModuleGuideButton content={fieldGuide} />
        </div>
      </header>

      {/* Tab body. */}
      <main className="flex flex-1 flex-col items-stretch overflow-y-auto">
        {tab === 'today' && <TodayTab session={session} />}
        {tab === 'capture' && <CaptureTab session={session} enqueue={enqueue} />}
        {tab === 'crew' && <CrewTab session={session} enqueue={enqueue} />}
        {tab === 'issue' && (
          <FieldRaiseIssueTab
            session={session}
            enqueue={enqueue}
            pendingOps={pendingOps}
            lastResults={lastResults}
            online={online}
          />
        )}
        {tab === 'profile' && (
          <div className="flex flex-1 flex-col">
            <div className="px-4 pt-4">
              <HowFieldWorks />
            </div>
            <div className="flex flex-col items-center gap-2 px-4 py-6 text-center">
              <p className="text-sm text-slate-500">
                {session
                  ? t('field.profile_signed_in', { defaultValue: 'Signed in as a field worker.' })
                  : t('field.no_session', { defaultValue: 'Open the link from your SMS to start.' })}
              </p>
              <p className="text-xs text-slate-400">
                {online
                  ? t('field.sync_online', { defaultValue: 'Online - changes sync automatically.' })
                  : t('field.sync_offline', { defaultValue: 'Offline - changes are saved and will sync.' })}
              </p>
            </div>
            {/* Pending-sync review queue: lists offline captures awaiting replay
                with per-item retry/dismiss. */}
            <SyncQueuePanel
              state={{ online, pendingOps, syncing, syncNow, discard }}
              className="border-t border-slate-100"
            />
          </div>
        )}
      </main>

      {/* Bottom nav — fixed 64 px, 4 tabs. */}
      <nav
        className="sticky bottom-0 flex border-t border-slate-200 bg-white"
        aria-label={t('field.nav_label', { defaultValue: 'Field navigation' })}
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        {TABS.map(({ key, label, Icon }) => {
          const active = key === tab;
          const tabLabel = t(`field.tab_${key}`, { defaultValue: label });
          return (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              aria-current={active ? 'page' : undefined}
              aria-label={tabLabel}
              className={`flex h-16 flex-1 flex-col items-center justify-center gap-1 text-xs ${
                active ? 'text-sky-600' : 'text-slate-500'
              }`}
            >
              <Icon size={28} aria-hidden="true" />
              <span>{tabLabel}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}

export default FieldShellPage;
