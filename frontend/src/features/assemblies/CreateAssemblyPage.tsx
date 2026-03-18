import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Button, Input, Card } from '@/shared/ui';
import { assembliesApi, type CreateAssemblyData } from './api';

/* -- Constants ------------------------------------------------------------ */

const CATEGORIES = [
  { value: 'concrete', label: 'Concrete' },
  { value: 'masonry', label: 'Masonry' },
  { value: 'steel', label: 'Steel' },
  { value: 'mep', label: 'MEP' },
  { value: 'earthwork', label: 'Earthwork' },
  { value: 'general', label: 'General' },
];

const UNITS = [
  { value: 'm', label: 'm -- Meter' },
  { value: 'm2', label: 'm2 -- Square meter' },
  { value: 'm3', label: 'm3 -- Cubic meter' },
  { value: 'kg', label: 'kg -- Kilogram' },
  { value: 't', label: 't -- Tonne' },
  { value: 'pcs', label: 'pcs -- Piece' },
  { value: 'lsum', label: 'lsum -- Lump sum' },
  { value: 'h', label: 'h -- Hour' },
  { value: 'set', label: 'set -- Set' },
  { value: 'lm', label: 'lm -- Linear meter' },
];

const CURRENCIES = [
  { value: 'EUR', label: 'EUR' },
  { value: 'USD', label: 'USD' },
  { value: 'GBP', label: 'GBP' },
  { value: 'CHF', label: 'CHF' },
  { value: 'SEK', label: 'SEK' },
  { value: 'NOK', label: 'NOK' },
  { value: 'DKK', label: 'DKK' },
  { value: 'PLN', label: 'PLN' },
  { value: 'CZK', label: 'CZK' },
  { value: 'CAD', label: 'CAD' },
  { value: 'AUD', label: 'AUD' },
  { value: 'CNY', label: 'CNY' },
  { value: 'JPY', label: 'JPY' },
  { value: 'INR', label: 'INR' },
  { value: 'AED', label: 'AED' },
  { value: 'SAR', label: 'SAR' },
  { value: 'BRL', label: 'BRL' },
  { value: 'ZAR', label: 'ZAR' },
];

const STANDARDS = [
  { value: 'din276', label: 'DIN 276' },
  { value: 'nrm', label: 'NRM' },
  { value: 'masterformat', label: 'MasterFormat' },
  { value: 'uniformat', label: 'UniFormat' },
  { value: 'uniclass', label: 'Uniclass' },
];

/* -- Component ------------------------------------------------------------ */

export function CreateAssemblyPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [form, setForm] = useState({
    code: '',
    name: '',
    unit: 'm2',
    category: 'general',
    classificationStandard: '',
    classificationCode: '',
    currency: 'EUR',
    bid_factor: '1.00',
  });

  const mutation = useMutation({
    mutationFn: (data: CreateAssemblyData) => assembliesApi.create(data),
    onSuccess: (assembly) => {
      queryClient.invalidateQueries({ queryKey: ['assemblies'] });
      navigate(`/assemblies/${assembly.id}`);
    },
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!form.code.trim() || !form.name.trim()) return;

    const classification: Record<string, string> = {};
    if (form.classificationStandard && form.classificationCode) {
      classification[form.classificationStandard] = form.classificationCode;
    }

    mutation.mutate({
      code: form.code,
      name: form.name,
      unit: form.unit,
      category: form.category,
      classification: Object.keys(classification).length > 0 ? classification : undefined,
      currency: form.currency,
      bid_factor: parseFloat(form.bid_factor) || 1.0,
    });
  };

  const set = (field: string, value: string) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const selectClass =
    'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary transition-all duration-fast ease-oe focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent hover:border-content-tertiary cursor-pointer appearance-none';

  return (
    <div className="max-w-2xl mx-auto animate-fade-in">
      <button
        onClick={() => navigate('/assemblies')}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
      >
        <ArrowLeft size={14} />
        {t('assemblies.title', 'Assemblies')}
      </button>

      <h1 className="text-2xl font-bold text-content-primary mb-6">
        {t('assemblies.new_assembly', 'New Assembly')}
      </h1>

      <Card>
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Code & Name */}
          <div className="grid grid-cols-3 gap-4">
            <Input
              label="Code"
              value={form.code}
              onChange={(e) => set('code', e.target.value)}
              placeholder="e.g. ASM-001"
              required
              autoFocus
            />
            <div className="col-span-2">
              <Input
                label="Name"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder="e.g. Reinforced Concrete Wall C30/37"
                required
              />
            </div>
          </div>

          {/* Unit & Category */}
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-content-primary">Unit</label>
              <select
                value={form.unit}
                onChange={(e) => set('unit', e.target.value)}
                className={selectClass}
              >
                {UNITS.map((u) => (
                  <option key={u.value} value={u.value}>
                    {u.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-content-primary">Category</label>
              <select
                value={form.category}
                onChange={(e) => set('category', e.target.value)}
                className={selectClass}
              >
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Classification */}
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-content-primary">
                Classification Standard
              </label>
              <select
                value={form.classificationStandard}
                onChange={(e) => set('classificationStandard', e.target.value)}
                className={selectClass}
              >
                <option value="">-- None --</option>
                {STANDARDS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <Input
              label="Classification Code"
              value={form.classificationCode}
              onChange={(e) => set('classificationCode', e.target.value)}
              placeholder="e.g. 330"
              disabled={!form.classificationStandard}
            />
          </div>

          {/* Currency & Bid Factor */}
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-content-primary">Currency</label>
              <select
                value={form.currency}
                onChange={(e) => set('currency', e.target.value)}
                className={selectClass}
              >
                {CURRENCIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
            <Input
              label="Bid Factor"
              type="number"
              value={form.bid_factor}
              onChange={(e) => set('bid_factor', e.target.value)}
              placeholder="1.00"
              hint="Multiplier applied to the total rate (1.00 = no markup)"
            />
          </div>

          {/* Error */}
          {mutation.error && (
            <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
              {(mutation.error as Error).message || 'Failed to create assembly'}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="secondary" type="button" onClick={() => navigate('/assemblies')}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button variant="primary" type="submit" loading={mutation.isPending}>
              {t('common.create', 'Create')}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
