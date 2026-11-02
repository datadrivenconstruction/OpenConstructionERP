/**
 * Imports a country's public holidays for one year into a named work calendar,
 * from the same regional tables the schedule already counts working days on.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Download } from 'lucide-react';
import { Button, Input } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import type { WorkCalendarResponse } from './api';

interface HolidayList {
  country: string;
  dates: string[];
}

export function HolidayImport({
  projectId,
  existing,
  onImport,
  disabled,
}: {
  projectId: string;
  existing: string[];
  onImport: (dates: string[]) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const [country, setCountry] = useState('');
  const [year, setYear] = useState(String(new Date().getFullYear()));

  const regional = useQuery({
    queryKey: ['work-calendar', projectId],
    queryFn: () =>
      apiGet<WorkCalendarResponse>(`/v1/schedule/work-calendar/?project_id=${encodeURIComponent(projectId)}`),
  });
  const projectCountry = regional.data?.holiday_country ?? '';
  useEffect(() => {
    if (projectCountry) setCountry((c) => c || projectCountry);
  }, [projectCountry]);

  const importMutation = useMutation({
    mutationFn: () =>
      apiGet<HolidayList>(
        `/v1/schedule/holidays/?country=${encodeURIComponent(country.trim().toUpperCase())}&years=${encodeURIComponent(year)}`,
      ),
    onSuccess: (list) => onImport([...new Set([...existing, ...list.dates])].sort()),
  });

  const yearOk = /^\d{4}$/.test(year);
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <Input
        value={country}
        maxLength={10}
        disabled={disabled}
        aria-label={t('schedule.calendar.import_country', { defaultValue: 'Country code' })}
        placeholder={t('schedule.calendar.import_country', { defaultValue: 'Country code' })}
        data-testid="holiday-import-country"
        onChange={(e) => setCountry(e.target.value)}
        className="w-28"
      />
      <Input
        type="number"
        min={1900}
        max={2200}
        value={year}
        disabled={disabled}
        aria-label={t('schedule.calendar.import_year', { defaultValue: 'Year' })}
        data-testid="holiday-import-year"
        onChange={(e) => setYear(e.target.value)}
        className="w-24"
      />
      <Button
        variant="secondary"
        size="sm"
        icon={<Download size={14} />}
        data-testid="holiday-import-button"
        disabled={disabled || !country.trim() || !yearOk}
        loading={importMutation.isPending}
        onClick={() => importMutation.mutate()}
      >
        {t('schedule.calendar.import_holidays', { defaultValue: 'Import public holidays' })}
      </Button>
      {importMutation.isError && (
        <p className="w-full text-xs text-semantic-error" role="alert">
          {t('schedule.calendar.import_failed', {
            defaultValue: 'No public holiday table covers this country. Add the dates by hand.',
          })}
        </p>
      )}
    </div>
  );
}
