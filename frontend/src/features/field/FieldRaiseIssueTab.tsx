// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Field "Raise issue" tab - a site worker flags a defect from their phone.
 *
 * Dead-simple, thumb-zone form: title, priority, an optional note, an optional
 * photo straight from the device camera, and an optional GPS pin. On submit the
 * punch CREATE is captured through the shared offline mutation queue so it
 * survives no-signal and replays idempotently with the field-session headers
 * (see `raiseIssueApi.ts` for why the field-native capture endpoint is used
 * rather than the desktop punchlist route).
 *
 * The photo cannot ride the same queue - its sender is JSON-only and there is
 * no op-to-op dependency to carry the not-yet-known punch id - so it degrades
 * gracefully: the photo is parked as a durable record keyed by the create's
 * `client_op_id` and uploaded on the next online sync once the created punch id
 * is known (from the live drain results, or the server ledger after a reload).
 * The issue itself is never blocked on the photo.
 *
 * Every interactive element stays >=48px per the shell's touch-target rule.
 */

import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { canStore, downscalePhoto, readStorageEstimate } from '@/shared/lib/offline/storageQuota';
import {
  AlertTriangle,
  Camera,
  Check,
  CloudOff,
  Loader2,
  MapPin,
  Send,
  Trash2,
  X,
} from 'lucide-react';
import {
  isOnline,
  newClientOpId,
  type DrainResult,
  type EnqueueInput,
  type QueuedOp,
} from '@/shared/lib/offline';
import type { PunchPriority } from '../punchlist/api';
import type { FieldSession } from './fieldApi';
import {
  RAISE_ISSUE_KIND,
  buildPunchCreateBody,
  resolveSyncedPunchIds,
  uploadFieldPunchPhoto,
  type RaiseIssueGeo,
} from './raiseIssueApi';
import {
  listRaisedIssues,
  markPhotoUploaded,
  pendingPhotoRecords,
  saveRaisedIssue,
  type RaisedIssueRecord,
} from './raisedIssuesStore';

type Enqueue = (input: EnqueueInput) => Promise<void>;

interface FieldRaiseIssueTabProps {
  session: FieldSession | null;
  enqueue: Enqueue;
  /** Live queue contents - drives the per-issue "Queued vs Sent" state. */
  pendingOps: QueuedOp[];
  /** Most recent drain outcomes - the fast path to a just-created punch id. */
  lastResults: DrainResult[];
  online: boolean;
}

interface PriorityOption {
  value: PunchPriority;
  labelKey: string;
  defaultLabel: string;
  /** Classes for the chip when it is the selected priority. */
  activeClass: string;
  /** The status-dot colour used in the recent-issues list. */
  dotClass: string;
}

const PRIORITIES: readonly PriorityOption[] = [
  {
    value: 'low',
    labelKey: 'field.issue_priority_low',
    defaultLabel: 'Low',
    activeClass: 'border-border bg-surface-secondary text-content-primary',
    dotClass: 'bg-border',
  },
  {
    value: 'medium',
    labelKey: 'field.issue_priority_medium',
    defaultLabel: 'Medium',
    activeClass: 'border-semantic-info/60 bg-semantic-info-bg text-semantic-info',
    dotClass: 'bg-semantic-info',
  },
  {
    value: 'high',
    labelKey: 'field.issue_priority_high',
    defaultLabel: 'High',
    activeClass: 'border-semantic-warning/60 bg-semantic-warning-bg text-semantic-warning',
    dotClass: 'bg-semantic-warning',
  },
  {
    value: 'critical',
    labelKey: 'field.issue_priority_critical',
    defaultLabel: 'Critical',
    activeClass: 'border-semantic-error/60 bg-semantic-error-bg text-semantic-error',
    dotClass: 'bg-semantic-error',
  },
] as const;

function priorityDot(priority: PunchPriority): string {
  return PRIORITIES.find((p) => p.value === priority)?.dotClass ?? 'bg-border';
}

export function FieldRaiseIssueTab({
  session,
  enqueue,
  pendingOps,
  lastResults,
  online,
}: FieldRaiseIssueTabProps) {
  const { t } = useTranslation();

  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState<PunchPriority>('medium');
  const [note, setNote] = useState('');
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [storageFull, setStorageFull] = useState(false);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [geo, setGeo] = useState<RaiseIssueGeo | null>(null);
  const [geoBusy, setGeoBusy] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [records, setRecords] = useState<RaisedIssueRecord[]>([]);

  const reconcilingRef = useRef(false);

  const refresh = useCallback(async () => {
    setRecords(await listRaisedIssues());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Revoke each preview object URL when it is replaced and on unmount, so a
  // stream of retakes never leaks blobs. Keyed on the URL so the cleanup frees
  // the value it captured, not a newer one.
  useEffect(() => {
    if (!photoPreview) return undefined;
    return () => URL.revokeObjectURL(photoPreview);
  }, [photoPreview]);

  /**
   * Upload any parked photos whose create has synced. Resolves the created punch
   * id from the live drain results first (same session, no network), then from
   * the server ledger (durable, survives a reload). Serialised via a ref so two
   * effect firings cannot double-upload.
   */
  const reconcilePhotos = useCallback(async () => {
    if (!session || !isOnline() || reconcilingRef.current) return;
    reconcilingRef.current = true;
    try {
      const pending = await pendingPhotoRecords();
      if (pending.length === 0) return;

      const resolved = new Map<string, string>();
      for (const rec of pending) {
        const hit = lastResults.find(
          (r) => r.clientOpId === rec.clientOpId && r.resultId,
        );
        if (hit?.resultId) resolved.set(rec.clientOpId, hit.resultId);
        else if (rec.punchId) resolved.set(rec.clientOpId, rec.punchId);
      }

      const unresolved = pending
        .filter((rec) => !resolved.has(rec.clientOpId))
        .map((rec) => rec.clientOpId);
      if (unresolved.length > 0) {
        const durable = await resolveSyncedPunchIds(session, unresolved);
        durable.forEach((punchId, opId) => resolved.set(opId, punchId));
      }

      let changed = false;
      for (const rec of pending) {
        const punchId = resolved.get(rec.clientOpId);
        if (!punchId || !rec.photo) continue;
        const ok = await uploadFieldPunchPhoto(
          session,
          punchId,
          rec.clientOpId,
          rec.photo,
          rec.photoName ?? 'photo.jpg',
        );
        if (ok) {
          await markPhotoUploaded(rec.clientOpId, punchId);
          changed = true;
        }
      }
      if (changed) await refresh();
    } finally {
      reconcilingRef.current = false;
    }
  }, [session, lastResults, refresh]);

  // Re-run reconciliation whenever a drain finishes (lastResults), connectivity
  // returns (online), or the record set changes (a new photo was parked / an
  // upload cleared one). Converges: an uploaded photo drops out of the pending
  // set, so a run with nothing to do makes no state change.
  useEffect(() => {
    void reconcilePhotos();
  }, [reconcilePhotos, online, records]);

  const clearPhoto = useCallback(() => {
    // The `[photoPreview]` effect revokes the old URL when it changes to null.
    setPhotoFile(null);
    setPhotoPreview(null);
  }, []);

  const onPickPhoto = useCallback(async (e: ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0];
    // Reset the input so re-picking the same file still fires onChange.
    e.target.value = '';
    if (!picked) return;
    // Shrink before it is stored, and refuse when the phone is nearly full.
    const small = await downscalePhoto(picked);
    const file =
      small === picked ? picked : new File([small], picked.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' });
    if (!canStore(file.size, await readStorageEstimate())) {
      setStorageFull(true);
      return;
    }
    setStorageFull(false);
    setPhotoFile(file);
    // The `[photoPreview]` effect revokes the previous URL when this replaces it.
    setPhotoPreview(URL.createObjectURL(file));
  }, []);

  const captureGeo = useCallback(() => {
    setGeoError(null);
    if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
      setGeoError(
        t('field.issue_geo_unavailable', {
          defaultValue: 'Location is not available on this device.',
        }),
      );
      return;
    }
    setGeoBusy(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGeo({
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracyM: Number.isFinite(pos.coords.accuracy) ? pos.coords.accuracy : undefined,
        });
        setGeoBusy(false);
      },
      () => {
        setGeoError(
          t('field.issue_geo_denied', {
            defaultValue: 'Could not get your location. Check the app permission.',
          }),
        );
        setGeoBusy(false);
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 },
    );
  }, [t]);

  const submit = useCallback(async () => {
    if (!session) return;
    const trimmedTitle = title.trim();
    if (!trimmedTitle) return;

    const clientOpId = newClientOpId();
    const capturedAt = new Date().toISOString();

    // 1) The punch create rides the durable offline queue (idempotent, replayed
    //    with the field-session headers).
    await enqueue({
      clientOpId,
      method: 'POST',
      path: '/v1/field-diary/capture/punch/',
      kind: RAISE_ISSUE_KIND,
      body: buildPunchCreateBody({
        title: trimmedTitle,
        description: note.trim(),
        priority,
        capturedAt,
        geo,
      }),
    });

    // 2) Park the issue (and its photo, if any) as a durable record so the tab
    //    shows it across a reload and the photo uploads on the next sync.
    await saveRaisedIssue({
      clientOpId,
      title: trimmedTitle,
      priority,
      createdAt: Date.now(),
      hasPhoto: photoFile !== null,
      photoPending: photoFile !== null,
      photo: photoFile ?? undefined,
      photoName: photoFile?.name,
    });

    // Reset the form for the next capture.
    setTitle('');
    setNote('');
    setPriority('medium');
    clearPhoto();
    setGeo(null);
    setGeoError(null);
    setSavedAt(Date.now());
    await refresh();
    // If we are already online the create may drain immediately; try the photo.
    void reconcilePhotos();
  }, [session, title, note, priority, geo, photoFile, enqueue, clearPhoto, refresh, reconcilePhotos]);

  if (!session) {
    return (
      <p className="px-4 py-8 text-center text-content-tertiary">
        {t('field.no_session', { defaultValue: 'Open the link from your SMS to start.' })}
      </p>
    );
  }

  const canSubmit = title.trim().length > 0;

  return (
    <div className="flex w-full flex-col gap-4 px-4 py-4">
      <div>
        <h2 className="flex items-center gap-1.5 text-base font-semibold text-content-primary">
          <AlertTriangle size={20} className="text-semantic-warning" aria-hidden="true" />
          {t('field.issue_title', { defaultValue: 'Raise a site issue' })}
        </h2>
        <p className="mt-0.5 text-xs text-content-tertiary">
          {t('field.issue_intro', {
            defaultValue: 'Flag a defect with a photo. It saves offline and sends when you are back online.',
          })}
        </p>
      </div>

      {/* Title */}
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-content-secondary">
          {t('field.issue_field_title', { defaultValue: 'What is the issue?' })}
        </span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('field.issue_title_placeholder', {
            defaultValue: 'e.g. Cracked tile in stairwell',
          })}
          maxLength={255}
          className="oe-input oe-input-lg h-12 text-base"
        />
      </label>

      {/* Priority */}
      <div className="flex flex-col gap-1 text-sm">
        <span className="text-content-secondary">
          {t('field.issue_priority', { defaultValue: 'Priority' })}
        </span>
        <div className="grid grid-cols-4 gap-2">
          {PRIORITIES.map((p) => {
            const active = p.value === priority;
            return (
              <button
                key={p.value}
                type="button"
                aria-pressed={active}
                onClick={() => setPriority(p.value)}
                className={`h-11 rounded-xl border text-sm font-medium ${
                  active ? p.activeClass : 'border-border bg-surface-primary text-content-secondary'
                }`}
              >
                {t(p.labelKey, { defaultValue: p.defaultLabel })}
              </button>
            );
          })}
        </div>
      </div>

      {/* Note */}
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-content-secondary">
          {t('field.issue_note', { defaultValue: 'Details (optional)' })}
        </span>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          maxLength={5000}
          className="oe-textarea"
        />
      </label>

      {/* Photo */}
      <div className="flex flex-col gap-2 text-sm">
        <span className="text-content-secondary">{t('field.issue_photo', { defaultValue: 'Photo' })}</span>
        {photoPreview ? (
          <div className="relative overflow-hidden rounded-xl border border-border-light">
            <img
              src={photoPreview}
              alt={t('field.issue_photo_alt', { defaultValue: 'Preview of what you are flagging' })}
              className="max-h-56 w-full object-cover"
            />
            <button
              type="button"
              onClick={clearPhoto}
              aria-label={t('field.issue_photo_remove', { defaultValue: 'Remove photo' })}
              className="absolute right-2 top-2 flex h-10 w-10 items-center justify-center rounded-full bg-slate-900/60 text-white"
            >
              <X size={20} aria-hidden="true" />
            </button>
          </div>
        ) : (
          <label className="flex h-14 cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-surface-secondary text-base font-medium text-content-secondary">
            <input
              type="file"
              accept="image/*"
              capture="environment"
              className="sr-only"
              onChange={(e) => void onPickPhoto(e)}
            />
            <Camera size={22} aria-hidden="true" />
            {t('field.issue_photo_take', { defaultValue: 'Take a photo' })}
          </label>
        )}
        {storageFull && (
          <p role="alert" data-testid="photo-storage-full" className="mt-2 text-sm text-semantic-error">
            {t('field.quota.warning', {
              defaultValue: 'Phone storage is almost full. Sync soon so photos are not lost.',
            })}
          </p>
        )}
      </div>

      {/* Location */}
      <div className="flex flex-col gap-2 text-sm">
        <span className="text-content-secondary">
          {t('field.issue_location', { defaultValue: 'Location (optional)' })}
        </span>
        {geo ? (
          <div className="flex items-center justify-between gap-2 rounded-xl border border-border-light bg-surface-secondary px-3 py-2">
            <span className="flex min-w-0 items-center gap-2 text-sm text-content-secondary">
              <MapPin size={20} className="shrink-0 text-semantic-success" aria-hidden="true" />
              <span className="truncate">
                {geo.lat.toFixed(5)}, {geo.lon.toFixed(5)}
                {typeof geo.accuracyM === 'number' && (
                  <span className="text-content-tertiary">
                    {' '}
                    {t('field.issue_geo_accuracy', {
                      defaultValue: '+/-{{m}} m',
                      m: Math.round(geo.accuracyM),
                    })}
                  </span>
                )}
              </span>
            </span>
            <button
              type="button"
              onClick={() => setGeo(null)}
              aria-label={t('field.issue_geo_remove', { defaultValue: 'Remove location' })}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-content-tertiary hover:bg-surface-tertiary"
            >
              <Trash2 size={20} aria-hidden="true" />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={captureGeo}
            disabled={geoBusy}
            className="flex h-12 items-center justify-center gap-2 rounded-xl border border-border bg-white text-base font-medium text-content-secondary disabled:opacity-50"
          >
            {geoBusy ? (
              <Loader2 size={20} className="animate-spin" aria-hidden="true" />
            ) : (
              <MapPin size={20} aria-hidden="true" />
            )}
            {t('field.issue_geo_add', { defaultValue: 'Add my location' })}
          </button>
        )}
        {geoError && <p className="text-xs text-semantic-error">{geoError}</p>}
      </div>

      {/* Submit */}
      <button
        type="button"
        onClick={() => void submit()}
        disabled={!canSubmit}
        className="flex h-14 items-center justify-center gap-2 rounded-xl bg-semantic-warning text-base font-semibold text-white disabled:opacity-50"
      >
        <Send size={20} aria-hidden="true" />
        {t('field.issue_submit', { defaultValue: 'Raise issue' })}
      </button>
      {savedAt !== null && (
        <p className="text-center text-sm text-semantic-success">
          {online
            ? t('field.issue_saved_online', { defaultValue: 'Issue raised. Sending to the office.' })
            : t('field.issue_saved_offline', {
                defaultValue: 'Saved. It will send when you are back online.',
              })}
        </p>
      )}

      {/* Recently raised */}
      {records.length > 0 && (
        <div className="mt-2 flex flex-col gap-2 border-t border-border-light pt-3">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('field.issue_recent', { defaultValue: 'Recently raised' })}
          </h3>
          <ul className="flex flex-col gap-2">
            {records.slice(0, 8).map((rec) => {
              const queued = pendingOps.some((o) => o.clientOpId === rec.clientOpId);
              return (
                <li key={rec.clientOpId} className="rounded-xl border border-border-light p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span
                        className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${priorityDot(rec.priority)}`}
                        aria-hidden="true"
                      />
                      <span className="truncate text-sm font-medium text-content-primary">
                        {rec.title}
                      </span>
                    </div>
                    <span className="shrink-0 text-2xs text-content-tertiary">
                      {new Date(rec.createdAt).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {queued ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-semantic-warning-bg px-2 py-0.5 text-2xs font-medium text-semantic-warning">
                        <CloudOff size={12} aria-hidden="true" />
                        {t('field.issue_state_queued', { defaultValue: 'Queued' })}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-semantic-success-bg px-2 py-0.5 text-2xs font-medium text-semantic-success">
                        <Check size={12} aria-hidden="true" />
                        {t('field.issue_state_sent', { defaultValue: 'Sent' })}
                      </span>
                    )}
                    {rec.hasPhoto &&
                      (rec.photoPending ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-0.5 text-2xs font-medium text-content-secondary">
                          <Camera size={12} aria-hidden="true" />
                          {t('field.issue_photo_waiting', { defaultValue: 'Photo waiting' })}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-semantic-success-bg px-2 py-0.5 text-2xs font-medium text-semantic-success">
                          <Camera size={12} aria-hidden="true" />
                          {t('field.issue_photo_sent', { defaultValue: 'Photo sent' })}
                        </span>
                      ))}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

export default FieldRaiseIssueTab;
