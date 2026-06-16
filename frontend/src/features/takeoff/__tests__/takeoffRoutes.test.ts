import { describe, expect, it } from 'vitest';
import {
  buildProjectDocumentTakeoffUrl,
  buildTakeoffMeasurementUrl,
  parseMeasurementDocumentSource,
  resolveProjectDocumentTakeoffTarget,
} from '../takeoffRoutes';

describe('takeoff measurement routes', () => {
  it('routes ordinary Project Files PDFs with source=document and the Project Files UUID', () => {
    const url = buildProjectDocumentTakeoffUrl({
      id: 'project-file-doc-id',
      name: 'abc.pdf',
    });

    expect(url).toBe('/takeoff?tab=measurements&doc=project-file-doc-id&source=document&name=abc.pdf');
  });

  it('routes Project Files mirrors back to the original Takeoff UUID namespace', () => {
    const target = resolveProjectDocumentTakeoffTarget({
      id: 'project-file-mirror-id',
      name: 'takeoff-upload.pdf',
      metadata: {
        source_module: 'takeoff',
        source_id: 'takeoff-doc-id',
      },
    });

    expect(target).toEqual({
      documentId: 'takeoff-doc-id',
      documentName: 'takeoff-upload.pdf',
      documentSource: 'takeoff',
    });
    expect(buildTakeoffMeasurementUrl(target)).toBe(
      '/takeoff?tab=measurements&doc=takeoff-doc-id&name=takeoff-upload.pdf',
    );
  });

  it('builds focused measurement links without the legacy focus parameter', () => {
    expect(
      buildTakeoffMeasurementUrl({
        documentId: 'document-id',
        documentSource: 'document',
        measurementId: 'measurement-id',
        page: 3,
      }),
    ).toBe('/takeoff?tab=measurements&doc=document-id&source=document&measurementId=measurement-id&page=3');
  });

  it('parses measurement document source metadata defensively', () => {
    expect(parseMeasurementDocumentSource('document')).toBe('document');
    expect(parseMeasurementDocumentSource('takeoff')).toBe('takeoff');
    expect(parseMeasurementDocumentSource('other')).toBeNull();
    expect(parseMeasurementDocumentSource(undefined)).toBeNull();
  });
});
