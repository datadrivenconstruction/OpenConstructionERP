// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The project's pins as a list: what is pinned where, filterable by record kind, status and
 * revision state. A site manager reads it to see every open NCR on a floor at a glance.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ExternalLink, MapPin } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Badge } from '@/shared/ui';
import { fetchPins, type PinRevisionState, type PinTargetKind, type RegistryPin } from './api';
import { PIN_KINDS, REVISION_STATES, kindMeta, recordPath } from './pinKinds';
import { statusBadgeVariant } from './layers';

interface Props {
  projectId: string;
  /** Limit the list to one drawing; leave out for the whole project. */
  documentId?: string;
  /** Called when a row is clicked, so the page can open that sheet and page. */
  onSelect?: (pin: RegistryPin) => void;
}

export function PinListPanel({ projectId, documentId, onSelect }: Props) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<PinTargetKind | ''>('');
  const [status, setStatus] = useState('');
  const [revision, setRevision] = useState<PinRevisionState | ''>('');

  const { data, isLoading, isError } = useQuery({
    queryKey: ['plan-room-pins', projectId, documentId ?? '', kind, status, revision],
    queryFn: () =>
      fetchPins(projectId, {
        document_id: documentId,
        target_kind: kind,
        status,
        revision_state: revision,
        limit: 200,
      }),
    enabled: !!projectId,
  });

  // The status filter offers the statuses the pins carry, not a fixed list: each record kind has its own.
  const statuses = useQuery({
    queryKey: ['plan-room-pin-statuses', projectId, documentId ?? ''],
    queryFn: () => fetchPins(projectId, { document_id: documentId, limit: 200 }),
    enabled: !!projectId,
    select: (page) => Array.from(new Set(page.items.map((p) => p.status).filter((s): s is string => !!s))).sort(),
  });

  const items = useMemo(() => data?.items ?? [], [data]);
  const selectCls = 'oe-input h-8 py-0 text-xs';

  return (
    <section
      aria-label={t('plan_room.pin_list_title', { defaultValue: 'Pins' })}
      className="rounded-xl border border-border-light bg-surface-primary"
    >
      <header className="flex items-center justify-between gap-2 px-3 pt-3">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('plan_room.pin_list_title', { defaultValue: 'Pins' })}
        </h3>
        <span className="text-xs text-content-tertiary">{data?.total ?? 0}</span>
      </header>

      <div className="grid grid-cols-1 gap-1.5 px-3 py-2 sm:grid-cols-3 lg:grid-cols-1">
        <select
          aria-label={t('plan_room.filter_kind', { defaultValue: 'Record kind' })}
          value={kind}
          onChange={(e) => setKind(e.target.value as PinTargetKind | '')}
          className={selectCls}
        >
          <option value="">{t('plan_room.filter_kind_all', { defaultValue: 'All kinds' })}</option>
          {PIN_KINDS.map((k) => (
            <option key={k.kind} value={k.kind}>
              {t(k.labelKey, { defaultValue: k.defaultLabel })}
            </option>
          ))}
        </select>
        <select
          aria-label={t('plan_room.filter_status', { defaultValue: 'Status' })}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className={selectCls}
        >
          <option value="">{t('plan_room.filter_status_all', { defaultValue: 'Any status' })}</option>
          {(statuses.data ?? []).map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
        <select
          aria-label={t('plan_room.filter_revision', { defaultValue: 'Revision state' })}
          value={revision}
          onChange={(e) => setRevision(e.target.value as PinRevisionState | '')}
          className={selectCls}
        >
          <option value="">{t('plan_room.filter_revision_all', { defaultValue: 'Any revision state' })}</option>
          {REVISION_STATES.map((r) => (
            <option key={r.state} value={r.state}>
              {t(r.labelKey, { defaultValue: r.defaultLabel })}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <p className="px-3 pb-3 text-xs text-content-tertiary">{t('common.loading', { defaultValue: 'Loading...' })}</p>
      ) : isError ? (
        <p className="px-3 pb-3 text-xs text-semantic-error">
          {t('plan_room.pin_list_error', { defaultValue: 'The pins could not be loaded.' })}
        </p>
      ) : items.length === 0 ? (
        <p className="px-3 pb-3 text-xs text-content-tertiary">
          {t('plan_room.pin_list_empty', { defaultValue: 'No pins match. Drop one on the drawing.' })}
        </p>
      ) : (
        <ul className="max-h-80 divide-y divide-border-light overflow-y-auto border-t border-border-light">
          {items.map((pin) => {
            const meta = kindMeta(pin.target_kind);
            const path = recordPath(pin.target_kind, pin.target_id);
            return (
              <li key={pin.id} className="flex items-start gap-2 px-3 py-2">
                <button
                  type="button"
                  onClick={() => onSelect?.(pin)}
                  className="flex min-w-0 flex-1 items-start gap-2 text-left"
                >
                  <MapPin size={14} className="mt-0.5 shrink-0" style={{ color: meta.color }} aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-content-primary">
                      {pin.target_label || pin.note || t(meta.labelKey, { defaultValue: meta.defaultLabel })}
                    </span>
                    <span className="mt-1 flex flex-wrap items-center gap-1">
                      <Badge variant="neutral" size="sm">
                        {t(meta.labelKey, { defaultValue: meta.defaultLabel })}
                      </Badge>
                      {pin.status && (
                        <Badge variant={statusBadgeVariant(pin.status)} size="sm">
                          {pin.status.replace(/_/g, ' ')}
                        </Badge>
                      )}
                      {pin.revision_state !== 'current' && (
                        <Badge variant="warning" size="sm">
                          {t(`plan_room.rev_${pin.revision_state}`, { defaultValue: pin.revision_state })}
                        </Badge>
                      )}
                      {pin.document_id && (
                        <span className="text-2xs text-content-tertiary">
                          {t('plan_room.page_n', { defaultValue: 'Page {{n}}', n: pin.page })}
                        </span>
                      )}
                    </span>
                  </span>
                </button>
                {path && (
                  <Link
                    to={path}
                    aria-label={t('plan_room.open_record', { defaultValue: 'Open record' })}
                    title={t('plan_room.open_record', { defaultValue: 'Open record' })}
                    className="mt-0.5 shrink-0 rounded p-1 text-content-tertiary hover:bg-surface-secondary"
                  >
                    <ExternalLink size={14} />
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
