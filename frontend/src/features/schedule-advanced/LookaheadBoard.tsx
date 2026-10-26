// Look-ahead board​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Last Planner look-ahead board: weeks as columns, schedule activities pulled
 * from the master schedule as cards. A card is READY when it has no open
 * constraint, BLOCKED otherwise; a committed card is already promised in a
 * weekly work plan.
 */
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Badge, Card, Skeleton } from '@/shared/ui';
import { useLookAheadBoard, type LpsBoard, type LpsBoardTask } from './api';

function TaskCard({ task }: { task: LpsBoardTask }) {
  const { t } = useTranslation();
  const blockers = task.constraints
    .filter((c) => c.status !== 'cleared')
    .map((c) => c.description || c.constraint_type)
    .join('; ');
  return (
    <div
      data-testid="lps-board-task"
      data-ready={task.is_ready ? 'true' : 'false'}
      title={blockers || undefined}
      className={clsx(
        'rounded-md border bg-surface-primary p-2 text-xs',
        task.is_ready ? 'border-border-light' : 'border-semantic-error/40',
      )}
    >
      <p className="font-medium text-content-primary break-words">
        {task.wbs_code ? `${task.wbs_code} ` : ''}
        {task.name}
      </p>
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        <Badge variant={task.is_ready ? 'success' : 'error'} size="sm" dot>
          {task.is_ready
            ? t('schedule_advanced.board_ready', { defaultValue: 'Ready' })
            : t('schedule_advanced.board_blocked', { defaultValue: 'Blocked' })}
        </Badge>
        {task.open_constraints > 0 && (
          <Badge variant="warning" size="sm">
            {t('schedule_advanced.board_open_constraints', { defaultValue: '{{count}} open constraints', count: task.open_constraints })}
          </Badge>
        )}
        {task.committed && (
          <Badge variant="blue" size="sm">
            {t('schedule_advanced.board_committed', { defaultValue: 'Committed' })}
          </Badge>
        )}
      </div>
      <p className="mt-1 text-2xs text-content-tertiary">
        {task.start_date} - {task.end_date}
      </p>
    </div>
  );
}

export function LookaheadBoardView({ board }: { board: LpsBoard }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="success" dot>
          {t('schedule_advanced.board_ready_count', { defaultValue: '{{count}} ready', count: board.ready_count })}
        </Badge>
        <Badge variant="error" dot>
          {t('schedule_advanced.board_blocked_count', { defaultValue: '{{count}} blocked', count: board.blocked_count })}
        </Badge>
      </div>
      <div className="overflow-x-auto">
        <div className="flex gap-3 min-w-max pb-2">
          {board.weeks.map((week) => {
            const tasks = board.tasks.filter((x) => x.week_start === week);
            return (
              <div key={week} className="w-60 shrink-0 space-y-2" data-testid="lps-board-week">
                <p className="text-xs font-semibold text-content-secondary">
                  {t('schedule_advanced.board_week_of', { defaultValue: 'Week of {{date}}', date: week })}
                </p>
                {tasks.length === 0 ? (
                  <p className="rounded-md border border-dashed border-border-light p-2 text-2xs text-content-tertiary">
                    {t('schedule_advanced.board_week_empty', { defaultValue: 'No activities start this week' })}
                  </p>
                ) : (
                  tasks.map((task) => <TaskCard key={task.task_ref} task={task} />)
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function LookaheadBoard({ lookAheadId }: { lookAheadId: string }) {
  const { t } = useTranslation();
  const q = useLookAheadBoard(lookAheadId);
  return (
    <Card padding="md">
      <h3 className="mb-3 text-sm font-semibold text-content-primary">
        {t('schedule_advanced.board_title', { defaultValue: 'Look-ahead board' })}
      </h3>
      {q.isLoading ? (
        <Skeleton height={96} />
      ) : q.isError || !q.data ? (
        <p className="text-xs text-content-tertiary">
          {t('schedule_advanced.board_error', { defaultValue: 'The board could not be loaded.' })}
        </p>
      ) : q.data.tasks.length === 0 ? (
        <p className="text-xs text-content-tertiary">
          {t('schedule_advanced.board_empty', { defaultValue: 'No schedule activities fall inside this look-ahead window.' })}
        </p>
      ) : (
        <LookaheadBoardView board={q.data} />
      )}
    </Card>
  );
}
