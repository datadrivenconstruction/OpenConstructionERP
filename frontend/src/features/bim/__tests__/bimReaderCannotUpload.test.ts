// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A viewer opens models but is never offered an upload, a re-process or a
// delete the server would refuse with 403. Read from the page source, the way
// the other BIM page contracts are, because the page needs a WebGL viewer to render.
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { roleHasPermission } from '@/shared/lib/permissionGates';

const CANDIDATES = [
  resolve(process.cwd(), 'src/features/bim/BIMPage.tsx'),
  resolve(process.cwd(), 'frontend/src/features/bim/BIMPage.tsx'),
];
const PAGE_PATH = CANDIDATES.find(existsSync);
if (!PAGE_PATH) throw new Error(`cannot find BIMPage.tsx, looked in ${CANDIDATES.join(' and ')}`);
const PAGE = readFileSync(PAGE_PATH, 'utf8');

describe('BIM model permissions in the UI', () => {
  it('gives upload to editors and delete to managers, matching the server', () => {
    expect(roleHasPermission('viewer', 'bim.create')).toBe(false);
    expect(roleHasPermission('editor', 'bim.create')).toBe(true);
    expect(roleHasPermission('editor', 'bim.delete')).toBe(false);
    expect(roleHasPermission('manager', 'bim.delete')).toBe(true);
  });

  it('offers the filmstrip add tile and the upload panel only with bim.create', () => {
    expect(PAGE).toContain('onUpload={canUploadModels ? () => setUploadOpen(true) : undefined}');
    expect(PAGE).toContain('{uploadOpen && canUploadModels && (');
    expect(PAGE).toMatch(/\{onUpload && \(\s*<button\s+onClick=\{onUpload\}/);
  });

  it('hides retry, install and re-upload on a failed model for a reader and says why', () => {
    expect(PAGE).toContain('canUpload={canUploadModels}');
    expect(PAGE).toContain('canDelete={canDeleteModels}');
    expect(PAGE).toMatch(/const showRetryButton = canUpload && /);
    expect(PAGE).toMatch(/const showInstallButton =\s+canUpload/);
    expect(PAGE).toContain('data-testid="bim-overlay-read-only"');
  });

  it('replaces the landing upload card with a read-only note for a reader', () => {
    expect(PAGE).toContain("const canUpload = useHasPermission('bim.create');");
    expect(PAGE).toContain('{canUpload ? (');
    expect(PAGE).toContain('data-testid="bim-landing-read-only"');
  });
});
