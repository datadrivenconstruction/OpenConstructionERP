// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Request types are data: the client helpers that the picker, the filter,
 * the stats strip and the create form share, and the URLs they call.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPatch = vi.fn();
const apiDelete = vi.fn();

vi.mock('@/shared/lib/api', () => ({
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPost: (...args: unknown[]) => apiPost(...args),
  apiPatch: (...args: unknown[]) => apiPatch(...args),
  apiDelete: (...args: unknown[]) => apiDelete(...args),
}));

import {
  DEFAULT_REQUEST_TYPE,
  REQUIRED_FIELD_CHOICES,
  createRequestType,
  deleteRequestType,
  fetchRegisterValidation,
  fetchRequestTypePresets,
  fetchRequestTypes,
  loadRequestTypePreset,
  localizedText,
  missingRequiredFields,
  requestTypeLabel,
  requestTypeName,
  sampleNumber,
  selectableTypes,
  updateRequestType,
  type RequestType,
  type RequiredFieldValues,
} from '../requestTypes';

function type(overrides: Partial<RequestType>): RequestType {
  return {
    id: 'id-' + (overrides.code ?? 'RFI'),
    project_id: 'p1',
    code: 'RFI',
    name: 'Request for Information',
    name_i18n: { en: 'Request for Information', de: 'Informationsanfrage' },
    description_i18n: {},
    number_prefix: 'RFI',
    number_digits: 3,
    default_response_days: 14,
    response_days: 14,
    required_fields: [],
    default_route_id: null,
    is_active: true,
    is_builtin: false,
    sort_order: 0,
    preset_code: null,
    request_count: 0,
    ...overrides,
  };
}

const EMPTY: RequiredFieldValues = {
  assigned_to: '',
  response_due_date: '',
  discipline: '',
  priority: '',
  linked_drawing_ids: [],
  cost_impact_value: '',
  schedule_impact_days: '',
};

describe('localizedText', () => {
  const names = { en: 'Technical Query', de: 'Technische Anfrage', 'pt-BR': 'Consulta técnica' };

  it('reads the exact tag first, then the base language, then English', () => {
    expect(localizedText(names, 'pt-BR', 'TQ')).toBe('Consulta técnica');
    expect(localizedText(names, 'de-AT', 'TQ')).toBe('Technische Anfrage');
    expect(localizedText(names, 'de_CH', 'TQ')).toBe('Technische Anfrage');
    expect(localizedText(names, 'ja', 'TQ')).toBe('Technical Query');
  });

  it('falls back when the catalogue carries no text at all', () => {
    expect(localizedText({}, 'de', 'TQ')).toBe('TQ');
    expect(localizedText(null, 'de', 'TQ')).toBe('TQ');
  });
});

describe('type names and labels', () => {
  const types = [
    type({ code: 'RFI' }),
    type({ code: 'TQ', name: 'Technical Query', name_i18n: { en: 'Technical Query', de: 'Technische Anfrage' } }),
  ];

  it('names a type in the reader language from the catalogue, not the locale files', () => {
    expect(requestTypeName(types[1]!, 'de')).toBe('Technische Anfrage');
    expect(requestTypeName(types[1]!, 'fr')).toBe('Technical Query');
  });

  it('labels a code the catalogue no longer holds with the bare code', () => {
    expect(requestTypeLabel(types, 'TQ', 'de')).toBe('Technische Anfrage');
    expect(requestTypeLabel(types, 'GONE', 'de')).toBe('GONE');
  });

  it('reads a request without a type as the default RFI type', () => {
    expect(DEFAULT_REQUEST_TYPE).toBe('RFI');
    expect(requestTypeLabel(types, null, 'de')).toBe('Informationsanfrage');
  });
});

describe('selectableTypes', () => {
  it('offers active types only, in catalogue order then by code', () => {
    const picked = selectableTypes([
      type({ code: 'SQ', sort_order: 2 }),
      type({ code: 'RFI', sort_order: 0 }),
      type({ code: 'OLD', sort_order: 1, is_active: false }),
      type({ code: 'DQ', sort_order: 2 }),
    ]);
    expect(picked.map((t) => t.code)).toEqual(['RFI', 'DQ', 'SQ']);
  });
});

describe('missingRequiredFields', () => {
  it('lists what the type requires and the form leaves empty, in the type order', () => {
    const tq = type({ code: 'TQ', required_fields: ['assigned_to', 'discipline', 'response_due_date'] });
    expect(missingRequiredFields(tq, EMPTY)).toEqual(['assigned_to', 'discipline', 'response_due_date']);
    expect(
      missingRequiredFields(tq, { ...EMPTY, assigned_to: 'u1', discipline: '  ', response_due_date: '2026-11-02' }),
    ).toEqual(['discipline']);
  });

  it('treats an empty drawing list as missing and a filled one as present', () => {
    const fq = type({ code: 'FQ', required_fields: ['linked_drawing_ids'] });
    expect(missingRequiredFields(fq, EMPTY)).toEqual(['linked_drawing_ids']);
    expect(missingRequiredFields(fq, { ...EMPTY, linked_drawing_ids: ['d1'] })).toEqual([]);
  });

  it('requires nothing of a type with no requirements or of no type at all', () => {
    expect(missingRequiredFields(type({}), EMPTY)).toEqual([]);
    expect(missingRequiredFields(undefined, EMPTY)).toEqual([]);
  });

  it('knows every field a type may require', () => {
    for (const field of REQUIRED_FIELD_CHOICES) {
      expect(Object.keys(EMPTY)).toContain(field);
    }
  });
});

describe('sampleNumber', () => {
  it('shows the numbering of the type', () => {
    expect(sampleNumber({ number_prefix: 'TQ', number_digits: 4 })).toBe('TQ-0001');
    expect(sampleNumber({ number_prefix: 'RFI', number_digits: 3 })).toBe('RFI-001');
  });
});

describe('request type API', () => {
  beforeEach(() => {
    apiGet.mockReset().mockResolvedValue({ items: [], total: 0 });
    apiPost.mockReset().mockResolvedValue({});
    apiPatch.mockReset().mockResolvedValue({});
    apiDelete.mockReset().mockResolvedValue(undefined);
  });

  it('reads the catalogue of one project', async () => {
    await fetchRequestTypes('p 1');
    expect(apiGet).toHaveBeenCalledWith('/v1/rfi/types/?project_id=p%201');
  });

  it('reads the presets and unwraps the page', async () => {
    apiGet.mockResolvedValueOnce({ items: [{ code: 'epc_oil_gas' }], total: 1 });
    const presets = await fetchRequestTypePresets();
    expect(apiGet).toHaveBeenCalledWith('/v1/rfi/types/presets/');
    expect(presets.map((p) => p.code)).toEqual(['epc_oil_gas']);
  });

  it('loads a preset into a project', async () => {
    await loadRequestTypePreset('general_construction', 'p1');
    expect(apiPost).toHaveBeenCalledWith('/v1/rfi/types/presets/general_construction/load/?project_id=p1');
  });

  it('creates, updates and deletes a type', async () => {
    const payload = { project_id: 'p1', code: 'TQ', name_i18n: { en: 'Technical Query' }, number_prefix: 'TQ' };
    await createRequestType(payload);
    expect(apiPost).toHaveBeenCalledWith('/v1/rfi/types/', payload);
    await updateRequestType('t1', { is_active: false });
    expect(apiPatch).toHaveBeenCalledWith('/v1/rfi/types/t1', { is_active: false });
    await deleteRequestType('t1');
    expect(apiDelete).toHaveBeenCalledWith('/v1/rfi/types/t1');
  });

  it('runs the register check of one project', async () => {
    await fetchRegisterValidation('p1');
    expect(apiGet).toHaveBeenCalledWith('/v1/rfi/validation/?project_id=p1');
  });
});
