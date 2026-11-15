// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Editable estimate templates: types and calls. Built-in templates are read only. */

import { apiDelete, apiGet, apiPost, apiPut } from '@/shared/lib/api';

export interface TemplatePosition {
  ordinal: string;
  description: string;
  unit: string;
  /** Fixed default quantity, blank when the estimator fills it in. */
  quantity: string | null;
  /** Multiplied by the floor area when a bill is made; blank for none. */
  qty_factor: string | null;
  /** Optional unit rate. */
  rate: string | null;
  classification: Record<string, string>;
}

export interface TemplateSection {
  ordinal: string;
  description: string;
  classification: Record<string, string>;
  positions: TemplatePosition[];
}

export interface TemplateMarkup {
  name: string;
  markup_type: string;
  category: string;
  percentage: string;
  fixed_amount: string;
  apply_to: string;
}

export interface TemplateIssue {
  rule_id: string;
  severity: 'warning';
  /** Zero based indexes of the offending row. */
  path: { section?: number; position?: number };
  params: Record<string, unknown>;
}

export interface TemplateDetail {
  id: string;
  builtin: boolean;
  name: string;
  description: string;
  icon: string;
  classification_standard: string;
  origin: string;
  copied_from: string | null;
  sections: TemplateSection[];
  markups: TemplateMarkup[];
  warnings: TemplateIssue[];
}

/** Body of create, update and validate. */
export interface TemplateWriteBody {
  name: string;
  description: string;
  icon: string;
  classification_standard: string;
  sections: TemplateSection[];
  markups: TemplateMarkup[];
}

export interface TemplateFromBoqBody {
  boq_id: string;
  name?: string;
  description?: string;
  classification_standard?: string;
  keep_quantities: boolean;
  keep_rates: boolean;
  include_markups: boolean;
  renumber: boolean;
}

export const templatesApi = {
  get: (id: string) => apiGet<TemplateDetail>(`/v1/boq/boqs/templates/${id}/`),
  create: (body: TemplateWriteBody) => apiPost<TemplateDetail>(`/v1/boq/boqs/templates/`, body),
  update: (id: string, body: TemplateWriteBody) => apiPut<TemplateDetail>(`/v1/boq/boqs/templates/${id}/`, body),
  remove: (id: string) => apiDelete(`/v1/boq/boqs/templates/${id}/`),
  duplicate: (id: string) => apiPost<TemplateDetail>(`/v1/boq/boqs/templates/${id}/duplicate/`, {}),
  validate: (body: TemplateWriteBody) => apiPost<TemplateIssue[]>(`/v1/boq/boqs/templates/validate/`, body),
  fromBoq: (body: TemplateFromBoqBody) => apiPost<TemplateDetail>(`/v1/boq/boqs/templates/from-boq/`, body),
};

export function toWriteBody(t: TemplateDetail | TemplateWriteBody): TemplateWriteBody {
  return {
    name: t.name,
    description: t.description,
    icon: t.icon,
    classification_standard: t.classification_standard,
    sections: t.sections,
    markups: t.markups,
  };
}

/** Section and position numbers as `01`, `01.0010`, in list order. */
export function renumberSections(sections: TemplateSection[]): TemplateSection[] {
  return sections.map((sec, si) => {
    const sn = String(si + 1).padStart(2, '0');
    return {
      ...sec,
      ordinal: sn,
      positions: sec.positions.map((p, pi) => ({
        ...p,
        ordinal: `${sn}.${String((pi + 1) * 10).padStart(4, '0')}`,
      })),
    };
  });
}

/** Moves item `from` to index `to`; returns the same list when either is out of range. */
export function moveItem<T>(list: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list;
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item as T);
  return next;
}
