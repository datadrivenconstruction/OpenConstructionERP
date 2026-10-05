// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The state or province a project is in, beside its country.
//
// Some rules are set below the country. California caps the deposit a home
// improvement contract may ask for, Victoria a domestic-building one, and the
// payment-plan check can only apply such a rule when it knows where the work
// is. Left empty, the check says it could not run rather than guess, so the
// field is optional and says what it is for.
//
// The value is an ISO 3166-2 code (US-CA, AU-VIC), the same shape the server
// validates. It is checked here first so a typo is explained in words instead
// of coming back as a 422, and a code whose country part differs from the
// project's country is pointed out, since that is almost always a slip.
// Emptying the box sends null, which the project PATCH stores as "not set".

import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { MapPin, Save } from 'lucide-react';
import { Button, Card, CardHeader } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { projectsApi, type Project } from './api';

/** Same pattern the backend validates (`SUBDIVISION_CODE_RE`). */
const SUBDIVISION_RE = /^[A-Z]{2}-[A-Z0-9]{1,3}$/;

export function ProjectSubdivisionCard({ project }: { project: Project }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const saved = project.subdivision_code ?? '';
  const [draft, setDraft] = useState(saved);
  useEffect(() => setDraft(saved), [saved]);

  const code = draft.trim().toUpperCase();
  const invalid = code !== '' && !SUBDIVISION_RE.test(code);
  const country = (project.country_code ?? '').toUpperCase();
  const mismatch = !invalid && code !== '' && country !== '' && !code.startsWith(`${country}-`);

  const saveMut = useMutation({
    mutationFn: () => projectsApi.update(project.id, { subdivision_code: code || null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', project.id] });
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      addToast({
        type: 'success',
        title: t('project.settings.saved', { defaultValue: 'Project settings saved' }),
      });
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('project.settings.save_failed', { defaultValue: 'Failed to save settings' }),
        message: getErrorMessage(err),
      }),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (invalid || code === saved) return;
    saveMut.mutate();
  };

  return (
    <Card padding="lg">
      <CardHeader
        title={t('project.settings.location.title', { defaultValue: 'State or province' })}
        subtitle={t('project.settings.location.subtitle', {
          defaultValue:
            'Some rules depend on the state or province where the work is, for example how much a client may be asked to pay up front. Leave it empty if no such rule applies.',
        })}
      />
      <form onSubmit={submit} className="mt-4 flex flex-col gap-3 md:flex-row md:flex-wrap md:items-end">
        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-content-primary">
            {t('project.settings.location.country', { defaultValue: 'Country' })}
          </span>
          <span className="inline-flex h-9 items-center gap-1.5 text-sm text-content-secondary">
            <MapPin size={13} className="text-content-tertiary" />
            {country ||
              t('project.settings.location.country_none', {
                defaultValue: 'Not set, taken from the site address',
              })}
          </span>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor="project-subdivision" className="text-sm font-medium text-content-primary">
            {t('project.settings.location.subdivision', { defaultValue: 'State / province' })}
          </label>
          <input
            id="project-subdivision"
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={country ? `${country}-` : 'US-CA'}
            maxLength={6}
            autoComplete="off"
            aria-invalid={invalid || undefined}
            className="h-9 w-32 rounded-lg border border-border bg-surface-primary px-3 text-sm uppercase text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
          />
        </div>
        <Button
          variant="primary"
          size="sm"
          type="submit"
          icon={<Save size={14} />}
          loading={saveMut.isPending}
          disabled={invalid || code === saved}
        >
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
        <p className="text-xs text-content-tertiary md:basis-full md:max-w-md">
          {t('project.settings.location.helper', {
            defaultValue: 'Use the ISO code: the country, a hyphen and the state, such as US-CA or AU-VIC.',
          })}
        </p>
        {invalid && (
          <p role="alert" className="text-xs text-semantic-error md:basis-full">
            {t('project.settings.location.invalid', {
              defaultValue: 'This is not an ISO code. Write it like US-CA.',
            })}
          </p>
        )}
        {mismatch && (
          <p className="text-xs text-semantic-warning md:basis-full">
            {t('project.settings.location.country_mismatch', {
              code,
              country,
              defaultValue: '{{code}} is not in {{country}}, the country of this project.',
            })}
          </p>
        )}
      </form>
    </Card>
  );
}
