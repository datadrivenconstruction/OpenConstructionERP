import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Button, Input, Card } from '@/shared/ui';
import { projectsApi, type CreateProjectData } from './api';

const REGIONS = [
  { value: 'DACH', label: 'DACH (Germany, Austria, Switzerland)' },
  { value: 'UK', label: 'United Kingdom' },
  { value: 'US', label: 'United States' },
  { value: 'INTL', label: 'International' },
];

const STANDARDS = [
  { value: 'din276', label: 'DIN 276 (DACH)' },
  { value: 'nrm', label: 'NRM (UK)' },
  { value: 'masterformat', label: 'MasterFormat (US)' },
];

const CURRENCIES = [
  { value: 'EUR', label: 'EUR (€)' },
  { value: 'GBP', label: 'GBP (£)' },
  { value: 'USD', label: 'USD ($)' },
  { value: 'CHF', label: 'CHF (Fr.)' },
];

export function CreateProjectPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [form, setForm] = useState<CreateProjectData>({
    name: '',
    description: '',
    region: 'DACH',
    classification_standard: 'din276',
    currency: 'EUR',
    locale: 'de',
  });

  const mutation = useMutation({
    mutationFn: projectsApi.create,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      navigate(`/projects/${project.id}`);
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    mutation.mutate(form);
  };

  const set = (field: keyof CreateProjectData, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  return (
    <div className="max-w-2xl mx-auto animate-fade-in">
      <button
        onClick={() => navigate('/projects')}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
      >
        <ArrowLeft size={14} />
        {t('projects.title')}
      </button>

      <h1 className="text-2xl font-bold text-content-primary mb-6">
        {t('projects.new_project')}
      </h1>

      <Card>
        <form onSubmit={handleSubmit} className="space-y-5">
          <Input
            label={t('projects.project_name')}
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            placeholder="e.g. Residential Complex Berlin-Mitte"
            required
            autoFocus
          />

          <div>
            <label className="text-sm font-medium text-content-primary block mb-1.5">
              Description
            </label>
            <textarea
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              placeholder="Project description, scope, notes..."
              rows={3}
              className="w-full rounded-lg border border-border px-3 py-2.5 text-sm text-content-primary placeholder:text-content-tertiary bg-surface-primary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent transition-all duration-fast ease-oe hover:border-content-tertiary resize-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <SelectField
              label="Region"
              value={form.region ?? 'DACH'}
              options={REGIONS}
              onChange={(v) => set('region', v)}
            />
            <SelectField
              label="Classification Standard"
              value={form.classification_standard ?? 'din276'}
              options={STANDARDS}
              onChange={(v) => set('classification_standard', v)}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <SelectField
              label="Currency"
              value={form.currency ?? 'EUR'}
              options={CURRENCIES}
              onChange={(v) => set('currency', v)}
            />
            <SelectField
              label="Language"
              value={form.locale ?? 'de'}
              options={[
                { value: 'de', label: 'Deutsch' },
                { value: 'en', label: 'English' },
                { value: 'ru', label: 'Русский' },
                { value: 'fr', label: 'Français' },
              ]}
              onChange={(v) => set('locale', v)}
            />
          </div>

          {mutation.error && (
            <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
              {(mutation.error as Error).message || 'Failed to create project'}
            </div>
          )}

          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="secondary" type="button" onClick={() => navigate('/projects')}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" type="submit" loading={mutation.isPending}>
              {t('common.create')}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-sm font-medium text-content-primary">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary cursor-pointer appearance-none"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
