// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * "Feeds": what this request feeds on the programme and in the estimate.
 * A switchboard build is a line on the schedule and a set of BOQ
 * positions, and until now the only place that connection lived was in
 * somebody's head.
 *
 * One schedule activity (a request feeds one line, or none) and any
 * number of BOQ positions. Both are chips that link OUT - to /schedule
 * and to the job's estimate - so the connection is walkable in both
 * directions rather than being a stored id nobody can follow.
 *
 * The pickers are lazy: the activity and position lists are two fan-outs
 * over the project's schedules and BOQs, so they are only fetched once
 * somebody opens a picker, and a failure degrades to an empty list with a
 * line saying so - a request whose programme link cannot be edited still
 * shows the link it has.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { CalendarRange, ListTree, X } from 'lucide-react';
import { fetchBoqPositions, fetchScheduleActivities, type WorkRequest } from './api';
import { WR } from './hooks';
import { Picker, type PickAnchor } from './Pickers';
import { errorText, tintStyle } from './lib';

export function Feeds({
  req,
  onChange,
}: {
  req: WorkRequest;
  onChange: (patch: { schedule_activity_id?: string | null; boq_position_ids?: string[] }) => void;
}) {
  const { t } = useTranslation();
  const [picker, setPicker] = useState<{ at: PickAnchor; what: 'activity' | 'boq' } | null>(null);

  const activities = useQuery({
    queryKey: [WR, 'schedule-activities', req.project_id],
    queryFn: () => fetchScheduleActivities(req.project_id),
    enabled: !!req.project_id && picker?.what === 'activity',
    retry: false,
    staleTime: 300_000,
  });
  const positions = useQuery({
    queryKey: [WR, 'boq-positions', req.project_id],
    queryFn: () => fetchBoqPositions(req.project_id),
    enabled: !!req.project_id && picker?.what === 'boq',
    retry: false,
    staleTime: 300_000,
  });

  const boqIds = useMemo(() => req.boq_position_ids ?? [], [req.boq_position_ids]);
  /**
   * A position's label: the server's own `boq_position_labels` when it
   * resolves them, else whatever the picker has loaded, else the id. The
   * last resort is deliberate - an id is ugly, and it is still a chip
   * that opens the right position, which "1 position" is not.
   */
  const boqLabel = (id: string, i: number): string => {
    const given = req.boq_position_labels?.[i];
    if (given) return given;
    return (positions.data ?? []).find((p) => p.id === id)?.label ?? id;
  };

  const activityLabel =
    req.schedule_activity_name || (activities.data ?? []).find((a) => a.id === req.schedule_activity_id)?.label || req.schedule_activity_id || '';

  const options = picker?.what === 'activity' ? activities.data ?? [] : positions.data ?? [];
  const loadError = picker?.what === 'activity' ? activities.error : positions.error;
  const loading = picker?.what === 'activity' ? activities.isLoading : positions.isLoading;

  return (
    <div className="wr-kv" data-testid="wr-feeds">
      <span className="k">{t('wr.feed_activity', { defaultValue: 'Schedule activity' })}</span>
      <span className="v wr-feeds">
        {req.schedule_activity_id ? (
          <>
            <Link className="wr-chip" to="/schedule" title={activityLabel} data-testid="wr-feed-activity">
              <span className="tag" style={tintStyle('#6136ad')}>
                <CalendarRange size={10} aria-hidden />
              </span>
              <span className="lbl">{activityLabel}</span>
            </Link>
            <button
              type="button"
              className="wr-btn-quiet"
              aria-label={t('wr.feed_clear_activity', { defaultValue: 'Clear the schedule activity' })}
              onClick={() => onChange({ schedule_activity_id: null })}
              data-testid="wr-feed-activity-clear"
            >
              <X size={11} />
            </button>
          </>
        ) : (
          <span className="wr-hint">{t('wr.feed_no_activity', { defaultValue: 'Not linked to the programme.' })}</span>
        )}
        <button type="button" className="wr-btn-quiet" onClick={(e) => setPicker({ at: e.currentTarget, what: 'activity' })} data-testid="wr-feed-activity-pick">
          {req.schedule_activity_id ? t('wr.change', { defaultValue: 'Change…' }) : t('wr.feed_link_activity', { defaultValue: 'Link an activity…' })}
        </button>
      </span>

      <span className="k">{t('wr.feed_boq', { defaultValue: 'BOQ positions' })}</span>
      <span className="v wr-feeds">
        {boqIds.length === 0 && <span className="wr-hint">{t('wr.feed_no_boq', { defaultValue: 'Not booked against the estimate.' })}</span>}
        {boqIds.map((id, i) => (
          <span key={id} className="wr-chip" title={boqLabel(id, i)}>
            <span className="tag" style={tintStyle('#0a6f66')}>
              <ListTree size={10} aria-hidden />
            </span>
            <Link className="lbl" to={`/projects/${encodeURIComponent(req.project_id)}/boq`}>
              {boqLabel(id, i)}
            </Link>
            <button
              type="button"
              className="wr-btn-quiet"
              aria-label={t('wr.feed_remove_boq', { defaultValue: 'Remove this position' })}
              onClick={() => onChange({ boq_position_ids: boqIds.filter((x) => x !== id) })}
            >
              ✕
            </button>
          </span>
        ))}
        <button type="button" className="wr-btn-quiet" onClick={(e) => setPicker({ at: e.currentTarget, what: 'boq' })} data-testid="wr-feed-boq-pick">
          {t('wr.feed_pick_boq', { defaultValue: 'Pick positions…' })}
        </button>
        {boqIds.length > 0 && (
          <button type="button" className="wr-btn-quiet" onClick={() => onChange({ boq_position_ids: [] })} data-testid="wr-feed-boq-clear">
            {t('wr.feed_clear_boq', { defaultValue: 'Clear all' })}
          </button>
        )}
      </span>

      {picker && (
        <Picker
          anchor={picker.at}
          multi={picker.what === 'boq'}
          options={options}
          selected={picker.what === 'activity' ? (req.schedule_activity_id ? [req.schedule_activity_id] : []) : boqIds}
          placeholder={
            picker.what === 'activity'
              ? t('wr.feed_search_activity', { defaultValue: 'Search the programme…' })
              : t('wr.feed_search_boq', { defaultValue: 'Search the estimate…' })
          }
          emptyText={
            loadError
              ? errorText(loadError)
              : loading
                ? t('wr.loading', { defaultValue: 'Loading…' })
                : picker.what === 'activity'
                  ? t('wr.feed_activity_none', { defaultValue: 'This job has no schedule activities yet.' })
                  : t('wr.feed_boq_none', { defaultValue: 'This job has no estimate positions yet.' })
          }
          onClose={() => setPicker(null)}
          onChange={(ids) => {
            if (picker.what === 'activity') onChange({ schedule_activity_id: ids[0] ?? null });
            else onChange({ boq_position_ids: ids });
          }}
        />
      )}
    </div>
  );
}
