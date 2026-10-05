// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which imported activities the client sees on the portal.
 *
 * A "yes" in the file's visibility column is only a suggestion: nothing is
 * shown to the client unless it is ticked here, and the ticked refs are what
 * the commit sends as `client_visible_refs`. Milestones and suggested rows
 * are listed first; the rest is one click away.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Diamond, Eye } from 'lucide-react';

import { Badge, Button } from '@/shared/ui';
import type { ImportActivity } from './tabularImport';

export interface ClientMilestonePickerProps {
  activities: ImportActivity[];
  /** Refs the file marks as visible to the client. */
  suggested: string[];
  selected: ReadonlySet<string>;
  onChange: (next: Set<string>) => void;
  disabled?: boolean;
}

export function ClientMilestonePicker({
  activities,
  suggested,
  selected,
  onChange,
  disabled = false,
}: ClientMilestonePickerProps) {
  const { t } = useTranslation();
  const [showAll, setShowAll] = useState(false);
  const suggestedSet = useMemo(() => new Set(suggested), [suggested]);

  const featured = activities.filter(
    (a) => a.activity_type === 'milestone' || suggestedSet.has(a.ref) || selected.has(a.ref),
  );
  const listed = showAll || featured.length === 0 ? activities : featured;
  const hidden = activities.length - listed.length;

  const toggle = (ref: string) => {
    const next = new Set(selected);
    if (next.has(ref)) next.delete(ref);
    else next.add(ref);
    onChange(next);
  };

  return (
    <div className="space-y-2" data-testid="tabular-client-picker">
      <p className="text-xs text-content-secondary">
        {t('schedule.tabular_import.client_desc', {
          defaultValue:
            'Tick what the client may see on the portal. A "yes" in the file is only a suggestion; nothing is shown to the client unless it is ticked here.',
        })}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {suggested.length > 0 && (
          <Button
            size="sm"
            variant="secondary"
            disabled={disabled}
            icon={<Eye size={14} />}
            onClick={() => onChange(new Set([...selected, ...suggested]))}
          >
            {t('schedule.tabular_import.client_use_suggested', {
              count: suggested.length,
              defaultValue_one: 'Tick the {{count}} row the file suggests',
              defaultValue_other: 'Tick the {{count}} rows the file suggests',
            })}
          </Button>
        )}
        {selected.size > 0 && (
          <Button size="sm" variant="ghost" disabled={disabled} onClick={() => onChange(new Set())}>
            {t('schedule.tabular_import.client_clear', { defaultValue: 'Clear' })}
          </Button>
        )}
        <span className="text-xs text-content-tertiary">
          {t('schedule.tabular_import.client_selected', {
            count: selected.size,
            defaultValue_one: '{{count}} activity visible to the client',
            defaultValue_other: '{{count}} activities visible to the client',
          })}
        </span>
      </div>
      <ul className="max-h-56 divide-y divide-border-light overflow-y-auto rounded-lg border border-border-light">
        {listed.map((activity) => (
          <li key={activity.ref}>
            <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-xs">
              <input
                type="checkbox"
                checked={selected.has(activity.ref)}
                disabled={disabled}
                onChange={() => toggle(activity.ref)}
                className="h-3.5 w-3.5 accent-oe-blue"
              />
              {activity.activity_type === 'milestone' && <Diamond size={12} className="shrink-0 text-oe-blue" />}
              <span className="min-w-0 flex-1 truncate text-content-primary">
                {activity.activity_code ? `${activity.activity_code} · ${activity.name}` : activity.name}
              </span>
              {suggestedSet.has(activity.ref) && (
                <Badge size="sm" variant="neutral">
                  {t('schedule.tabular_import.client_suggested_badge', { defaultValue: 'Suggested by the file' })}
                </Badge>
              )}
            </label>
          </li>
        ))}
      </ul>
      {(hidden > 0 || showAll) && featured.length > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="text-xs font-medium text-oe-blue-text hover:underline"
        >
          {showAll
            ? t('schedule.tabular_import.client_show_featured', {
                defaultValue: 'Show milestones and suggestions only',
              })
            : t('schedule.tabular_import.client_show_all', {
                count: hidden,
                defaultValue_one: 'Show {{count}} more activity',
                defaultValue_other: 'Show {{count}} more activities',
              })}
        </button>
      )}
    </div>
  );
}
