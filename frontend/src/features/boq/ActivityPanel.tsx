/**
 * ActivityPanel — Collapsible activity log for the BOQ Editor.
 *
 * Displays recent changes (position added/updated/deleted, imports, etc.)
 * with icons, descriptions, and relative timestamps.
 *
 * Extracted from BOQEditorPage.tsx for modularity.
 */

import React from 'react';
import {
  Plus,
  Trash2,
  Pencil,
  BarChart3,
  FileDown,
  LayoutTemplate,
  Activity,
  Inbox,
  ChevronDown,
  ChevronUp,
  Circle,
} from 'lucide-react';
import type { ActivityEntry, ActivityAction } from './api';
import { formatRelativeTime } from './boqHelpers';

/* ── Activity icon map ───────────────────────────────────────────────── */

/** Map action types to icon + color for visual distinction. */
const ACTIVITY_ICON_MAP: Record<ActivityAction, { icon: React.ReactNode; color: string }> = {
  position_added: {
    icon: <Circle size={12} strokeWidth={3} />,
    color: 'text-semantic-success',
  },
  position_updated: {
    icon: <Pencil size={12} strokeWidth={2} />,
    color: 'text-oe-blue',
  },
  position_deleted: {
    icon: <Trash2 size={12} strokeWidth={2} />,
    color: 'text-semantic-error',
  },
  quantity_updated: {
    icon: <Pencil size={12} strokeWidth={2} />,
    color: 'text-oe-blue',
  },
  rate_updated: {
    icon: <Pencil size={12} strokeWidth={2} />,
    color: 'text-oe-blue',
  },
  section_added: {
    icon: <Plus size={12} strokeWidth={2.5} />,
    color: 'text-semantic-success',
  },
  section_deleted: {
    icon: <Trash2 size={12} strokeWidth={2} />,
    color: 'text-semantic-error',
  },
  validation_run: {
    icon: <BarChart3 size={12} strokeWidth={2} />,
    color: 'text-violet-500',
  },
  excel_imported: {
    icon: <FileDown size={12} strokeWidth={2} />,
    color: 'text-semantic-success',
  },
  csv_imported: {
    icon: <FileDown size={12} strokeWidth={2} />,
    color: 'text-semantic-success',
  },
  boq_created: {
    icon: <Plus size={12} strokeWidth={2.5} />,
    color: 'text-oe-blue',
  },
  template_applied: {
    icon: <LayoutTemplate size={12} strokeWidth={2} />,
    color: 'text-violet-500',
  },
  markup_added: {
    icon: <Plus size={12} strokeWidth={2.5} />,
    color: 'text-semantic-success',
  },
  markup_updated: {
    icon: <Pencil size={12} strokeWidth={2} />,
    color: 'text-oe-blue',
  },
  status_changed: {
    icon: <Activity size={12} strokeWidth={2} />,
    color: 'text-amber-500',
  },
};

/* ── ActivityPanel component ─────────────────────────────────────────── */

export function ActivityPanel({
  activities,
  isOpen,
  onToggle,
  t,
}: {
  activities: ActivityEntry[];
  isOpen: boolean;
  onToggle: () => void;
  t: (key: string, options?: Record<string, string>) => string;
}) {
  const visibleActivities = isOpen ? activities : activities.slice(0, 5);

  return (
    <div className="mt-6 rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden transition-all">
      {/* ── Toggle header ──────────────────────────────────────────── */}
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-5 py-3.5 hover:bg-surface-secondary/50 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <Activity size={16} className="text-content-tertiary" strokeWidth={1.75} />
          <span className="text-sm font-semibold text-content-primary">
            {t('boq.recent_activity', { defaultValue: 'Recent Activity' })}
          </span>
          {activities.length > 0 && (
            <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-surface-secondary px-1.5 text-2xs font-medium text-content-secondary tabular-nums">
              {activities.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-content-tertiary">
          {isOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </div>
      </button>

      {/* ── Activity list ──────────────────────────────────────────── */}
      {activities.length === 0 ? (
        <div className="px-5 pb-5 pt-1">
          <div className="flex flex-col items-center gap-2 py-6 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-secondary">
              <Inbox size={18} className="text-content-tertiary" />
            </div>
            <p className="text-xs text-content-tertiary">
              {t('boq.no_activity', { defaultValue: 'No activity yet. Changes will appear here.' })}
            </p>
          </div>
        </div>
      ) : (
        <div className="border-t border-border-light">
          <ul className="divide-y divide-border-light">
            {visibleActivities.map((entry) => {
              const mapping = ACTIVITY_ICON_MAP[entry.action] ?? {
                icon: <Activity size={12} strokeWidth={2} />,
                color: 'text-content-tertiary',
              };

              return (
                <li
                  key={entry.id}
                  className="flex items-center gap-3 px-5 py-3 hover:bg-surface-secondary/30 transition-colors"
                >
                  {/* Icon */}
                  <div
                    className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-surface-secondary ${mapping.color}`}
                  >
                    {mapping.icon}
                  </div>

                  {/* Description */}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-content-primary truncate">
                      {entry.description}
                    </p>
                    {entry.user_name && (
                      <p className="text-2xs text-content-tertiary mt-0.5">
                        {entry.user_name}
                      </p>
                    )}
                  </div>

                  {/* Relative time */}
                  <span className="shrink-0 text-xs text-content-tertiary tabular-nums">
                    {formatRelativeTime(entry.created_at)}
                  </span>
                </li>
              );
            })}
          </ul>

          {/* Show all link */}
          {!isOpen && activities.length > 5 && (
            <div className="border-t border-border-light px-5 py-3">
              <button
                onClick={onToggle}
                className="text-xs font-medium text-oe-blue hover:text-oe-blue-hover transition-colors"
              >
                {t('boq.show_all_activity', { defaultValue: 'Show all activity...' })}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
