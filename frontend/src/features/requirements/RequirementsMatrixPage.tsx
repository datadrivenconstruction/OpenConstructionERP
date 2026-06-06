// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wave 4 / T13 — ISO 19650 information-requirements matrix.
//
// Rows are project requirements (Entity · Attribute · Constraint).
// Columns are the ISO 19650 deliverable types (Model / Drawing /
// Schedule / Report / COBie / PSET) that prove a requirement is met.
// Cells carry a (LOD, LOI, status) triplet colour-coded by status
// (accepted = green, submitted = amber, missing = red).
//
// The page is self-sufficient: from an empty project a user can create
// a requirement set, add / edit / delete the requirements (rows), and
// click any cell to attach / edit / remove a deliverable. Everything is
// wired to the backend requirements module endpoints and confirmed with
// toasts. Backend RBAC is the authority on who may write — write actions
// surface a toast on a 403 rather than being hidden.
//
// Route: /requirements/matrix  (project chosen via the global
// ProjectContextStore active selector, with ``?project=`` deep-link
// fallback for external links).

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  ClipboardList,
  ExternalLink,
  Filter as FilterIcon,
  Link2,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from 'lucide-react';

import { BetaBanner } from '@/shared/ui/BetaBanner';
import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { DismissibleInfo, IntroRichText } from '@/shared/ui/DismissibleInfo';
import { PageHeader } from '@/shared/ui/PageHeader';
import { Button } from '@/shared/ui/Button';
import { Card } from '@/shared/ui/Card';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { WideModal, WideModalField, WideModalSection } from '@/shared/ui/WideModal';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  addRequirement,
  createDeliverable,
  createRequirementSet,
  deleteDeliverable,
  deleteRequirement,
  deleteRequirementSet,
  fetchRequirementSets,
  getMatrix,
  updateDeliverable,
  updateRequirement,
  updateRequirementSet,
  type AddRequirementPayload,
  type CreateDeliverablePayload,
  type Deliverable,
  type DeliverableStatus,
  type MatrixCell,
  type MatrixResponse,
  type MatrixRow,
  type RequirementSet,
  type UpdateDeliverablePayload,
  type UpdateRequirementPayload,
} from './api';

// ── Constants ──────────────────────────────────────────────────────────

const CANONICAL_TYPES = [
  'model',
  'drawing',
  'schedule',
  'report',
  'cobie',
  'pset',
] as const;

const LOD_OPTIONS = ['100', '200', '300', '350', '400', '500'] as const;
const LOI_OPTIONS = ['1', '2', '3', '4', '5'] as const;

// Must match the backend RequirementCreate `constraint_type` pattern.
const CONSTRAINT_TYPES = [
  'equals',
  'not_equals',
  'min',
  'max',
  'range',
  'contains',
  'not_contains',
  'regex',
  'exists',
  'not_exists',
] as const;

const PRIORITY_OPTIONS = ['must', 'should', 'may'] as const;
// Mirrors the backend RequirementUpdate `status` pattern.
const REQ_STATUS_OPTIONS = ['open', 'verified', 'linked', 'conflict'] as const;

const STATUS_LABEL: Record<DeliverableStatus, string> = {
  accepted: 'Accepted',
  submitted: 'Submitted',
  missing: 'Missing',
};

const TYPE_LABEL: Record<string, string> = {
  model: 'Model',
  drawing: 'Drawing',
  schedule: 'Schedule',
  report: 'Report',
  cobie: 'COBie',
  pset: 'PSET',
  other: 'Other',
};

// Where each ISO 19650 deliverable type lives in the app. The cell editor
// surfaces an "Open deliverable" link routing to the module that proves the
// requirement (a model in the BIM viewer, a drawing in markups, a schedule in
// the 4D Gantt, a report in Reports, etc.). The deliverable rows carry only a
// type (no per-record FK on the backend), so we deep-link to the module home
// scoped to the active project rather than a single record.
const DELIVERABLE_ROUTE: Record<string, string> = {
  model: '/bim',
  drawing: '/markups',
  schedule: '/schedule',
  report: '/reports',
  cobie: '/files',
  pset: '/bim',
  other: '/files',
};

/** Route for a deliverable type, scoped to the active project where useful. */
function deliverableRoute(deliverableType: string, projectId: string): string {
  const base = DELIVERABLE_ROUTE[deliverableType] ?? '/files';
  return projectId ? `${base}?project=${encodeURIComponent(projectId)}` : base;
}

// Tailwind colour classes per status — heatmap cell background +
// accent border + text. Keeps the matrix scannable at a glance.
const CELL_STYLE: Record<DeliverableStatus, string> = {
  accepted:
    'bg-green-50 border-green-300 text-green-900 hover:bg-green-100 dark:bg-green-900/30 dark:border-green-700 dark:text-green-100 dark:hover:bg-green-900/50',
  submitted:
    'bg-amber-50 border-amber-300 text-amber-900 hover:bg-amber-100 dark:bg-amber-900/30 dark:border-amber-700 dark:text-amber-100 dark:hover:bg-amber-900/50',
  missing:
    'bg-red-50 border-red-200 text-red-700 hover:bg-red-100 dark:bg-red-900/20 dark:border-red-800/60 dark:text-red-300 dark:hover:bg-red-900/40',
};

const INPUT_CLASS =
  'h-9 w-full rounded-md border border-border bg-surface-primary px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue';

// ── Coverage chip ───────────────────────────────────────────────────────

interface CoverageChipProps {
  pct: number;
}

function CoverageChip({ pct }: CoverageChipProps) {
  const tone =
    pct >= 80
      ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-200'
      : pct >= 50
        ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200'
        : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-200';
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
        tone,
      )}
    >
      {pct.toFixed(0)}%
    </span>
  );
}

// ── Requirement editor modal (rows) ──────────────────────────────────────

interface ReqEditorState {
  open: boolean;
  /** null = create; otherwise edit this matrix row. */
  row: MatrixRow | null;
}

interface ReqEditorProps {
  state: ReqEditorState;
  /** Set the new requirement is created in (only used when creating). */
  setId: string | null;
  onClose: () => void;
  onSaved: () => void;
}

function RequirementEditor({ state, setId, onClose, onSaved }: ReqEditorProps) {
  const { t } = useTranslation();
  const toast = useToastStore((s) => s.addToast);
  const isEditing = state.row != null;

  // The matrix row carries entity/attribute/priority only, so for edits we
  // can prefill those three and leave the rest for the user to fill in.
  const [entity, setEntity] = useState('');
  const [attribute, setAttribute] = useState('');
  const [constraintType, setConstraintType] = useState<string>('equals');
  const [constraintValue, setConstraintValue] = useState('');
  const [unit, setUnit] = useState('');
  const [category, setCategory] = useState('general');
  const [priority, setPriority] = useState<string>('must');
  const [status, setStatus] = useState<string>('open');
  const [notes, setNotes] = useState('');

  useEffect(() => {
    setEntity(state.row?.entity ?? '');
    setAttribute(state.row?.attribute ?? '');
    setConstraintType('equals');
    setConstraintValue('');
    setUnit('');
    setCategory('general');
    setPriority(state.row?.priority || 'must');
    setStatus('open');
    setNotes('');
  }, [state.open, state.row?.requirement_id]);

  const save = useMutation({
    mutationFn: async () => {
      const entityClean = entity.trim();
      const attributeClean = attribute.trim();
      if (!entityClean || !attributeClean) {
        throw new Error(t('requirements.matrix.required', { defaultValue: 'Entity and attribute are required.' }));
      }
      if (isEditing && state.row) {
        const payload: UpdateRequirementPayload = {
          entity: entityClean,
          attribute: attributeClean,
          constraint_type: constraintType,
          constraint_value: constraintValue,
          unit,
          category,
          priority,
          status,
          notes,
        };
        await updateRequirement(state.row.requirement_set_id, state.row.requirement_id, payload);
      } else {
        if (!setId) throw new Error('No requirement set selected');
        const payload: AddRequirementPayload = {
          entity: entityClean,
          attribute: attributeClean,
          constraint_type: constraintType,
          constraint_value: constraintValue,
          unit,
          category,
          priority,
          notes,
        };
        await addRequirement(setId, payload);
      }
    },
    onSuccess: () => {
      toast({
        type: 'success',
        title: isEditing
          ? t('requirements.req_updated', { defaultValue: 'Requirement updated' })
          : t('requirements.req_added', { defaultValue: 'Requirement added' }),
      });
      onSaved();
      onClose();
    },
    onError: (err) => {
      toast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: (err as Error).message });
    },
  });

  if (!state.open) return null;

  return (
    <WideModal
      open={state.open}
      onClose={onClose}
      title={
        isEditing
          ? t('requirements.edit_requirement', { defaultValue: 'Edit Requirement' })
          : t('requirements.add_requirement', { defaultValue: 'Add Requirement' })
      }
      subtitle={t('requirements.matrix.empty_no_reqs_desc', {
        defaultValue:
          'Add your first requirement, an Entity, an Attribute and a Constraint, then attach the deliverables that satisfy it in the columns on the right.',
      })}
      size="lg"
      busy={save.isPending}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" size="md" onClick={() => save.mutate()} loading={save.isPending}>
            {isEditing ? t('common.save', { defaultValue: 'Save' }) : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection title={t('requirements.matrix.col_requirement', { defaultValue: 'Requirement' })} columns={2}>
        <WideModalField label={t('requirements.entity', { defaultValue: 'Entity' })} required htmlFor="req-entity">
          <input
            id="req-entity"
            value={entity}
            onChange={(e) => setEntity(e.target.value)}
            placeholder={t('requirements.entity_placeholder', { defaultValue: 'e.g. wall, floor, roof' })}
            className={INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField label={t('requirements.attribute', { defaultValue: 'Attribute' })} required htmlFor="req-attr">
          <input
            id="req-attr"
            value={attribute}
            onChange={(e) => setAttribute(e.target.value)}
            placeholder={t('requirements.attribute_placeholder', { defaultValue: 'e.g. thickness, fire_rating' })}
            className={INPUT_CLASS}
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection title={t('requirements.constraint', { defaultValue: 'Constraint' })} columns={3}>
        <WideModalField label={t('requirements.constraint_type', { defaultValue: 'Constraint Type' })} htmlFor="req-ctype">
          <select id="req-ctype" value={constraintType} onChange={(e) => setConstraintType(e.target.value)} className={INPUT_CLASS}>
            {CONSTRAINT_TYPES.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('requirements.constraint_value', { defaultValue: 'Value' })} htmlFor="req-cval">
          <input
            id="req-cval"
            value={constraintValue}
            onChange={(e) => setConstraintValue(e.target.value)}
            placeholder={t('requirements.value_placeholder', { defaultValue: 'e.g. 200, C30/37, F90' })}
            className={INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField label={t('requirements.unit', { defaultValue: 'Unit' })} htmlFor="req-unit">
          <input id="req-unit" value={unit} onChange={(e) => setUnit(e.target.value)} placeholder="mm, m², W/m²K" className={INPUT_CLASS} />
        </WideModalField>
      </WideModalSection>

      <WideModalSection title={t('requirements.matrix.classification', { defaultValue: 'Classification' })} columns={isEditing ? 3 : 2}>
        <WideModalField label={t('requirements.category', { defaultValue: 'Category' })} htmlFor="req-cat">
          <input id="req-cat" value={category} onChange={(e) => setCategory(e.target.value)} className={INPUT_CLASS} />
        </WideModalField>
        <WideModalField label={t('requirements.priority', { defaultValue: 'Priority' })} htmlFor="req-prio">
          <select id="req-prio" value={priority} onChange={(e) => setPriority(e.target.value)} className={INPUT_CLASS}>
            {PRIORITY_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {t(`requirements.matrix.priority_${v}`, { defaultValue: v })}
              </option>
            ))}
          </select>
        </WideModalField>
        {isEditing && (
          <WideModalField label={t('requirements.matrix.status', { defaultValue: 'Status' })} htmlFor="req-status">
            <select id="req-status" value={status} onChange={(e) => setStatus(e.target.value)} className={INPUT_CLASS}>
              {REQ_STATUS_OPTIONS.map((v) => (
                <option key={v} value={v}>
                  {t(`requirements.matrix.status_${v}`, { defaultValue: v })}
                </option>
              ))}
            </select>
          </WideModalField>
        )}
      </WideModalSection>

      <WideModalSection title={t('requirements.notes', { defaultValue: 'Notes' })} columns={1}>
        <WideModalField label={t('requirements.notes', { defaultValue: 'Notes' })} htmlFor="req-notes">
          <textarea
            id="req-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            placeholder={t('requirements.notes_placeholder', { defaultValue: 'Additional notes or context...' })}
            className="w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

// ── Set editor modal (create / rename) ───────────────────────────────────

interface SetEditorState {
  open: boolean;
  /** null = create; otherwise rename this set. */
  set: RequirementSet | null;
}

interface SetEditorProps {
  state: SetEditorState;
  projectId: string;
  onClose: () => void;
  onSaved: (created?: RequirementSet) => void;
}

function SetEditor({ state, projectId, onClose, onSaved }: SetEditorProps) {
  const { t } = useTranslation();
  const toast = useToastStore((s) => s.addToast);
  const isEditing = state.set != null;
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  useEffect(() => {
    setName(state.set?.name ?? '');
    setDescription(state.set?.description ?? '');
  }, [state.open, state.set?.id]);

  const save = useMutation({
    mutationFn: async (): Promise<RequirementSet | undefined> => {
      const nameClean = name.trim();
      if (!nameClean) throw new Error(t('requirements.set_name_placeholder', { defaultValue: 'A set name is required.' }));
      if (isEditing && state.set) {
        return updateRequirementSet(state.set.id, { name: nameClean, description });
      }
      return createRequirementSet({ project_id: projectId, name: nameClean, description });
    },
    onSuccess: (created) => {
      toast({
        type: 'success',
        title: isEditing
          ? t('requirements.matrix.set_renamed', { defaultValue: 'Requirement set updated' })
          : t('requirements.set_created', { defaultValue: 'Requirement set created' }),
      });
      onSaved(created);
      onClose();
    },
    onError: (err) => {
      toast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: (err as Error).message });
    },
  });

  if (!state.open) return null;

  return (
    <WideModal
      open={state.open}
      onClose={onClose}
      title={
        isEditing
          ? t('requirements.matrix.rename_set', { defaultValue: 'Rename set' })
          : t('requirements.matrix.new_set', { defaultValue: 'New requirement set' })
      }
      subtitle={t('requirements.matrix.empty_no_sets_desc', {
        defaultValue:
          'A requirement set groups the requirements for this project. Create one to start adding requirements.',
      })}
      size="md"
      busy={save.isPending}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" size="md" onClick={() => save.mutate()} loading={save.isPending}>
            {isEditing ? t('common.save', { defaultValue: 'Save' }) : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection columns={1}>
        <WideModalField label={t('requirements.matrix.set_name', { defaultValue: 'Set name' })} required htmlFor="set-name">
          <input
            id="set-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('requirements.set_name_placeholder', { defaultValue: 'e.g. Structural Requirements Phase 1' })}
            className={INPUT_CLASS}
          />
        </WideModalField>
        <WideModalField label={t('requirements.matrix.set_description', { defaultValue: 'Description' })} htmlFor="set-desc">
          <textarea
            id="set-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder={t('requirements.matrix.set_description_placeholder', {
              defaultValue: 'Optional, e.g. structural information requirements for stage 4',
            })}
            className="w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

// ── Deliverable cell editor modal ─────────────────────────────────────────

interface CellEditorState {
  open: boolean;
  row: MatrixRow | null;
  deliverableType: string;
  cell: MatrixCell | null;
}

interface CellEditorProps {
  state: CellEditorState;
  projectId: string;
  onClose: () => void;
  onSaved: () => void;
}

function CellEditor({ state, projectId, onClose, onSaved }: CellEditorProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toast = useToastStore((s) => s.addToast);
  const isEditing = state.cell?.deliverable_id != null;

  const [lod, setLod] = useState<string>(state.cell?.lod ?? '');
  const [loi, setLoi] = useState<string>(state.cell?.loi ?? '');
  const [submittedAt, setSubmittedAt] = useState<string>(
    state.cell?.submitted_at ? state.cell.submitted_at.slice(0, 16) : '',
  );
  const [acceptedAt, setAcceptedAt] = useState<string>(
    state.cell?.accepted_at ? state.cell.accepted_at.slice(0, 16) : '',
  );

  // Reset local state whenever the modal opens with a different cell —
  // otherwise reopening on a new (row, col) keeps stale values.
  useEffect(() => {
    setLod(state.cell?.lod ?? '');
    setLoi(state.cell?.loi ?? '');
    setSubmittedAt(state.cell?.submitted_at ? state.cell.submitted_at.slice(0, 16) : '');
    setAcceptedAt(state.cell?.accepted_at ? state.cell.accepted_at.slice(0, 16) : '');
  }, [state.open, state.row?.requirement_id, state.deliverableType]);

  const buildPayload = (): CreateDeliverablePayload | UpdateDeliverablePayload => {
    const toIso = (s: string): string | null => (s ? new Date(s).toISOString() : null);
    return {
      deliverable_type: state.deliverableType,
      lod: lod || null,
      loi: loi || null,
      submitted_at: toIso(submittedAt),
      accepted_at: toIso(acceptedAt),
    };
  };

  const save = useMutation({
    mutationFn: async () => {
      if (!state.row) return;
      if (isEditing && state.cell?.deliverable_id) {
        await updateDeliverable(
          state.row.requirement_id,
          state.cell.deliverable_id,
          buildPayload() as UpdateDeliverablePayload,
        );
      } else {
        await createDeliverable(state.row.requirement_id, buildPayload() as CreateDeliverablePayload);
      }
    },
    onSuccess: () => {
      toast({
        type: 'success',
        title: isEditing
          ? t('requirements.deliverable_updated', { defaultValue: 'Deliverable updated' })
          : t('requirements.deliverable_added', { defaultValue: 'Deliverable added' }),
      });
      onSaved();
      onClose();
    },
    onError: (err) => {
      toast({ type: 'error', title: t('common.error', { defaultValue: 'Save failed' }), message: (err as Error).message });
    },
  });

  const remove = useMutation({
    mutationFn: async () => {
      if (!state.row || !state.cell?.deliverable_id) return;
      await deleteDeliverable(state.row.requirement_id, state.cell.deliverable_id);
    },
    onSuccess: () => {
      toast({ type: 'success', title: t('requirements.deliverable_removed', { defaultValue: 'Deliverable removed' }) });
      onSaved();
      onClose();
    },
    onError: (err) => {
      toast({ type: 'error', title: t('common.error', { defaultValue: 'Delete failed' }), message: (err as Error).message });
    },
  });

  if (!state.open || !state.row) return null;

  const typeLabel = TYPE_LABEL[state.deliverableType] ?? state.deliverableType;
  const title = `${typeLabel} - ${state.row.entity}.${state.row.attribute}`;

  return (
    <WideModal
      open={state.open}
      onClose={onClose}
      title={title}
      subtitle={
        isEditing
          ? t('requirements.matrix.deliverable_edit_sub', {
              defaultValue: 'Edit the LOD / LOI and submission timestamps for this deliverable.',
            })
          : t('requirements.matrix.deliverable_new_sub', {
              defaultValue: 'Attach a new ISO 19650 deliverable to this requirement.',
            })
      }
      size="md"
      busy={save.isPending || remove.isPending}
      footer={
        <>
          {isEditing && (
            <Button variant="danger" size="md" onClick={() => remove.mutate()} loading={remove.isPending}>
              {t('common.remove', { defaultValue: 'Remove' })}
            </Button>
          )}
          <Button variant="ghost" size="md" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" size="md" onClick={() => save.mutate()} loading={save.isPending}>
            {isEditing ? t('common.save', { defaultValue: 'Save' }) : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <WideModalSection title={t('requirements.matrix.lod_loi', { defaultValue: 'Level of detail / information' })} columns={2}>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-content-secondary">LOD (BIMForum)</span>
          <select value={lod} onChange={(e) => setLod(e.target.value)} className={INPUT_CLASS}>
            <option value="">—</option>
            {LOD_OPTIONS.map((v) => (
              <option key={v} value={v}>
                LOD {v}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-content-secondary">LOI (ISO 19650)</span>
          <select value={loi} onChange={(e) => setLoi(e.target.value)} className={INPUT_CLASS}>
            <option value="">—</option>
            {LOI_OPTIONS.map((v) => (
              <option key={v} value={v}>
                LOI {v}
              </option>
            ))}
          </select>
        </label>
      </WideModalSection>

      <WideModalSection title={t('requirements.matrix.submission', { defaultValue: 'Submission lifecycle' })} columns={2}>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-content-secondary">{t('requirements.matrix.submitted_at', { defaultValue: 'Submitted at' })}</span>
          <input type="datetime-local" value={submittedAt} onChange={(e) => setSubmittedAt(e.target.value)} className={INPUT_CLASS} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-content-secondary">{t('requirements.matrix.accepted_at', { defaultValue: 'Accepted at' })}</span>
          <input type="datetime-local" value={acceptedAt} onChange={(e) => setAcceptedAt(e.target.value)} className={INPUT_CLASS} />
        </label>
      </WideModalSection>

      {/* Open deliverable: route to the module that proves this requirement
          (model -> BIM viewer, drawing -> markups, schedule -> 4D, etc.). */}
      <WideModalSection title={t('requirements.matrix.open_deliverable', { defaultValue: 'Open deliverable' })} columns={1}>
        <div className="flex flex-col gap-2">
          <p className="text-xs text-content-secondary">
            {t('requirements.matrix.open_deliverable_hint', {
              defaultValue:
                'Jump to where this {{type}} deliverable lives to review or attach the evidence that satisfies the requirement.',
              type: typeLabel,
            })}
          </p>
          <div>
            <Button
              variant="secondary"
              size="sm"
              icon={<ExternalLink size={14} />}
              onClick={() => {
                navigate(deliverableRoute(state.deliverableType, projectId));
                onClose();
              }}
            >
              {t('requirements.matrix.open_in_module', {
                defaultValue: 'Open {{type}}',
                type: typeLabel,
              })}
            </Button>
          </div>
        </div>
      </WideModalSection>
    </WideModal>
  );
}

// ── Legend ────────────────────────────────────────────────────────────────

function StatusLegend() {
  const { t } = useTranslation();
  const items: Array<{ status: DeliverableStatus; label: string }> = [
    { status: 'accepted', label: t('requirements.matrix.status_accepted', { defaultValue: 'Accepted' }) },
    { status: 'submitted', label: t('requirements.matrix.status_submitted', { defaultValue: 'Submitted' }) },
    { status: 'missing', label: t('requirements.matrix.status_missing', { defaultValue: 'Missing' }) },
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-content-secondary">
      <span className="font-medium">{t('requirements.matrix.legend', { defaultValue: 'Legend' })}:</span>
      {items.map((it) => (
        <span key={it.status} className="inline-flex items-center gap-1.5">
          <span className={clsx('h-3 w-3 rounded-sm border', CELL_STYLE[it.status])} />
          {it.label}
        </span>
      ))}
      <span className="text-content-tertiary">{t('requirements.matrix.legend_hint', { defaultValue: 'Click any cell to add or edit a deliverable.' })}</span>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────

export function RequirementsMatrixPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const ctxProjectId = useProjectContextStore((s) => s.activeProjectId);
  const ctxProjectName = useProjectContextStore((s) => s.activeProjectName);
  const projectId = ctxProjectId ?? params.get('project') ?? '';
  const toast = useToastStore((s) => s.addToast);

  const [typeFilter, setTypeFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<DeliverableStatus | ''>('');
  const [setFilter, setSetFilter] = useState<string>('');

  const [cellEditor, setCellEditor] = useState<CellEditorState>({
    open: false,
    row: null,
    deliverableType: '',
    cell: null,
  });
  const [reqEditor, setReqEditor] = useState<ReqEditorState>({ open: false, row: null });
  const [setEditor, setSetEditor] = useState<SetEditorState>({ open: false, set: null });
  const [reqToDelete, setReqToDelete] = useState<MatrixRow | null>(null);
  const [setToDelete, setSetToDelete] = useState<RequirementSet | null>(null);

  // Keep `?project=` in the URL in sync with the active project so the
  // back button + deep-links stay coherent.
  useEffect(() => {
    if (projectId && params.get('project') !== projectId) {
      const next = new URLSearchParams(params);
      next.set('project', projectId);
      setParams(next, { replace: true });
    }
  }, [projectId, params, setParams]);

  const qc = useQueryClient();
  const matrixQuery = useQuery<MatrixResponse>({
    queryKey: ['requirements-matrix', projectId, typeFilter],
    enabled: !!projectId,
    queryFn: () => getMatrix(projectId, typeFilter || undefined),
  });
  const setsQuery = useQuery<RequirementSet[]>({
    queryKey: ['requirements-sets', projectId],
    enabled: !!projectId,
    queryFn: () => fetchRequirementSets(projectId),
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['requirements-matrix', projectId] });
    qc.invalidateQueries({ queryKey: ['requirements-sets', projectId] });
  };

  const sets = setsQuery.data ?? [];
  const hasSets = sets.length > 0;
  const setNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of sets) m.set(s.id, s.name);
    return m;
  }, [sets]);

  // The set new requirements are added to: the filtered set if one is
  // selected, else the first (most-recent) set on the project.
  const targetSetId = setFilter || sets[0]?.id || null;
  const targetSet = sets.find((s) => s.id === targetSetId) ?? null;

  // Apply filters client-side. Server already trims columns when
  // typeFilter is set; we additionally filter by set and by status.
  const visibleRows: MatrixRow[] = useMemo(() => {
    if (!matrixQuery.data) return [];
    const cols = typeFilter ? [typeFilter] : matrixQuery.data.deliverable_types;
    return matrixQuery.data.rows.filter((row) => {
      if (setFilter && row.requirement_set_id !== setFilter) return false;
      if (statusFilter && !cols.some((col) => row.cells[col]?.status === statusFilter)) return false;
      return true;
    });
  }, [matrixQuery.data, typeFilter, statusFilter, setFilter]);

  const cols = matrixQuery.data?.deliverable_types?.length
    ? matrixQuery.data.deliverable_types
    : (CANONICAL_TYPES as readonly string[]);

  const totalRows = matrixQuery.data?.rows.length ?? 0;
  const filtersActive = !!typeFilter || !!statusFilter || !!setFilter;

  const deleteReq = useMutation({
    mutationFn: async (row: MatrixRow) => {
      await deleteRequirement(row.requirement_set_id, row.requirement_id);
    },
    onSuccess: () => {
      toast({ type: 'success', title: t('requirements.req_deleted', { defaultValue: 'Requirement deleted' }) });
      setReqToDelete(null);
      refresh();
    },
    onError: (err) => {
      toast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: (err as Error).message });
    },
  });

  const deleteSet = useMutation({
    mutationFn: async (s: RequirementSet) => {
      await deleteRequirementSet(s.id);
    },
    onSuccess: () => {
      toast({ type: 'success', title: t('requirements.set_deleted', { defaultValue: 'Requirement set deleted' }) });
      setSetToDelete(null);
      if (setFilter === setToDelete?.id) setSetFilter('');
      refresh();
    },
    onError: (err) => {
      toast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: (err as Error).message });
    },
  });

  // ── Render ────────────────────────────────────────────────────────

  if (!projectId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={<ClipboardList size={32} />}
          title={t('requirements.matrix.select_project', { defaultValue: 'Select a project' })}
          description={t('requirements.matrix.select_project_desc', {
            defaultValue: 'Pick an active project from the global selector to view and edit its requirements matrix.',
          })}
        />
      </div>
    );
  }

  const subtitle = ctxProjectName
    ? t('requirements.matrix.subtitle', {
        defaultValue: 'ISO 19650 information requirements and their deliverable coverage for {{project}}.',
        project: ctxProjectName,
      })
    : t('requirements.matrix.subtitle_generic', {
        defaultValue: 'ISO 19650 information requirements and their deliverable coverage for the selected project.',
      });

  const loading = matrixQuery.isLoading || setsQuery.isLoading;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(ctxProjectName
            ? [{ label: ctxProjectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('nav.eir_matrix', { defaultValue: 'EIR Matrix (ISO 19650)' }) },
        ]}
      />
      <BetaBanner moduleKey="requirements" className="mt-3" />

      {/* Header */}
      <PageHeader
        srTitle={t('nav.eir_matrix', { defaultValue: 'EIR Matrix (ISO 19650)' })}
        subtitle={subtitle}
        actions={
          <>
            {matrixQuery.data && totalRows > 0 && (
              <div className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-elevated px-3 py-1.5 text-sm">
                <span className="text-content-secondary">{t('requirements.matrix.project_coverage', { defaultValue: 'Project coverage' })}</span>
                <CoverageChip pct={matrixQuery.data.coverage_pct} />
              </div>
            )}
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw size={14} />}
              onClick={refresh}
              disabled={matrixQuery.isFetching || setsQuery.isFetching}
            >
              {t('requirements.matrix.refresh', { defaultValue: 'Refresh' })}
            </Button>
            {hasSets && (
              <Button
                variant="primary"
                size="sm"
                icon={<Plus size={14} />}
                onClick={() => setReqEditor({ open: true, row: null })}
              >
                {t('requirements.matrix.add_requirement', { defaultValue: 'Add requirement' })}
              </Button>
            )}
          </>
        }
      />

      {/* Canonical intro card (replaces the old "What is this?" toggle) */}
      <DismissibleInfo
        storageKey="requirements/matrix"
        title={t('requirements.intro_title', {
          defaultValue: 'Prove every information requirement was met',
        })}
        more={
          t('requirements.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('requirements.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('nav.bim_rules', { defaultValue: 'Rule Packs' }),
            onClick: () => navigate('/bim/rules'),
          },
          {
            label: t('nav.coordination_hub', { defaultValue: 'Coordination Hub' }),
            onClick: () => navigate('/coordination'),
          },
        ]}
      >
        {t('requirements.intro_body', {
          defaultValue:
            'Write each project requirement as Entity, Attribute and Constraint, for example exterior wall, fire rating, equals F90, then map it against the ISO 19650 deliverables that prove it, model, drawing, schedule, report, COBie or property set. Every cell shows the level of information delivered and turns green when accepted, amber when submitted and red when still missing, giving a live coverage score for the active project.',
        })}
      </DismissibleInfo>

      {/* Filters + legend (only meaningful once requirements exist) */}
      {hasSets && totalRows > 0 && (
        <Card padding="sm">
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex items-center gap-2 text-sm text-content-secondary">
                <FilterIcon size={14} /> {t('common.filters', { defaultValue: 'Filters' })}
              </div>
              {sets.length > 1 && (
                <label className="flex items-center gap-1.5 text-sm">
                  <span className="text-content-secondary">{t('requirements.matrix.set_label', { defaultValue: 'Requirement set' })}</span>
                  <select value={setFilter} onChange={(e) => setSetFilter(e.target.value)} className="h-8 rounded-md border border-border bg-surface-primary px-2 text-sm">
                    <option value="">{t('requirements.matrix.set_all', { defaultValue: 'All sets' })}</option>
                    {sets.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="flex items-center gap-1.5 text-sm">
                <span className="text-content-secondary">{t('requirements.matrix.col_deliverable', { defaultValue: 'Deliverable' })}</span>
                <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} className="h-8 rounded-md border border-border bg-surface-primary px-2 text-sm">
                  <option value="">{t('common.all', { defaultValue: 'All' })}</option>
                  {cols.map((tcol) => (
                    <option key={tcol} value={tcol}>
                      {TYPE_LABEL[tcol] ?? tcol}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-1.5 text-sm">
                <span className="text-content-secondary">{t('requirements.matrix.status', { defaultValue: 'Status' })}</span>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value as DeliverableStatus | '')}
                  className="h-8 rounded-md border border-border bg-surface-primary px-2 text-sm"
                >
                  <option value="">{t('common.all', { defaultValue: 'All' })}</option>
                  <option value="accepted">{t('requirements.matrix.status_accepted', { defaultValue: 'Accepted' })}</option>
                  <option value="submitted">{t('requirements.matrix.status_submitted', { defaultValue: 'Submitted' })}</option>
                  <option value="missing">{t('requirements.matrix.status_missing', { defaultValue: 'Missing' })}</option>
                </select>
              </label>
              {filtersActive && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setTypeFilter('');
                    setStatusFilter('');
                    setSetFilter('');
                  }}
                >
                  {t('common.clear', { defaultValue: 'Clear' })}
                </Button>
              )}
              {/* Set management for the active set */}
              {targetSet && (
                <div className="ml-auto flex items-center gap-1">
                  <Button variant="ghost" size="sm" icon={<Pencil size={13} />} onClick={() => setSetEditor({ open: true, set: targetSet })}>
                    {t('requirements.matrix.rename_set', { defaultValue: 'Rename set' })}
                  </Button>
                  <Button variant="ghost" size="sm" icon={<Trash2 size={13} />} onClick={() => setSetToDelete(targetSet)}>
                    {t('requirements.matrix.delete_set', { defaultValue: 'Delete set' })}
                  </Button>
                </div>
              )}
            </div>
            <StatusLegend />
          </div>
        </Card>
      )}

      {/* Matrix / states */}
      <Card padding="none" className="overflow-hidden">
        {loading ? (
          <SkeletonTable rows={6} columns={5} className="border-0 rounded-none" />
        ) : matrixQuery.isError ? (
          <div className="p-6 text-sm text-red-600">
            {t('requirements.matrix.load_failed', { defaultValue: 'Failed to load the requirements matrix:' })}{' '}
            {(matrixQuery.error as Error).message}
          </div>
        ) : !hasSets ? (
          <EmptyState
            icon={<ClipboardList size={28} />}
            title={t('requirements.matrix.empty_no_sets_title', { defaultValue: 'No requirements yet' })}
            description={t('requirements.matrix.empty_no_sets_desc', {
              defaultValue:
                'A requirement set groups the requirements for this project. Create one to start adding requirements, then attach the deliverables that satisfy each one.',
            })}
            action={{
              label: t('requirements.matrix.create_set', { defaultValue: 'Create requirement set' }),
              onClick: () => setSetEditor({ open: true, set: null }),
            }}
          />
        ) : totalRows === 0 ? (
          <EmptyState
            icon={<ClipboardList size={28} />}
            title={t('requirements.matrix.empty_no_reqs_title', { defaultValue: 'This set has no requirements' })}
            description={t('requirements.matrix.empty_no_reqs_desc', {
              defaultValue:
                'Add your first requirement, an Entity, an Attribute and a Constraint, then attach the deliverables that satisfy it in the columns on the right.',
            })}
            action={{
              label: t('requirements.matrix.add_first_requirement', { defaultValue: 'Add your first requirement' }),
              onClick: () => setReqEditor({ open: true, row: null }),
            }}
          />
        ) : visibleRows.length === 0 ? (
          <EmptyState
            icon={<FilterIcon size={28} />}
            title={t('requirements.matrix.empty_filtered_title', { defaultValue: 'No matching requirements' })}
            description={t('requirements.matrix.empty_filtered_desc', {
              defaultValue: 'No requirement matches the current filters. Clear the filters to see them all.',
            })}
            action={{
              label: t('common.clear', { defaultValue: 'Clear filters' }),
              onClick: () => {
                setTypeFilter('');
                setStatusFilter('');
                setSetFilter('');
              },
            }}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse">
              <thead className="bg-surface-secondary/60 text-xs uppercase tracking-wider text-content-secondary">
                <tr>
                  <th className="sticky left-0 z-10 min-w-[220px] bg-surface-secondary/60 px-3 py-2 text-left font-medium">
                    {t('requirements.matrix.col_requirement', { defaultValue: 'Requirement' })}
                  </th>
                  {sets.length > 1 && !setFilter && (
                    <th className="px-3 py-2 text-left font-medium">{t('requirements.matrix.col_set', { defaultValue: 'Set' })}</th>
                  )}
                  <th className="px-3 py-2 text-left font-medium">{t('requirements.matrix.col_coverage', { defaultValue: 'Coverage' })}</th>
                  {cols.map((col) => (
                    <th key={col} className="min-w-[120px] px-3 py-2 text-left font-medium">
                      {TYPE_LABEL[col] ?? col}
                    </th>
                  ))}
                  <th className="px-3 py-2 text-right font-medium">{t('requirements.matrix.col_actions', { defaultValue: 'Actions' })}</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr key={row.requirement_id} className="group/row border-t border-border-light/60 hover:bg-surface-secondary/30">
                    <td className="sticky left-0 z-10 max-w-[280px] bg-surface-elevated px-3 py-2 align-top group-hover/row:bg-surface-secondary/30">
                      <div className="truncate font-medium text-content-primary" title={`${row.entity}.${row.attribute}`}>
                        {row.entity}
                      </div>
                      <div className="text-xs text-content-secondary">
                        {row.attribute}
                        {row.priority && (
                          <span className="ml-1 rounded bg-surface-secondary px-1 py-0.5 text-[10px] uppercase">
                            {t(`requirements.matrix.priority_${row.priority}`, { defaultValue: row.priority })}
                          </span>
                        )}
                      </div>
                      {row.linked_position_id && (
                        <button
                          type="button"
                          onClick={() =>
                            navigate(`/boq?positionId=${encodeURIComponent(row.linked_position_id as string)}`)
                          }
                          title={t('requirements.matrix.open_boq_position', {
                            defaultValue: 'Open the linked BOQ position',
                          })}
                          className="mt-1 inline-flex items-center gap-1 rounded-full border border-oe-blue/30 bg-oe-blue/10 px-2 py-0.5 text-[11px] font-medium text-oe-blue transition hover:bg-oe-blue/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
                        >
                          <Link2 size={11} />
                          {t('requirements.matrix.linked_boq', { defaultValue: 'BOQ' })}
                        </button>
                      )}
                    </td>
                    {sets.length > 1 && !setFilter && (
                      <td className="px-3 py-2 align-middle text-xs text-content-secondary">
                        {setNameById.get(row.requirement_set_id) ?? '—'}
                      </td>
                    )}
                    <td className="px-3 py-2 align-middle">
                      <CoverageChip pct={row.coverage_pct} />
                    </td>
                    {cols.map((col) => {
                      const cell = row.cells[col];
                      const status: DeliverableStatus = (cell?.status as DeliverableStatus) ?? 'missing';
                      return (
                        <td key={col} className="px-2 py-2 align-middle">
                          <button
                            type="button"
                            onClick={() => setCellEditor({ open: true, row, deliverableType: col, cell: cell ?? null })}
                            className={clsx(
                              'group flex w-full min-w-[120px] flex-col items-start gap-0.5 rounded-lg border px-2.5 py-1.5 text-left text-xs transition',
                              CELL_STYLE[status],
                            )}
                            aria-label={`${TYPE_LABEL[col] ?? col} - ${STATUS_LABEL[status]} - ${row.entity}.${row.attribute}`}
                          >
                            <span className="font-semibold uppercase tracking-wide">
                              {t(`requirements.matrix.status_${status}`, { defaultValue: STATUS_LABEL[status] })}
                            </span>
                            <span className="text-[11px] opacity-80">
                              {cell?.lod ? `LOD ${cell.lod}` : 'LOD -'}
                              {' · '}
                              {cell?.loi ? `LOI ${cell.loi}` : 'LOI -'}
                            </span>
                            {!cell?.deliverable_id && (
                              <span className="inline-flex items-center gap-0.5 text-[11px] opacity-70 group-hover:opacity-100">
                                <Plus size={10} /> {t('common.add', { defaultValue: 'Add' })}
                              </span>
                            )}
                          </button>
                        </td>
                      );
                    })}
                    <td className="px-3 py-2 align-middle text-right">
                      <div className="inline-flex items-center gap-1 opacity-60 transition group-hover/row:opacity-100">
                        <button
                          type="button"
                          onClick={() => setReqEditor({ open: true, row })}
                          aria-label={t('requirements.matrix.row_edit', { defaultValue: 'Edit requirement' })}
                          title={t('requirements.matrix.row_edit', { defaultValue: 'Edit requirement' })}
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-secondary hover:bg-surface-secondary hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => setReqToDelete(row)}
                          aria-label={t('requirements.matrix.row_delete', { defaultValue: 'Delete requirement' })}
                          title={t('requirements.matrix.row_delete', { defaultValue: 'Delete requirement' })}
                          className="inline-flex h-7 w-7 items-center justify-center rounded-md text-content-secondary hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue dark:hover:bg-red-900/30"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Modals */}
      <RequirementEditor
        state={reqEditor}
        setId={targetSetId}
        onClose={() => setReqEditor({ open: false, row: null })}
        onSaved={refresh}
      />
      <SetEditor
        state={setEditor}
        projectId={projectId}
        onClose={() => setSetEditor({ open: false, set: null })}
        onSaved={(created) => {
          if (created) setSetFilter(created.id);
          refresh();
        }}
      />
      <CellEditor
        state={cellEditor}
        projectId={projectId}
        onClose={() => setCellEditor({ open: false, row: null, deliverableType: '', cell: null })}
        onSaved={refresh}
      />

      {/* Confirm dialogs */}
      <ConfirmDialog
        open={reqToDelete != null}
        onCancel={() => setReqToDelete(null)}
        onConfirm={() => reqToDelete && deleteReq.mutate(reqToDelete)}
        loading={deleteReq.isPending}
        title={t('requirements.matrix.row_delete', { defaultValue: 'Delete requirement' })}
        message={t('requirements.matrix.confirm_delete_req', {
          defaultValue: 'Delete the requirement "{{name}}" and all its deliverables? This cannot be undone.',
          name: reqToDelete ? `${reqToDelete.entity}.${reqToDelete.attribute}` : '',
        })}
      />
      <ConfirmDialog
        open={setToDelete != null}
        onCancel={() => setSetToDelete(null)}
        onConfirm={() => setToDelete && deleteSet.mutate(setToDelete)}
        loading={deleteSet.isPending}
        title={t('requirements.matrix.delete_set', { defaultValue: 'Delete set' })}
        message={t('requirements.matrix.confirm_delete_set', {
          defaultValue: 'Delete the set "{{name}}" with all its requirements and deliverables? This cannot be undone.',
          name: setToDelete?.name ?? '',
        })}
      />
    </div>
  );
}

// Keep the default export so the lazy loader in App.tsx can map it
// either way (named or default).
export default RequirementsMatrixPage;

// Used by lazy-loader checks — keeps the reference live as a sanity touch
// of every exported binding so dead-code analysers don't drop the named
// helpers (they are imported by the modal sub-component).
export type { Deliverable };
