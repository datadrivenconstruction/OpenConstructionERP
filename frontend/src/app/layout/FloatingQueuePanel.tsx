/**
 * Floating queue panel — always visible at bottom-right when tasks are active.
 *
 * Shows progress for CAD conversions and file uploads. Persists across navigation.
 * Minimizable to a small badge. Expandable to show full task list.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
  X,
  ExternalLink,
  FileUp,
  Layers,
} from 'lucide-react';
import { useUploadQueueStore } from '@/stores/useUploadQueueStore';

export function FloatingQueuePanel() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const tasks = useUploadQueueStore((s) => s.tasks);
  const removeTask = useUploadQueueStore((s) => s.removeTask);
  const clearCompleted = useUploadQueueStore((s) => s.clearCompleted);
  const [minimized, setMinimized] = useState(false);

  const activeTasks = tasks.filter((t) => t.status === 'processing' || t.status === 'queued');
  const completedTasks = tasks.filter((t) => t.status === 'completed');
  const errorTasks = tasks.filter((t) => t.status === 'error');

  // Don't render if no tasks at all
  if (tasks.length === 0) return null;

  // Minimized: just a small badge
  if (minimized) {
    return (
      <div className="fixed bottom-4 right-4 z-50">
        <button
          onClick={() => setMinimized(false)}
          className="flex items-center gap-2 px-3 py-2 rounded-full bg-surface-elevated border border-border-light shadow-lg hover:shadow-xl transition-all"
        >
          {activeTasks.length > 0 ? (
            <>
              <Loader2 size={14} className="text-oe-blue animate-spin" />
              <span className="text-xs font-medium text-content-primary">
                {activeTasks.length} {t('queue.processing', { defaultValue: 'processing' })}
              </span>
            </>
          ) : (
            <>
              <CheckCircle2 size={14} className="text-green-500" />
              <span className="text-xs font-medium text-content-primary">
                {completedTasks.length} {t('queue.done', { defaultValue: 'done' })}
              </span>
            </>
          )}
          <ChevronUp size={12} className="text-content-tertiary" />
        </button>
      </div>
    );
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 w-80 rounded-xl bg-surface-elevated border border-border-light shadow-xl overflow-hidden animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-surface-secondary/50 border-b border-border-light">
        <div className="flex items-center gap-2">
          {activeTasks.length > 0 ? (
            <Loader2 size={14} className="text-oe-blue animate-spin" />
          ) : (
            <CheckCircle2 size={14} className="text-green-500" />
          )}
          <span className="text-xs font-semibold text-content-primary">
            {activeTasks.length > 0
              ? t('queue.title_active', { defaultValue: 'Processing ({{count}})', count: activeTasks.length })
              : t('queue.title_done', { defaultValue: 'All tasks complete' })}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {completedTasks.length > 0 && activeTasks.length === 0 && (
            <button
              onClick={clearCompleted}
              className="text-2xs text-oe-blue hover:underline mr-1"
            >
              {t('queue.clear', { defaultValue: 'Clear' })}
            </button>
          )}
          <button
            onClick={() => setMinimized(true)}
            className="p-1 rounded hover:bg-surface-secondary text-content-tertiary"
            title={t('queue.minimize', { defaultValue: 'Minimize' })}
          >
            <ChevronDown size={14} />
          </button>
        </div>
      </div>

      {/* Task list */}
      <div className="max-h-60 overflow-y-auto">
        {tasks.map((task) => (
          <div
            key={task.id}
            className="flex items-start gap-3 px-4 py-3 border-b border-border-light last:border-0"
          >
            {/* Icon */}
            <div className="mt-0.5 shrink-0">
              {task.status === 'processing' && <Loader2 size={16} className="text-oe-blue animate-spin" />}
              {task.status === 'queued' && <FileUp size={16} className="text-content-tertiary" />}
              {task.status === 'completed' && <CheckCircle2 size={16} className="text-green-500" />}
              {task.status === 'error' && <XCircle size={16} className="text-semantic-error" />}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-content-primary truncate">{task.filename}</p>

              {/* Processing: progress bar */}
              {task.status === 'processing' && (
                <div className="mt-1.5">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1.5 bg-surface-secondary rounded-full overflow-hidden">
                      <div
                        className="h-full bg-oe-blue rounded-full transition-all duration-1000 ease-linear"
                        style={{ width: `${task.progress}%` }}
                      />
                    </div>
                    <span className="text-2xs text-oe-blue font-semibold tabular-nums w-8 text-right">
                      {Math.round(task.progress)}%
                    </span>
                  </div>
                  {task.message && (
                    <p className="text-2xs text-content-quaternary mt-0.5">{task.message}</p>
                  )}
                </div>
              )}

              {/* Completed: open link */}
              {task.status === 'completed' && (
                <div className="mt-1 flex items-center gap-2">
                  {task.resultUrl && (
                    <button
                      onClick={() => navigate(task.resultUrl!)}
                      className="inline-flex items-center gap-1 text-2xs text-oe-blue hover:underline font-medium"
                    >
                      <ExternalLink size={10} />
                      {t('queue.open_result', { defaultValue: 'Open in Explorer' })}
                    </button>
                  )}
                  <span className="text-2xs text-content-quaternary">
                    {task.message}
                  </span>
                </div>
              )}

              {/* Error */}
              {task.status === 'error' && (
                <p className="text-2xs text-semantic-error mt-0.5 truncate">{task.error || 'Failed'}</p>
              )}
            </div>

            {/* Remove button for completed/error */}
            {(task.status === 'completed' || task.status === 'error') && (
              <button
                onClick={() => removeTask(task.id)}
                className="shrink-0 p-0.5 rounded hover:bg-surface-secondary text-content-quaternary mt-0.5"
              >
                <X size={12} />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
