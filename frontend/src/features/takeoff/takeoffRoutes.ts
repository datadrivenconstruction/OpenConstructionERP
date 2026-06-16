export type MeasurementDocumentSource = 'takeoff' | 'document';

export function parseMeasurementDocumentSource(value: unknown): MeasurementDocumentSource | null {
  return value === 'document' || value === 'takeoff' ? value : null;
}

export interface TakeoffMeasurementTarget {
  documentId?: string | null;
  documentName?: string | null;
  documentSource?: MeasurementDocumentSource | null;
  measurementId?: string | null;
  page?: number | null;
}

export interface ProjectDocumentTakeoffLink {
  id: string;
  name: string;
  metadata?: {
    source_module?: unknown;
    source_id?: unknown;
  } | null;
}

function cleanString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

export function resolveProjectDocumentTakeoffTarget(
  doc: ProjectDocumentTakeoffLink,
): TakeoffMeasurementTarget {
  const sourceModule = cleanString(doc.metadata?.source_module);
  const sourceId = cleanString(doc.metadata?.source_id);
  if (sourceModule === 'takeoff' && sourceId) {
    return {
      documentId: sourceId,
      documentName: doc.name,
      documentSource: 'takeoff',
    };
  }
  return {
    documentId: doc.id,
    documentName: doc.name,
    documentSource: 'document',
  };
}

export function buildTakeoffMeasurementUrl(target: TakeoffMeasurementTarget): string {
  const params = new URLSearchParams();
  params.set('tab', 'measurements');
  if (target.documentId) params.set('doc', target.documentId);
  if (target.documentSource === 'document') params.set('source', 'document');
  if (target.documentName) params.set('name', target.documentName);
  if (target.measurementId) params.set('measurementId', target.measurementId);
  if (target.page) params.set('page', String(target.page));
  return `/takeoff?${params.toString()}`;
}

export function buildProjectDocumentTakeoffUrl(doc: ProjectDocumentTakeoffLink): string {
  return buildTakeoffMeasurementUrl(resolveProjectDocumentTakeoffTarget(doc));
}
