import { describe, expect, it } from 'vitest';
import { primaryModule } from './kindModule';
import type { FileRow } from './types';

function file(overrides: Partial<FileRow>): FileRow {
  return {
    id: 'file-id',
    kind: 'document',
    name: 'abc.pdf',
    project_id: 'project-id',
    size_bytes: 1,
    mime_type: 'application/pdf',
    extension: 'pdf',
    modified_at: null,
    physical_path: '',
    relative_path: '',
    storage_backend: 'local',
    download_url: null,
    preview_url: null,
    thumbnail_url: null,
    discipline: null,
    category: 'drawing',
    extra: {},
    ...overrides,
  };
}

describe('file manager module routing', () => {
  it('opens ordinary Project Files PDFs in the document measurement namespace', () => {
    const row = file({ id: 'project-file-doc-id', name: 'abc.pdf' });
    const target = primaryModule(row.kind, row.extension);

    expect(target.route(row.project_id, row.id, row)).toBe(
      '/takeoff?tab=measurements&doc=project-file-doc-id&source=document&name=abc.pdf',
    );
  });

  it('opens takeoff mirrors in the original Takeoff measurement namespace', () => {
    const row = file({
      id: 'project-file-mirror-id',
      name: 'takeoff-upload.pdf',
      extra: {
        source_module: 'takeoff',
        source_id: 'takeoff-doc-id',
      },
    });
    const target = primaryModule(row.kind, row.extension);

    expect(target.route(row.project_id, row.id, row)).toBe(
      '/takeoff?tab=measurements&doc=takeoff-doc-id&name=takeoff-upload.pdf',
    );
  });
});
