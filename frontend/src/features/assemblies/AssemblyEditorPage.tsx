import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, Trash2, Send, X } from 'lucide-react';
import { Button, Badge, Card, Input } from '@/shared/ui';
import {
  assembliesApi,
  type AssemblyComponent,
  type CreateComponentData,
} from './api';

/* -- Constants ------------------------------------------------------------ */

const UNITS = ['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'];

/* -- Component ------------------------------------------------------------ */

export function AssemblyEditorPage() {
  const { t } = useTranslation();
  const { assemblyId } = useParams<{ assemblyId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [applyModalOpen, setApplyModalOpen] = useState(false);

  const { data: assembly, isLoading } = useQuery({
    queryKey: ['assembly', assemblyId],
    queryFn: () => assembliesApi.get(assemblyId!),
    enabled: !!assemblyId,
  });

  const addComponentMutation = useMutation({
    mutationFn: (data: CreateComponentData) =>
      assembliesApi.addComponent(assemblyId!, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] }),
  });

  const updateComponentMutation = useMutation({
    mutationFn: ({ componentId, data }: { componentId: string; data: Partial<CreateComponentData> }) =>
      assembliesApi.updateComponent(assemblyId!, componentId, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] }),
  });

  const deleteComponentMutation = useMutation({
    mutationFn: (componentId: string) =>
      assembliesApi.deleteComponent(assemblyId!, componentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['assembly', assemblyId] }),
  });

  const handleAddComponent = useCallback(() => {
    addComponentMutation.mutate({
      description: '',
      factor: 1,
      quantity: 0,
      unit: 'm2',
      unit_cost: 0,
    });
  }, [addComponentMutation]);

  const fmt = (n: number) =>
    new Intl.NumberFormat('de-DE', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(n);

  if (isLoading) {
    return (
      <div className="max-w-content mx-auto py-8 text-center text-content-secondary animate-fade-in">
        Loading assembly...
      </div>
    );
  }

  if (!assembly) {
    return (
      <div className="max-w-content mx-auto py-16 text-center">
        <p className="text-content-secondary">Assembly not found</p>
      </div>
    );
  }

  const components = assembly.components ?? [];
  const computedTotal = components.reduce((sum, c) => sum + c.total, 0);
  const adjustedTotal = computedTotal * assembly.bid_factor;

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Back link */}
      <button
        onClick={() => navigate('/assemblies')}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
      >
        <ArrowLeft size={14} />
        {t('assemblies.title', 'Assemblies')}
      </button>

      {/* Header */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-content-primary truncate">
              {assembly.name}
            </h1>
            <Badge variant="blue" size="md">
              {assembly.code}
            </Badge>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-content-secondary">
            {assembly.category && (
              <span className="capitalize">{assembly.category}</span>
            )}
            <span className="text-content-tertiary">/</span>
            <span>{assembly.unit}</span>
            <span className="text-content-tertiary">/</span>
            <span>{assembly.currency || 'EUR'}</span>
            {assembly.bid_factor !== 1.0 && (
              <>
                <span className="text-content-tertiary">/</span>
                <span>
                  Bid Factor:{' '}
                  <strong className="text-content-primary">{assembly.bid_factor}</strong>
                </span>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="secondary"
            size="sm"
            icon={<Send size={15} />}
            onClick={() => setApplyModalOpen(true)}
          >
            Apply to BOQ
          </Button>
          <Button
            variant="primary"
            icon={<Plus size={16} />}
            onClick={handleAddComponent}
          >
            Add Component
          </Button>
        </div>
      </div>

      {/* Components Table */}
      <Card padding="none" className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-tertiary text-left">
                <th className="px-4 py-3 font-medium text-content-secondary min-w-[280px]">
                  Description
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-24 text-right">
                  Factor
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-24 text-right">
                  Qty
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-20 text-center">
                  Unit
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-28 text-right">
                  Unit Cost
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-32 text-right">
                  Total
                </th>
                <th className="px-4 py-3 w-10" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {components.map((component) => (
                <ComponentRow
                  key={component.id}
                  component={component}
                  onUpdate={(data) =>
                    updateComponentMutation.mutate({
                      componentId: component.id,
                      data,
                    })
                  }
                  onDelete={() => deleteComponentMutation.mutate(component.id)}
                  fmt={fmt}
                />
              ))}
              {components.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-content-tertiary">
                    No components yet. Click "Add Component" to start building this assembly.
                  </td>
                </tr>
              )}
            </tbody>
            {components.length > 0 && (
              <tfoot>
                {assembly.bid_factor !== 1.0 && (
                  <tr className="border-t border-border-light bg-surface-tertiary/50">
                    <td colSpan={5} className="px-4 py-2.5 text-right text-sm text-content-secondary">
                      Subtotal
                    </td>
                    <td className="px-4 py-2.5 text-right text-sm text-content-secondary tabular-nums">
                      {fmt(computedTotal)}
                    </td>
                    <td />
                  </tr>
                )}
                {assembly.bid_factor !== 1.0 && (
                  <tr className="border-t border-border-light bg-surface-tertiary/50">
                    <td colSpan={5} className="px-4 py-2.5 text-right text-sm text-content-secondary">
                      Bid Factor ({assembly.bid_factor})
                    </td>
                    <td className="px-4 py-2.5 text-right text-sm text-content-secondary tabular-nums">
                      x {assembly.bid_factor}
                    </td>
                    <td />
                  </tr>
                )}
                <tr className="border-t-2 border-border bg-surface-tertiary font-semibold">
                  <td colSpan={5} className="px-4 py-3 text-right text-content-primary">
                    Total Rate
                  </td>
                  <td className="px-4 py-3 text-right text-content-primary text-base tabular-nums">
                    {fmt(adjustedTotal)}
                    <span className="ml-1 text-xs font-normal text-content-tertiary">
                      / {assembly.unit}
                    </span>
                  </td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </Card>

      {/* Apply to BOQ Modal */}
      {applyModalOpen && (
        <ApplyToBOQModal
          assemblyId={assemblyId!}
          assemblyName={assembly.name}
          onClose={() => setApplyModalOpen(false)}
        />
      )}
    </div>
  );
}

/* -- Component Row (inline editable) -------------------------------------- */

function ComponentRow({
  component,
  onUpdate,
  onDelete,
  fmt,
}: {
  component: AssemblyComponent;
  onUpdate: (data: Partial<CreateComponentData>) => void;
  onDelete: () => void;
  fmt: (n: number) => string;
}) {
  const [editing, setEditing] = useState<string | null>(null);

  const handleBlur = (field: string, value: string) => {
    setEditing(null);
    const numFields = ['factor', 'quantity', 'unit_cost'];
    const update: Partial<CreateComponentData> = {
      [field]: numFields.includes(field) ? parseFloat(value) || 0 : value,
    };
    onUpdate(update);
  };

  const cellClass =
    'px-4 py-2.5 transition-colors cursor-text hover:bg-oe-blue-subtle/50';
  const inputClass =
    'w-full bg-transparent border-none outline-none focus:ring-0 p-0 text-sm';

  return (
    <tr className="group hover:bg-surface-secondary/50 transition-colors">
      {/* Description */}
      <td className={cellClass}>
        <EditableCell
          value={component.description}
          field="description"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={inputClass}
          placeholder="Enter description..."
        />
      </td>

      {/* Factor */}
      <td className={`${cellClass} text-right`}>
        <EditableCell
          value={String(component.factor)}
          field="factor"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={`${inputClass} text-right`}
          type="number"
        />
      </td>

      {/* Quantity */}
      <td className={`${cellClass} text-right`}>
        <EditableCell
          value={String(component.quantity)}
          field="quantity"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={`${inputClass} text-right`}
          type="number"
        />
      </td>

      {/* Unit */}
      <td className="px-4 py-2.5 text-center">
        <select
          value={component.unit}
          onChange={(e) => onUpdate({ unit: e.target.value })}
          className="bg-transparent text-sm text-center cursor-pointer border-none outline-none text-content-secondary hover:text-content-primary"
        >
          {UNITS.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </select>
      </td>

      {/* Unit Cost */}
      <td className={`${cellClass} text-right`}>
        <EditableCell
          value={String(component.unit_cost)}
          field="unit_cost"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={`${inputClass} text-right`}
          type="number"
        />
      </td>

      {/* Total (computed) */}
      <td className="px-4 py-2.5 text-right font-semibold text-content-primary tabular-nums">
        {fmt(component.total)}
      </td>

      {/* Delete */}
      <td className="px-2 py-2.5">
        <button
          onClick={onDelete}
          className="opacity-0 group-hover:opacity-100 flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg transition-all"
        >
          <Trash2 size={14} />
        </button>
      </td>
    </tr>
  );
}

/* -- Editable Cell -------------------------------------------------------- */

function EditableCell({
  value,
  field,
  editing,
  setEditing,
  onBlur,
  className,
  placeholder,
  type = 'text',
}: {
  value: string;
  field: string;
  editing: string | null;
  setEditing: (f: string | null) => void;
  onBlur: (field: string, value: string) => void;
  className?: string;
  placeholder?: string;
  type?: string;
}) {
  if (editing === field) {
    return (
      <input
        type={type}
        defaultValue={value}
        autoFocus
        className={className}
        placeholder={placeholder}
        onBlur={(e) => onBlur(field, e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
          if (e.key === 'Escape') setEditing(null);
        }}
      />
    );
  }

  return (
    <span
      onClick={() => setEditing(field)}
      className={`block min-h-[20px] ${!value && placeholder ? 'text-content-tertiary' : ''}`}
    >
      {value || placeholder || ''}
    </span>
  );
}

/* -- Apply to BOQ Modal --------------------------------------------------- */

function ApplyToBOQModal({
  assemblyId,
  assemblyName,
  onClose,
}: {
  assemblyId: string;
  assemblyName: string;
  onClose: () => void;
}) {
  const [boqId, setBoqId] = useState('');
  const [quantity, setQuantity] = useState('1');

  const applyMutation = useMutation({
    mutationFn: () =>
      assembliesApi.applyToBoq(assemblyId, boqId, parseFloat(quantity) || 1),
    onSuccess: () => {
      onClose();
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!boqId.trim()) return;
    applyMutation.mutate();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-md mx-4 animate-fade-in">
        <Card>
          <div className="flex items-start justify-between mb-5">
            <div>
              <h2 className="text-lg font-semibold text-content-primary">Apply to BOQ</h2>
              <p className="mt-0.5 text-sm text-content-secondary line-clamp-1">
                {assemblyName}
              </p>
            </div>
            <button
              onClick={onClose}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-all"
            >
              <X size={16} />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label="BOQ ID"
              value={boqId}
              onChange={(e) => setBoqId(e.target.value)}
              placeholder="Enter the BOQ identifier..."
              required
              autoFocus
            />

            <Input
              label="Quantity"
              type="number"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="1"
              hint="Number of times to apply this assembly"
            />

            {applyMutation.error && (
              <div className="rounded-lg bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
                {(applyMutation.error as Error).message || 'Failed to apply assembly to BOQ'}
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-1">
              <Button variant="secondary" type="button" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                type="submit"
                loading={applyMutation.isPending}
                icon={<Send size={15} />}
              >
                Apply
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
