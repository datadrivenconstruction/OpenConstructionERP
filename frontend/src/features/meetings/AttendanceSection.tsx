// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// AttendanceSection — meeting-minutes-tool-style check-in widget shown inside the
// MeetingRow's expanded panel. Lists current attendees with a check-in
// chip (green ✓ checked, grey pending), offers a "Check me in" button
// for the JWT user, and a small modal for recording walk-in attendees.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Circle, Loader2, UserPlus, Users, X } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  checkIn,
  getAttendance,
  recordExternalAttendee,
  type AttendanceRow,
} from './api';

interface AttendanceSectionProps {
  meetingId: string;
}

/**
 * Decode the `sub` claim (user id) from a JWT access token without
 * external deps. Mirrors the in-store decodeRoleFromToken helper.
 */
function decodeUserIdFromToken(token: string | null): string | null {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1]!.replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    const json = JSON.parse(atob(padded)) as { sub?: string };
    return typeof json.sub === 'string' ? json.sub : null;
  } catch {
    return null;
  }
}

export function AttendanceSection({ meetingId }: AttendanceSectionProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const accessToken = useAuthStore((s) => s.accessToken);
  const currentUserId = useMemo(
    () => decodeUserIdFromToken(accessToken),
    [accessToken],
  );

  const [showExternalModal, setShowExternalModal] = useState(false);
  const [externalName, setExternalName] = useState('');

  const attendanceQ = useQuery<AttendanceRow[]>({
    queryKey: ['meeting-attendance', meetingId],
    queryFn: () => getAttendance(meetingId),
    staleTime: 30_000,
  });

  const checkInMut = useMutation({
    mutationFn: () => checkIn(meetingId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['meeting-attendance', meetingId] });
      addToast({
        type: 'success',
        title: t('meetings.checked_in', { defaultValue: 'Checked in' }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('meetings.check_in_failed', { defaultValue: 'Check-in failed' }),
        message: e.message,
      });
    },
  });

  const externalMut = useMutation({
    mutationFn: (name: string) => recordExternalAttendee(meetingId, name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['meeting-attendance', meetingId] });
      setShowExternalModal(false);
      setExternalName('');
      addToast({
        type: 'success',
        title: t('meetings.external_added', {
          defaultValue: 'External attendee added',
        }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('meetings.external_failed', {
          defaultValue: 'Could not add external attendee',
        }),
        message: e.message,
      });
    },
  });

  const rows = attendanceQ.data ?? [];
  const userAlreadyCheckedIn = !!(
    currentUserId &&
    rows.find((r) => r.user_id === currentUserId && !!r.checked_in_at)
  );

  return (
    <div
      className="rounded-lg bg-surface-secondary p-3"
      data-testid="meeting-attendance-section"
    >
      <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
        <p className="text-xs text-content-tertiary font-medium uppercase tracking-wide flex items-center gap-1.5">
          <Users size={12} />
          {t('meetings.attendance', { defaultValue: 'Attendance' })}
          {rows.length > 0 && (
            <span className="text-content-secondary normal-case font-normal">
              ({rows.length})
            </span>
          )}
        </p>
        <div className="flex items-center gap-1.5">
          <Button
            variant="secondary"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              setShowExternalModal(true);
            }}
            data-testid="meeting-attendance-add-external"
          >
            <UserPlus size={14} className="mr-1.5" />
            {t('meetings.add_external', { defaultValue: 'Add external' })}
          </Button>
          {currentUserId && !userAlreadyCheckedIn && (
            <Button
              variant="primary"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                checkInMut.mutate();
              }}
              disabled={checkInMut.isPending}
              data-testid="meeting-attendance-check-in"
            >
              {checkInMut.isPending ? (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              ) : (
                <CheckCircle2 size={14} className="mr-1.5" />
              )}
              {t('meetings.check_me_in', { defaultValue: 'Check me in' })}
            </Button>
          )}
        </div>
      </div>

      {attendanceQ.isLoading ? (
        <p className="text-xs text-content-tertiary">
          <Loader2 size={12} className="inline animate-spin mr-1" />
          {t('common.loading', { defaultValue: 'Loading…' })}
        </p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-content-tertiary italic">
          {t('meetings.no_attendance', {
            defaultValue: 'No one has checked in yet.',
          })}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map((row) => {
            const checked = !!row.checked_in_at;
            const label =
              row.external_name ||
              (row.user_id ? `User ${row.user_id.slice(0, 8)}` : '—');
            return (
              <li key={row.id} className="flex items-center gap-2 text-sm">
                {checked ? (
                  <CheckCircle2
                    size={14}
                    className="text-semantic-success shrink-0"
                    aria-label={t('meetings.attendance_checked', {
                      defaultValue: 'Checked in',
                    })}
                  />
                ) : (
                  <Circle
                    size={14}
                    className="text-content-tertiary shrink-0"
                    aria-label={t('meetings.attendance_pending', {
                      defaultValue: 'Pending',
                    })}
                  />
                )}
                <span className="text-content-primary">{label}</span>
                {row.external_name && (
                  <span className="text-2xs text-content-tertiary uppercase tracking-wide">
                    {t('meetings.external_badge', { defaultValue: 'External' })}
                  </span>
                )}
                {checked && row.checked_in_at && (
                  <span className="text-xs text-content-tertiary ml-auto">
                    {new Date(row.checked_in_at).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {/* Add-external modal — small inline portal-free dialog */}
      {showExternalModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={(e) => {
            e.stopPropagation();
            setShowExternalModal(false);
          }}
        >
          <div
            className="w-full max-w-sm rounded-xl bg-surface-primary shadow-xl border border-border p-5"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="external-attendee-title"
          >
            <div className="flex items-center justify-between mb-3">
              <h3
                id="external-attendee-title"
                className="text-sm font-semibold text-content-primary"
              >
                {t('meetings.add_external_title', {
                  defaultValue: 'Add external attendee',
                })}
              </h3>
              <button
                type="button"
                onClick={() => setShowExternalModal(false)}
                className="text-content-tertiary hover:text-content-primary"
                aria-label={t('common.close', { defaultValue: 'Close' })}
              >
                <X size={16} />
              </button>
            </div>
            <label className="block text-xs font-medium text-content-primary mb-1.5">
              {t('meetings.external_name_label', { defaultValue: 'Full name' })}
            </label>
            <input
              type="text"
              value={externalName}
              onChange={(e) => setExternalName(e.target.value)}
              autoFocus
              placeholder={t('meetings.external_name_placeholder', {
                defaultValue: 'Jane Walker',
              })}
              className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && externalName.trim()) {
                  externalMut.mutate(externalName.trim());
                }
              }}
            />
            <div className="flex justify-end gap-2 mt-4">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowExternalModal(false)}
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => externalMut.mutate(externalName.trim())}
                disabled={!externalName.trim() || externalMut.isPending}
              >
                {externalMut.isPending ? (
                  <Loader2 size={14} className="mr-1.5 animate-spin" />
                ) : null}
                {t('meetings.add_external_action', { defaultValue: 'Add' })}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
