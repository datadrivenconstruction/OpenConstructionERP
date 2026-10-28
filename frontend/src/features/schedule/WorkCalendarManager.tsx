// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Work-calendar editor (#348). Create, edit and delete the project's named
// work calendars: a work-week (the seven Mon..Sun toggles map to ``work_days``
// ints, Mon=0 .. Sun=6), hours per day, a holiday list (ISO dates) and a single
// project default. Individual activities pick one of these in the Table view
// (see ActivityGrid); an unassigned activity uses the project default. Every
// edit writes through the schedule-advanced calendar CRUD and refetches the
// project's calendar list. Deletion uses an inline confirm affordance rather
// than a modal / window.confirm, which the environment does not support.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CalendarDays, Plus, Trash2, Star, X, CalendarOff, Loader2 } from 'lucide-react';
import { Button, Card, Badge, Input, EmptyState } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  listCalendars,
  createCalendar,
  updateCalendar,
  deleteCalendar,
  type ScheduleCalendar,
  type ScheduleCalendarUpdateBody,
} from '@/features/schedule-advanced/api';

/** The seven weekdays, in Mon..Sun order, mapped to ``work_days`` ints (Mon=0). */
const WEEKDAYS: { day: number; key: string; label: string }[] = [
  { day: 0, key: 'mon', label: 'Mon' },
  { day: 1, key: 'tue', label: 'Tue' },
  { day: 2, key: 'wed', label: 'Wed' },
  { day: 3, key: 'thu', label: 'Thu' },
  { day: 4, key: 'fri', label: 'Fri' },
  { day: 5, key: 'sat', label: 'Sat' },
  { day: 6, key: 'sun', label: 'Sun' },
];

/**
 * Project-scoped work-calendar manager. Lists the project's calendars and lets
 * the planner create one, edit it (name, weekday toggles, hours/day, holidays,
 * default flag) and delete it. The per-activity picker (ActivityGrid) reads the
 * same ``['schedule-calendars', projectId]`` query.
 */
export function WorkCalendarManager({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [newName, setNewName] = useState('');

  const calendarsKey = ['schedule-calendars', projectId];

  const { data: calendars = [], isLoading } = useQuery({
    queryKey: calendarsKey,
    queryFn: () => listCalendars(projectId),
    enabled: !!projectId,
  });

  const createMutation = useMutation({
    mutationFn: (name: string) =>
      createCalendar({
        project_id: projectId,
        name,
        // Sensible default: a five-day Mon..Fri week at 8h/day. Everything is
        // editable on the card once it exists. The first calendar becomes the
        // project default so activities have something to inherit.
        work_days: [0, 1, 2, 3, 4],
        work_hours_per_day: 8,
        holidays: [],
        is_default: calendars.length === 0,
      }),
    onSuccess: async () => {
      setNewName('');
      await queryClient.invalidateQueries({ queryKey: calendarsKey });
      addToast({
        type: 'success',
        title: t('schedule.calendar.created', { defaultValue: 'Calendar created' }),
      });
    },
    onError: (error: Error) =>
      addToast({
        type: 'error',
        title: t('toasts.error', { defaultValue: 'Error' }),
        message: error.message,
      }),
  });

  const submitCreate = () => {
    const name = newName.trim();
    if (!name) return;
    createMutation.mutate(name);
  };

  return (
    <div data-testid="work-calendar-manager" className="space-y-4">
      {/* Header + create row */}
      <Card padding="md">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
              <CalendarDays size={15} className="text-oe-blue" />
              {t('schedule.calendar.title', { defaultValue: 'Work calendars' })}
            </div>
            <p className="mt-0.5 max-w-xl text-xs text-content-tertiary">
              {t('schedule.calendar.description', {
                defaultValue:
                  'Named work weeks and holiday sets. Assign one to an activity in the Table view; unassigned activities use the project default.',
              })}
            </p>
          </div>
          <div className="flex items-end gap-2">
            <Input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  submitCreate();
                }
              }}
              placeholder={t('schedule.calendar.new_name_placeholder', {
                defaultValue: 'New calendar name...',
              })}
              aria-label={t('schedule.calendar.new_name_placeholder', {
                defaultValue: 'New calendar name...',
              })}
              data-testid="calendar-new-name"
              className="w-56"
            />
            <Button
              variant="primary"
              icon={<Plus size={15} />}
              data-testid="calendar-add"
              disabled={!newName.trim()}
              loading={createMutation.isPending}
              onClick={submitCreate}
            >
              {t('schedule.calendar.create', { defaultValue: 'Add calendar' })}
            </Button>
          </div>
        </div>
      </Card>

      {/* Calendar list */}
      {isLoading ? (
        <div className="flex items-center gap-2 p-4 text-sm text-content-secondary">
          <Loader2 size={15} className="animate-spin" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      ) : calendars.length === 0 ? (
        <EmptyState
          icon={<CalendarDays size={40} />}
          title={t('schedule.calendar.empty_title', { defaultValue: 'No work calendars yet' })}
          description={t('schedule.calendar.empty_desc', {
            defaultValue:
              'Create a calendar to define a work week and holidays, then assign it to activities in the Table view.',
          })}
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {calendars.map((cal) => (
            <CalendarCard key={cal.id} calendar={cal} projectId={projectId} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── One editable calendar card ────────────────────────────────────────────── */

function CalendarCard({
  calendar,
  projectId,
}: {
  calendar: ScheduleCalendar;
  projectId: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [newHoliday, setNewHoliday] = useState('');

  const calendarsKey = ['schedule-calendars', projectId];
  const invalidate = () => queryClient.invalidateQueries({ queryKey: calendarsKey });

  const onError = (error: Error) =>
    addToast({
      type: 'error',
      title: t('toasts.error', { defaultValue: 'Error' }),
      message: error.message,
    });

  const patchMutation = useMutation({
    mutationFn: (patch: ScheduleCalendarUpdateBody) => updateCalendar(calendar.id, patch),
    onSuccess: invalidate,
    onError: (error: Error) => {
      onError(error);
      // Refetch so a rejected edit reverts to the stored value.
      invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteCalendar(calendar.id),
    onSuccess: async () => {
      await invalidate();
      addToast({
        type: 'success',
        title: t('schedule.calendar.deleted', { defaultValue: 'Calendar deleted' }),
      });
    },
    onError,
  });

  const busy = patchMutation.isPending || deleteMutation.isPending;
  const hours = Number(calendar.work_hours_per_day);
  const holidays = [...calendar.holidays].sort();

  const toggleDay = (day: number) => {
    const set = new Set(calendar.work_days);
    if (set.has(day)) set.delete(day);
    else set.add(day);
    patchMutation.mutate({ work_days: [...set].sort((a, b) => a - b) });
  };

  const addHoliday = () => {
    const d = newHoliday.slice(0, 10);
    setNewHoliday('');
    if (!d || calendar.holidays.includes(d)) return;
    patchMutation.mutate({ holidays: [...calendar.holidays, d].sort() });
  };

  const removeHoliday = (d: string) => {
    patchMutation.mutate({ holidays: calendar.holidays.filter((h) => h !== d) });
  };

  return (
    <Card padding="md" data-testid={`calendar-card-${calendar.id}`} className="space-y-3">
      {/* Name + default + delete */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          key={`name-${calendar.id}-${calendar.name}`}
          defaultValue={calendar.name}
          aria-label={t('schedule.calendar.name_label', { defaultValue: 'Name' })}
          data-testid={`calendar-name-${calendar.id}`}
          disabled={busy}
          onBlur={(e) => {
            const name = e.target.value.trim();
            if (name && name !== calendar.name) patchMutation.mutate({ name });
          }}
          className="min-w-[8rem] flex-1"
        />
        {calendar.is_default && (
          <Badge variant="blue" size="sm">
            {t('schedule.calendar.default_badge', { defaultValue: 'Default' })}
          </Badge>
        )}
        <button
          type="button"
          aria-pressed={calendar.is_default}
          aria-label={t('schedule.calendar.set_default', { defaultValue: 'Set as default' })}
          disabled={busy || calendar.is_default}
          data-testid={`calendar-default-${calendar.id}`}
          onClick={() => patchMutation.mutate({ is_default: true })}
          title={t('schedule.calendar.set_default', { defaultValue: 'Set as default' })}
          className={`rounded-lg p-1.5 transition-colors disabled:opacity-50 ${
            calendar.is_default
              ? 'text-oe-blue'
              : 'text-content-tertiary hover:bg-surface-secondary hover:text-oe-blue'
          }`}
        >
          <Star size={15} fill={calendar.is_default ? 'currentColor' : 'none'} />
        </button>
        {confirmingDelete ? (
          <span className="flex items-center gap-1">
            <Button
              variant="danger"
              size="sm"
              data-testid={`calendar-delete-confirm-${calendar.id}`}
              loading={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate()}
            >
              {t('schedule.calendar.confirm_yes', { defaultValue: 'Delete' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={deleteMutation.isPending}
              onClick={() => setConfirmingDelete(false)}
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </span>
        ) : (
          <button
            type="button"
            aria-label={t('schedule.calendar.delete', { defaultValue: 'Delete calendar' })}
            data-testid={`calendar-delete-${calendar.id}`}
            disabled={busy}
            onClick={() => setConfirmingDelete(true)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-semantic-error-bg hover:text-semantic-error disabled:opacity-50"
          >
            <Trash2 size={15} />
          </button>
        )}
      </div>

      {confirmingDelete && (
        <p className="text-xs text-semantic-error">
          {t('schedule.calendar.confirm_delete', {
            defaultValue:
              'Delete this calendar? Activities using it fall back to the project default.',
          })}
        </p>
      )}

      {/* Weekday toggles */}
      <div>
        <div className="mb-1 text-xs font-medium text-content-secondary">
          {t('schedule.calendar.work_days', { defaultValue: 'Work days' })}
        </div>
        <div className="flex flex-wrap gap-1">
          {WEEKDAYS.map((w) => {
            const active = calendar.work_days.includes(w.day);
            return (
              <button
                key={w.day}
                type="button"
                aria-pressed={active}
                disabled={busy}
                data-testid={`calendar-${calendar.id}-day-${w.day}`}
                onClick={() => toggleDay(w.day)}
                className={`min-w-[2.75rem] rounded-md border px-2 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
                  active
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-border-light text-content-tertiary hover:bg-surface-secondary'
                }`}
              >
                {t(`schedule.calendar.weekday_${w.key}`, { defaultValue: w.label })}
              </button>
            );
          })}
        </div>
      </div>

      {/* Hours per day */}
      <label className="flex items-center gap-2 text-xs font-medium text-content-secondary">
        {t('schedule.calendar.hours_per_day', { defaultValue: 'Hours per day' })}
        <Input
          key={`hours-${calendar.id}-${hours}`}
          type="number"
          min={1}
          max={24}
          step={0.5}
          defaultValue={String(hours)}
          disabled={busy}
          data-testid={`calendar-hours-${calendar.id}`}
          aria-label={t('schedule.calendar.hours_per_day', { defaultValue: 'Hours per day' })}
          onBlur={(e) => {
            const n = e.target.valueAsNumber;
            if (!Number.isNaN(n) && n > 0 && n !== hours) {
              patchMutation.mutate({ work_hours_per_day: n });
            }
          }}
          className="w-24"
        />
      </label>

      {/* Holidays */}
      <div>
        <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-content-secondary">
          <CalendarOff size={13} />
          {t('schedule.calendar.holidays', { defaultValue: 'Holidays' })}
        </div>
        {holidays.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('schedule.calendar.no_holidays', { defaultValue: 'No holidays. Add a date below.' })}
          </p>
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {holidays.map((h) => (
              <li
                key={h}
                className="flex items-center gap-1 rounded-full border border-border-light bg-surface-secondary/50 py-0.5 pl-2 pr-1 text-xs tabular-nums text-content-secondary"
              >
                {h}
                <button
                  type="button"
                  aria-label={t('schedule.calendar.remove_holiday', {
                    defaultValue: 'Remove holiday',
                  })}
                  data-testid={`calendar-${calendar.id}-holiday-remove-${h}`}
                  disabled={busy}
                  onClick={() => removeHoliday(h)}
                  className="flex h-4 w-4 items-center justify-center rounded-full text-content-tertiary transition-colors hover:bg-semantic-error-bg hover:text-semantic-error disabled:opacity-50"
                >
                  <X size={11} />
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-2 flex items-center gap-2">
          <Input
            type="date"
            value={newHoliday}
            disabled={busy}
            aria-label={t('schedule.calendar.add_holiday', { defaultValue: 'Add holiday' })}
            data-testid={`calendar-holiday-input-${calendar.id}`}
            onChange={(e) => setNewHoliday(e.target.value)}
            className="w-40"
          />
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={14} />}
            data-testid={`calendar-holiday-add-${calendar.id}`}
            disabled={busy || !newHoliday}
            onClick={addHoliday}
          >
            {t('schedule.calendar.add_holiday', { defaultValue: 'Add holiday' })}
          </Button>
        </div>
      </div>
    </Card>
  );
}
