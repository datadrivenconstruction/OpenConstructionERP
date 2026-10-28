// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BulkRoomAddModal — pattern generator for creating many rooms at once.
 *
 * Two modes:
 *   • Generator — prefix + start + count + per-room capacity + base_rate +
 *     currency. Produces e.g. "B-201..B-212" with 1-room capacity each.
 *   • Paste — paste labels separated by newlines / commas.
 *
 * Money inputs stay as STRINGS end-to-end. We never parseFloat() rents.
 */

import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Loader2 } from 'lucide-react';

import { WideModal, WideModalSection, WideModalField } from '@/shared/ui/WideModal';
import { Button } from '@/shared/ui';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';

import {
  bulkCreateRooms,
  type RoomCreatePayload,
} from './api';
import { fmtList } from '@/shared/lib/formatters';

export interface BulkRoomAddModalProps {
  accommodationId: string;
  /** Capacity already represented by existing rooms — informs the helper text. */
  existingLabels?: string[];
  onClose: () => void;
  onCreated: (count: number) => void;
}

type Mode = 'generator' | 'paste';
const BULK_MODE_IDS: readonly Mode[] = ['generator', 'paste'];

export function BulkRoomAddModal({
  accommodationId,
  existingLabels = [],
  onClose,
  onCreated,
}: BulkRoomAddModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [mode, setMode] = useState<Mode>('generator');
  const onModeKeyDown = useTabKeyboardNav<Mode>({
    ids: BULK_MODE_IDS,
    activeId: mode,
    onChange: setMode,
    orientation: 'horizontal',
  });
  const [prefix, setPrefix] = useState('B-');
  const [start, setStart] = useState('201');
  const [count, setCount] = useState('12');
  const [capacity, setCapacity] = useState('1');
  /** Decimal as string — never parseFloat. */
  const [baseRate, setBaseRate] = useState('0');
  const [currency, setCurrency] = useState('');
  const [pasted, setPasted] = useState('');

  const labels = useMemo<string[]>(() => {
    if (mode === 'paste') {
      return pasted
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean);
    }
    const startNum = Number(start);
    const countNum = Number(count);
    if (!Number.isFinite(startNum) || !Number.isFinite(countNum)) return [];
    const out: string[] = [];
    const width = String(start).length;
    for (let i = 0; i < countNum; i += 1) {
      const n = startNum + i;
      // Preserve zero-padding when the original start was e.g. "001".
      const padded = String(n).padStart(width, '0');
      out.push(`${prefix}${padded}`);
    }
    return out;
  }, [mode, prefix, start, count, pasted]);

  // Cheap duplicate / existing check.
  const duplicates = useMemo(() => {
    const seen = new Set<string>();
    const dups = new Set<string>();
    const existing = new Set(existingLabels);
    for (const l of labels) {
      if (seen.has(l) || existing.has(l)) dups.add(l);
      seen.add(l);
    }
    return Array.from(dups);
  }, [labels, existingLabels]);

  const mutation = useMutation({
    mutationFn: async () => {
      const payload: RoomCreatePayload[] = labels.map((label) => {
        const room: RoomCreatePayload = {
          label,
          capacity: Math.max(1, Number(capacity) || 1),
          status: 'available',
        };
        // Money values stay as strings end-to-end.
        if (baseRate.trim()) room.base_rate = baseRate.trim();
        if (currency.trim()) room.base_rate_currency = currency.trim().toUpperCase();
        return room;
      });
      return bulkCreateRooms(accommodationId, payload);
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['accommodation'] });
      addToast({
        type: 'success',
        title: t('accommodation.bulk_add.created_toast', {
          defaultValue: 'Created {{count}} rooms',
          count: created.length,
        }),
      });
      onCreated(created.length);
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('accommodation.bulk_add.failed_toast', {
          defaultValue: 'Could not create rooms',
        }),
        message: getErrorMessage(err),
      });
    },
  });

  const canSubmit =
    labels.length > 0 && duplicates.length === 0 && !mutation.isPending;

  const inputCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('accommodation.bulk_add.title', { defaultValue: 'Add rooms' })}
      subtitle={t('accommodation.bulk_add.subtitle', {
        defaultValue:
          'Generate labels in a sequence or paste your own. Duplicate labels (existing or repeated) block submission.',
      })}
      size="lg"
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => mutation.mutate()}
            disabled={!canSubmit}
            loading={mutation.isPending}
            data-testid="accommodation-bulk-add-submit"
          >
            {t('accommodation.bulk_add.create_n', {
              defaultValue: 'Create {{count}} rooms',
              count: labels.length,
            })}
          </Button>
        </>
      }
    >
      {/* Mode tabs */}
      <div
        role="tablist"
        aria-label={t('accommodation.bulk_add.mode_aria', {
          defaultValue: 'Bulk add mode',
        })}
        onKeyDown={onModeKeyDown}
        className="mb-4 inline-flex rounded-lg border border-border p-0.5"
      >
        {BULK_MODE_IDS.map((m) => (
          <button
            key={m}
            role="tab"
            id={`bulk-room-add-tab-${m}`}
            aria-selected={mode === m}
            aria-controls={`bulk-room-add-panel-${m}`}
            tabIndex={mode === m ? 0 : -1}
            type="button"
            onClick={() => setMode(m)}
            className={clsx(
              'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              mode === m
                ? 'bg-oe-blue text-content-inverse shadow-sm'
                : 'text-content-secondary hover:text-content-primary',
            )}
          >
            {t(`accommodation.bulk_add.mode.${m}`, {
              defaultValue: m === 'generator' ? 'Generator' : 'Paste labels',
            })}
          </button>
        ))}
      </div>

      {mode === 'generator' ? (
        <WideModalSection columns={3}>
          <WideModalField
            label={t('accommodation.bulk_add.prefix', { defaultValue: 'Prefix' })}
          >
            <input
              type="text"
              value={prefix}
              onChange={(e) => setPrefix(e.target.value)}
              className={inputCls}
              data-testid="bulk-add-prefix"
            />
          </WideModalField>
          <WideModalField
            label={t('accommodation.bulk_add.start', { defaultValue: 'Start at' })}
          >
            <input
              type="text"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className={inputCls}
              data-testid="bulk-add-start"
            />
          </WideModalField>
          <WideModalField
            label={t('accommodation.bulk_add.count', { defaultValue: 'Count' })}
          >
            <input
              type="number"
              min={1}
              max={2000}
              value={count}
              onChange={(e) => setCount(e.target.value)}
              className={inputCls}
              data-testid="bulk-add-count"
            />
          </WideModalField>
        </WideModalSection>
      ) : (
        <WideModalSection columns={1}>
          <WideModalField
            label={t('accommodation.bulk_add.paste_labels', {
              defaultValue: 'Labels (one per line or comma-separated)',
            })}
            hint={t('accommodation.bulk_add.paste_hint', {
              defaultValue: 'e.g.  B-201, B-202, B-203',
            })}
          >
            <textarea
              rows={5}
              value={pasted}
              onChange={(e) => setPasted(e.target.value)}
              className="w-full rounded-lg border border-border bg-surface-primary p-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              data-testid="bulk-add-paste"
            />
          </WideModalField>
        </WideModalSection>
      )}

      <WideModalSection
        title={t('accommodation.bulk_add.shared_attrs', {
          defaultValue: 'Applied to every new room',
        })}
        columns={3}
      >
        <WideModalField
          label={t('accommodation.bulk_add.capacity', {
            defaultValue: 'Capacity each',
          })}
        >
          <input
            type="number"
            min={1}
            value={capacity}
            onChange={(e) => setCapacity(e.target.value)}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('accommodation.bulk_add.base_rate', {
            defaultValue: 'Base rate',
          })}
          hint={t('accommodation.bulk_add.decimal_hint', {
            defaultValue: 'Decimal (e.g. 199.99). Leave 0 to skip.',
          })}
        >
          <input
            type="text"
            inputMode="decimal"
            value={baseRate}
            onChange={(e) => setBaseRate(e.target.value)}
            className={inputCls}
            data-testid="bulk-add-base-rate"
          />
        </WideModalField>
        <WideModalField
          label={t('accommodation.bulk_add.currency', {
            defaultValue: 'Currency (ISO 4217)',
          })}
          hint={t('accommodation.bulk_add.currency_hint', {
            defaultValue: 'Empty → inherit from project.',
          })}
        >
          <input
            type="text"
            maxLength={3}
            value={currency}
            onChange={(e) =>
              setCurrency(e.target.value.toUpperCase().replace(/[^A-Z]/g, ''))
            }
            placeholder="USD"
            className={`${inputCls} font-mono uppercase`}
          />
        </WideModalField>
      </WideModalSection>

      {/* Preview */}
      <WideModalSection
        title={t('accommodation.bulk_add.preview', {
          defaultValue: 'Preview ({{count}})',
          count: labels.length,
        })}
        columns={1}
      >
        <div className="rounded-lg border border-border bg-surface-secondary p-3 max-h-32 overflow-y-auto text-xs font-mono">
          {labels.length === 0 ? (
            <span className="text-content-tertiary">
              {t('accommodation.bulk_add.preview_empty', {
                defaultValue: 'No labels to create yet.',
              })}
            </span>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {labels.map((l) => {
                const isDup = duplicates.includes(l);
                return (
                  <span
                    key={l}
                    className={clsx(
                      'rounded px-1.5 py-0.5',
                      isDup
                        ? 'bg-semantic-error/15 text-semantic-error'
                        : 'bg-surface-primary text-content-primary',
                    )}
                  >
                    {l}
                  </span>
                );
              })}
            </div>
          )}
        </div>
        {duplicates.length > 0 && (
          <p className="mt-2 text-xs text-semantic-error">
            {t('accommodation.bulk_add.duplicate_warning', {
              defaultValue:
                'Duplicate or existing labels block submission: {{labels}}',
              labels: fmtList(duplicates),
            })}
          </p>
        )}
      </WideModalSection>

      {mutation.isPending && (
        <div className="mt-2 flex items-center gap-2 text-xs text-content-tertiary">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t('common.loading', { defaultValue: 'Working…' })}
        </div>
      )}
    </WideModal>
  );
}
