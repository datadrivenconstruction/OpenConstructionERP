// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * HrAutobookModal — pick an employee Contact, request a room suggestion
 * from the backend, then (on confirm) POST the actual booking.
 *
 * The backend `/bookings/suggest-from-hr` endpoint returns the lowest-
 * labelled available worker_camp room across the user's accessible
 * projects. We surface that suggestion and let the operator confirm; if
 * they do, we follow up with `POST /rooms/{id}/bookings` carrying the
 * `source='hr_autobook'` flag for downstream attribution.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, BedDouble, CheckCircle2, AlertTriangle } from 'lucide-react';

import { WideModal, WideModalSection, WideModalField } from '@/shared/ui/WideModal';
import { Button } from '@/shared/ui';
import { ContactSearchInput } from '@/shared/ui/ContactSearchInput';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';

import {
  suggestFromHR,
  createBooking,
  type SuggestFromHRResponse,
} from './api';

export interface HrAutobookModalProps {
  onClose: () => void;
}

/**
 * Parse-free positivity check for a Decimal-as-string money value. We
 * deliberately avoid `Number()` / `parseFloat()` on money (precision and
 * very-large-value safety): a value is "positive" iff it contains at
 * least one non-zero digit. Strips sign, separators and zeros, then
 * checks for any remaining 1-9 digit. Returns false for empty / nullish.
 */
function isPositiveDecimalString(value: string | null | undefined): boolean {
  if (!value) return false;
  return /[1-9]/.test(value);
}

export function HrAutobookModal({ onClose }: HrAutobookModalProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [contactId, setContactId] = useState('');
  const [contactName, setContactName] = useState('');
  const [startDate, setStartDate] = useState(
    () => new Date().toISOString().slice(0, 10),
  );
  const [suggestion, setSuggestion] = useState<SuggestFromHRResponse | null>(
    null,
  );
  const [confirmed, setConfirmed] = useState(false);

  const suggestMutation = useMutation({
    mutationFn: suggestFromHR,
    onSuccess: (data) => {
      setSuggestion(data);
    },
    onError: (err) => {
      const msg = getErrorMessage(err);
      addToast({
        type: 'warning',
        title: t('accommodation.hr_autobook.no_rooms', {
          defaultValue: 'No available room',
        }),
        message: msg,
      });
    },
  });

  const confirmMutation = useMutation({
    mutationFn: async (s: SuggestFromHRResponse) =>
      createBooking(s.room_id, {
        occupant_contact_id: contactId,
        occupant_name: contactName || null,
        check_in: startDate,
        status: 'reserved',
        source: 'hr_autobook',
      }),
    onSuccess: () => {
      setConfirmed(true);
      queryClient.invalidateQueries({ queryKey: ['accommodation'] });
      addToast({
        type: 'success',
        title: t('accommodation.hr_autobook.confirmed', {
          defaultValue: 'Booking created',
        }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('accommodation.hr_autobook.confirm_failed', {
          defaultValue: 'Could not create booking',
        }),
        message: getErrorMessage(err),
      });
    },
  });

  const handleSuggest = () => {
    if (!contactId) {
      addToast({
        type: 'warning',
        title: t('accommodation.hr_autobook.pick_contact_first', {
          defaultValue: 'Pick an employee contact first.',
        }),
      });
      return;
    }
    setSuggestion(null);
    setConfirmed(false);
    suggestMutation.mutate({
      employee_contact_id: contactId,
      start_date: startDate,
    });
  };

  const inputCls =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('accommodation.hr_autobook.title', {
        defaultValue: 'Suggest room for employee',
      })}
      subtitle={t('accommodation.hr_autobook.subtitle', {
        defaultValue:
          'Picks the lowest-labelled available worker-camp room across projects you can see. You always confirm before a booking is created.',
      })}
      size="md"
      busy={suggestMutation.isPending || confirmMutation.isPending}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          {suggestion && !confirmed && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => confirmMutation.mutate(suggestion)}
              loading={confirmMutation.isPending}
              data-testid="hr-autobook-confirm"
            >
              {t('accommodation.hr_autobook.confirm', {
                defaultValue: 'Confirm booking',
              })}
            </Button>
          )}
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('accommodation.hr_autobook.employee', {
            defaultValue: 'Employee contact',
          })}
          required
          span={2}
        >
          <ContactSearchInput
            value={contactId}
            displayValue={contactName}
            onChange={(id, name) => {
              setContactId(id);
              setContactName(name);
              setSuggestion(null);
              setConfirmed(false);
            }}
          />
        </WideModalField>
        <WideModalField
          label={t('accommodation.hr_autobook.start_date', {
            defaultValue: 'Start date',
          })}
          required
        >
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className={inputCls}
            data-testid="hr-autobook-start-date"
          />
        </WideModalField>
        <WideModalField label="">
          <Button
            variant="secondary"
            size="md"
            onClick={handleSuggest}
            loading={suggestMutation.isPending}
            disabled={!contactId}
            data-testid="hr-autobook-suggest"
          >
            <BedDouble size={14} className="mr-1.5" />
            {t('accommodation.hr_autobook.suggest_button', {
              defaultValue: 'Suggest room',
            })}
          </Button>
        </WideModalField>
      </WideModalSection>

      {/* Suggestion card */}
      {suggestion && !confirmed && (
        <div
          role="region"
          aria-live="polite"
          data-testid="hr-autobook-suggestion"
          className="mt-4 rounded-xl border border-oe-blue/30 bg-oe-blue/5 p-4"
        >
          <div className="flex items-start gap-3">
            <CheckCircle2 className="h-5 w-5 text-oe-blue mt-0.5" />
            <div className="min-w-0">
              <div className="text-sm font-semibold text-content-primary">
                {t('accommodation.hr_autobook.suggestion_title', {
                  defaultValue: 'Suggested room',
                })}
              </div>
              <div className="mt-1 text-sm text-content-secondary">
                <span className="font-medium text-content-primary">
                  {suggestion.room_label}
                </span>{' '}
                · {suggestion.accommodation_name} ·{' '}
                {t(`accommodation.kind.${suggestion.accommodation_kind}`, {
                  defaultValue: suggestion.accommodation_kind,
                })}
              </div>
              <div className="mt-1 text-xs text-content-tertiary">
                {t('accommodation.hr_autobook.capacity', {
                  defaultValue: 'Capacity {{count}}',
                  count: suggestion.capacity,
                })}
                {suggestion.base_rate_currency &&
                  isPositiveDecimalString(suggestion.base_rate) && (
                    <>
                      {' · '}
                      {suggestion.base_rate} {suggestion.base_rate_currency}
                    </>
                  )}
              </div>
            </div>
          </div>
        </div>
      )}

      {confirmed && (
        <div className="mt-4 rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800">
          <CheckCircle2 className="mr-2 inline h-4 w-4" />
          {t('accommodation.hr_autobook.success_message', {
            defaultValue:
              'Booking created. Find it on the accommodation page under the Bookings tab.',
          })}
        </div>
      )}

      {suggestMutation.isError && !suggestion && (
        <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
          <AlertTriangle className="mr-2 inline h-4 w-4" />
          {t('accommodation.hr_autobook.no_rooms', {
            defaultValue: 'No available room across your worker camps.',
          })}
        </div>
      )}

      {(suggestMutation.isPending || confirmMutation.isPending) && (
        <div className="mt-2 flex items-center gap-2 text-xs text-content-tertiary">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t('common.loading', { defaultValue: 'Working…' })}
        </div>
      )}
    </WideModal>
  );
}
