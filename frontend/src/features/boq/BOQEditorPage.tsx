import { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Plus, Trash2, Download, ShieldCheck } from 'lucide-react';
import { Button, Badge, Card } from '@/shared/ui';
import { boqApi, type Position, type CreatePositionData, type UpdatePositionData } from './api';

const UNITS = ['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'];

export function BOQEditorPage() {
  const { t } = useTranslation();
  const { boqId } = useParams<{ boqId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: boq, isLoading } = useQuery({
    queryKey: ['boq', boqId],
    queryFn: () => boqApi.get(boqId!),
    enabled: !!boqId,
  });

  const addMutation = useMutation({
    mutationFn: (data: CreatePositionData) => boqApi.addPosition(data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['boq', boqId] }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdatePositionData }) =>
      boqApi.updatePosition(id, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['boq', boqId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => boqApi.deletePosition(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['boq', boqId] }),
  });

  const handleAddPosition = useCallback(() => {
    if (!boqId) return;
    const positions = boq?.positions ?? [];
    const nextNum = positions.length + 1;
    const ordinal = `01.01.${String(nextNum * 10).padStart(4, '0')}`;

    addMutation.mutate({
      boq_id: boqId,
      ordinal,
      description: '',
      unit: 'm2',
      quantity: 0,
      unit_rate: 0,
    });
  }, [boqId, boq, addMutation]);

  if (isLoading) {
    return (
      <div className="max-w-content mx-auto py-8 text-center text-content-secondary animate-fade-in">
        Loading BOQ...
      </div>
    );
  }

  if (!boq) {
    return (
      <div className="max-w-content mx-auto py-16 text-center">
        <p className="text-content-secondary">BOQ not found</p>
      </div>
    );
  }

  const fmt = (n: number) =>
    new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Header */}
      <button
        onClick={() => navigate(-1)}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
      >
        <ArrowLeft size={14} />
        Back to project
      </button>

      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{boq.name}</h1>
          {boq.description && (
            <p className="mt-1 text-sm text-content-secondary">{boq.description}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={boq.status === 'final' ? 'success' : 'blue'} size="md">
            {boq.status}
          </Badge>
          <Button
            variant="ghost"
            size="sm"
            icon={<ShieldCheck size={15} />}
            onClick={async () => {
              const token = localStorage.getItem('oe_access_token');
              try {
                const r = await fetch(`/api/v1/boq/boqs/${boqId}/validate`, {
                  method: 'POST',
                  headers: { Authorization: `Bearer ${token}` },
                });
                await r.json();
                navigate(`/validation`);
              } catch {
                alert('Validation failed');
              }
            }}
          >
            Validate
          </Button>
          <Button
            variant="ghost"
            size="sm"
            icon={<Download size={15} />}
            onClick={async () => {
              const token = localStorage.getItem('oe_access_token');
              const r = await fetch(`/api/v1/boq/boqs/${boqId}/export/excel`, {
                headers: { Authorization: `Bearer ${token}` },
              });
              if (r.ok) {
                const blob = await r.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${boq.name}.xlsx`;
                a.click();
                URL.revokeObjectURL(url);
              }
            }}
          >
            Excel
          </Button>
          <Button
            variant="ghost"
            size="sm"
            icon={<Download size={15} />}
            onClick={async () => {
              const token = localStorage.getItem('oe_access_token');
              const r = await fetch(`/api/v1/boq/boqs/${boqId}/export/csv`, {
                headers: { Authorization: `Bearer ${token}` },
              });
              if (r.ok) {
                const blob = await r.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${boq.name}.csv`;
                a.click();
                URL.revokeObjectURL(url);
              }
            }}
          >
            CSV
          </Button>
          <Button variant="primary" icon={<Plus size={16} />} onClick={handleAddPosition}>
            {t('boq.add_position')}
          </Button>
        </div>
      </div>

      {/* BOQ Table */}
      <Card padding="none" className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light bg-surface-tertiary text-left">
                <th className="px-4 py-3 font-medium text-content-secondary w-28">
                  {t('boq.ordinal')}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary min-w-[300px]">
                  {t('boq.description')}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-20 text-center">
                  {t('boq.unit')}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-28 text-right">
                  {t('boq.quantity')}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-28 text-right">
                  {t('boq.unit_rate')}
                </th>
                <th className="px-4 py-3 font-medium text-content-secondary w-32 text-right">
                  {t('boq.total')}
                </th>
                <th className="px-4 py-3 w-10" />
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {boq.positions.map((pos) => (
                <PositionRow
                  key={pos.id}
                  position={pos}
                  onUpdate={(data) => updateMutation.mutate({ id: pos.id, data })}
                  onDelete={() => deleteMutation.mutate(pos.id)}
                  fmt={fmt}
                />
              ))}
              {boq.positions.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-content-tertiary">
                    No positions yet. Click "Add Position" to start.
                  </td>
                </tr>
              )}
            </tbody>
            {boq.positions.length > 0 && (
              <tfoot>
                <tr className="border-t-2 border-border bg-surface-tertiary font-semibold">
                  <td colSpan={5} className="px-4 py-3 text-right text-content-primary">
                    {t('boq.grand_total')}
                  </td>
                  <td className="px-4 py-3 text-right text-content-primary text-base">
                    {fmt(boq.grand_total)}
                  </td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </Card>
    </div>
  );
}

/* ── Position Row — inline editable ───────────────────────────────────── */

function PositionRow({
  position,
  onUpdate,
  onDelete,
  fmt,
}: {
  position: Position;
  onUpdate: (data: UpdatePositionData) => void;
  onDelete: () => void;
  fmt: (n: number) => string;
}) {
  const [editing, setEditing] = useState<string | null>(null);

  const handleBlur = (field: string, value: string) => {
    setEditing(null);
    const numFields = ['quantity', 'unit_rate'];
    const update: UpdatePositionData = {
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
      {/* Ordinal */}
      <td className={cellClass}>
        <EditableCell
          value={position.ordinal}
          field="ordinal"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={`${inputClass} font-mono text-content-secondary`}
        />
      </td>

      {/* Description */}
      <td className={cellClass}>
        <EditableCell
          value={position.description}
          field="description"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={inputClass}
          placeholder="Enter description..."
        />
      </td>

      {/* Unit */}
      <td className="px-4 py-2.5 text-center">
        <select
          value={position.unit}
          onChange={(e) => onUpdate({ unit: e.target.value })}
          className="bg-transparent text-sm text-center cursor-pointer border-none outline-none text-content-secondary hover:text-content-primary"
        >
          {UNITS.map((u) => (
            <option key={u} value={u}>{u}</option>
          ))}
        </select>
      </td>

      {/* Quantity */}
      <td className={`${cellClass} text-right`}>
        <EditableCell
          value={String(position.quantity)}
          field="quantity"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={`${inputClass} text-right`}
          type="number"
        />
      </td>

      {/* Unit Rate */}
      <td className={`${cellClass} text-right`}>
        <EditableCell
          value={String(position.unit_rate)}
          field="unit_rate"
          editing={editing}
          setEditing={setEditing}
          onBlur={handleBlur}
          className={`${inputClass} text-right`}
          type="number"
        />
      </td>

      {/* Total (computed) */}
      <td className="px-4 py-2.5 text-right font-semibold text-content-primary">
        {fmt(position.total)}
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

/* ── Editable Cell ────────────────────────────────────────────────────── */

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
