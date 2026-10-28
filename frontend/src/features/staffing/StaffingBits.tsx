// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces the staffing screens share: the colour of each state, the
// cleared-to-work badge, a write that reports the server's refusal, a dialog
// that asks for a written reason, and the export buttons.

import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { Download } from 'lucide-react';

import { Badge, type BadgeVariant } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { WideModal } from '@/shared/ui/WideModal';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

import type {
  CellState,
  ExportFormat,
  FileStatus,
  FillStatus,
  LeaveStatus,
  PlanStatus,
  PositionStatus,
  TravelStatus,
} from './api';
import { refusalText, type TFn } from './labels';

export const FIELD_CLASS =
  'w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none disabled:opacity-60';

export const PLAN_TONE: Record<PlanStatus, BadgeVariant> = {
  draft: 'neutral',
  in_review: 'purple',
  approved: 'success',
  binding: 'success',
  revising: 'warning',
};

export const POSITION_TONE: Record<PositionStatus, BadgeVariant> = {
  open: 'warning',
  recruiting: 'blue',
  filled: 'success',
  on_hold: 'neutral',
  cancelled: 'neutral',
};

export const FILL_TONE: Record<FillStatus, BadgeVariant> = {
  proposed: 'blue',
  confirmed: 'success',
  ended: 'neutral',
};

export const FILE_TONE: Record<FileStatus, BadgeVariant> = {
  active: 'success',
  ended: 'neutral',
  retention_hold: 'warning',
  anonymised: 'neutral',
};

export const TRAVEL_TONE: Record<TravelStatus, BadgeVariant> = {
  planned: 'blue',
  booked: 'purple',
  done: 'success',
  cancelled: 'neutral',
};

export const LEAVE_TONE: Record<LeaveStatus, BadgeVariant> = {
  requested: 'blue',
  approved: 'success',
  taken: 'neutral',
  cancelled: 'neutral',
};

export const CELL_TONE: Record<CellState, BadgeVariant> = {
  valid: 'success',
  expiring: 'warning',
  expired: 'error',
  missing: 'error',
  waived: 'purple',
  not_required: 'neutral',
};

export function ToneBadge({ tone, children, testId }: { tone: BadgeVariant; children: ReactNode; testId?: string }) {
  return (
    <span data-testid={testId}>
      <Badge variant={tone} size="sm">
        {children}
      </Badge>
    </span>
  );
}

/** A person's name, or a neutral phrase when the roster line behind the record is gone. Never blank. */
export function personLabel(t: TFn, name: string | null | undefined): string {
  if (name && name.trim()) return name.trim();
  return t('staffing.person_unknown', { defaultValue: 'Former team member' });
}

/**
 * Whether the person may start work. Three answers, not two: without a
 * personnel file nothing is known, and that must not read as "not cleared".
 */
export function ClearedBadge({ cleared }: { cleared: boolean | null | undefined }) {
  const { t } = useTranslation();
  if (cleared === true) {
    return <ToneBadge tone="success" testId="cleared-yes">{t('staffing.fill.cleared', { defaultValue: 'Cleared to work' })}</ToneBadge>;
  }
  if (cleared === false) {
    return <ToneBadge tone="error" testId="cleared-no">{t('staffing.fill.not_cleared', { defaultValue: 'Not cleared' })}</ToneBadge>;
  }
  return <ToneBadge tone="neutral" testId="cleared-unknown">{t('staffing.fill.no_file', { defaultValue: 'No personnel file' })}</ToneBadge>;
}

/**
 * A write whose refusal the reader sees in the server's own words.
 *
 * The client does not predict permissions: the button is there, and when the
 * server says no, its reason is shown.
 */
export function useStaffingAction<TArgs = void, TResult = unknown>(
  fn: (args: TArgs) => Promise<TResult>,
  onDone?: (result: TResult, args: TArgs) => void,
) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  return useMutation({
    mutationFn: fn,
    onSuccess: (result, args) => onDone?.(result, args),
    onError: (err) => addToast({ type: 'error', title: refusalText(t as TFn, err) }),
  });
}

export interface ReasonDialogProps {
  open: boolean;
  title: string;
  subtitle?: string;
  /** Label of the text field; the reason is always required. */
  label: string;
  confirmLabel: string;
  danger?: boolean;
  onClose: () => void;
  /** Resolves when the server accepted the reason; a rejection stays in the dialog as its error. */
  onSubmit: (reason: string) => Promise<unknown>;
}

/** Asks for a written reason and will not send an empty one. Used for holds, erasures and waivers. */
export function ReasonDialog({ open, title, subtitle, label, confirmLabel, danger, onClose, onSubmit }: ReasonDialogProps) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setText('');
      setTried(false);
      setError(null);
    }
  }, [open]);

  const send = async () => {
    if (!text.trim()) {
      setTried(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit(text.trim());
      onClose();
    } catch (err) {
      setError(refusalText(t as TFn, err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={busy}
      size="sm"
      testId="staffing-reason-dialog"
      title={title}
      subtitle={subtitle}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} loading={busy} onClick={send} data-testid="reason-send">
            {confirmLabel}
          </Button>
        </div>
      }
    >
      <div className="space-y-2">
        <textarea
          rows={3}
          data-testid="reason-text"
          aria-label={label}
          placeholder={label}
          className={FIELD_CLASS}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        {tried && !text.trim() && (
          <p className="text-xs text-semantic-error" role="alert" data-testid="reason-required">
            {t('staffing.reason_required', { defaultValue: 'Write down the reason.' })}
          </p>
        )}
        {error && (
          <p className="text-xs text-semantic-error" role="alert" data-testid="reason-error">
            {error}
          </p>
        )}
      </div>
    </WideModal>
  );
}

/** PDF and Excel buttons for one export. A refused or failed download shows the server's message. */
export function ExportButtons({ download }: { download: (format: ExportFormat) => Promise<void> }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const run = async (format: ExportFormat) => {
    setBusy(format);
    try {
      await download(format);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(null);
    }
  };
  return (
    <span className="inline-flex gap-1">
      <Button variant="ghost" size="sm" icon={<Download size={14} />} loading={busy === 'pdf'} onClick={() => run('pdf')}>
        {t('staffing.export.pdf', { defaultValue: 'Export PDF' })}
      </Button>
      <Button variant="ghost" size="sm" icon={<Download size={14} />} loading={busy === 'xlsx'} onClick={() => run('xlsx')}>
        {t('staffing.export.xlsx', { defaultValue: 'Export Excel' })}
      </Button>
    </span>
  );
}

/** What a person picker says when it has nobody to offer: the team could not be loaded, or nobody is left. */
/** The server's reason beside a control it refuses; nothing when the action is allowed. */
export function Refusal({ text, testId }: { text: string; testId: string }) {
  if (!text) return null;
  return (
    <span className="text-xs text-content-tertiary" role="status" data-testid={testId}>
      {text}
    </span>
  );
}

export function PeoplePickerNote({ failed, empty, onRetry }: { failed: boolean; empty: boolean; onRetry: () => void }) {
  const { t } = useTranslation();
  if (failed) {
    return (
      <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-semantic-error" role="alert" data-testid="people-failed">
        {t('staffing.people_failed', { defaultValue: 'The project team could not be loaded.' })}
        <button type="button" className="underline" onClick={onRetry}>
          {t('common.retry', { defaultValue: 'Retry' })}
        </button>
      </p>
    );
  }
  if (!empty) return null;
  return (
    <p className="mt-1 text-xs text-content-tertiary" data-testid="people-none">
      {t('staffing.people_none', { defaultValue: 'There is nobody to choose. People come from the project team.' })}
    </p>
  );
}

/** A form's refusal line, shown inside the dialog that caused it. */
export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p className="mr-auto text-xs text-semantic-error" role="alert" data-testid="form-error">
      {message}
    </p>
  );
}
