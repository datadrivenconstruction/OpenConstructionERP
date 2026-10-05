// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { PERMISSION_MIN_ROLE, roleHasPermission, type GatedPermission } from './permissionGates';

describe('roleHasPermission', () => {
  it('refuses the viewer every gated permission, since each needs more than a viewer', () => {
    for (const permission of Object.keys(PERMISSION_MIN_ROLE) as GatedPermission[]) {
      expect(roleHasPermission('viewer', permission)).toBe(false);
    }
  });

  it('treats an absent role and an unknown role as a refusal', () => {
    expect(roleHasPermission(null, 'ai.estimate')).toBe(false);
    expect(roleHasPermission(undefined, 'ai.estimate')).toBe(false);
    expect(roleHasPermission('stranger', 'ai.estimate')).toBe(false);
  });

  it('keeps the user directory at manager, so an editor does not fire the call', () => {
    expect(roleHasPermission('editor', 'users.list')).toBe(false);
    expect(roleHasPermission('manager', 'users.list')).toBe(true);
    expect(roleHasPermission('admin', 'users.list')).toBe(true);
  });

  it('resolves aliases the way the backend does', () => {
    // estimator is an editor alias, readonly a viewer alias, owner an admin alias.
    expect(roleHasPermission('estimator', 'estimate_basis.generate')).toBe(true);
    expect(roleHasPermission('readonly', 'estimate_basis.generate')).toBe(false);
    expect(roleHasPermission('owner', 'payroll.read')).toBe(true);
  });

  it('lets an editor change a payment plan and raise its claim, and keeps deleting at manager', () => {
    // Mirrors contracts/permissions.py: create, update and submit_claim are
    // EDITOR, delete is MANAGER.
    for (const permission of ['contracts.create', 'contracts.update', 'contracts.submit_claim'] as const) {
      expect(roleHasPermission('viewer', permission)).toBe(false);
      expect(roleHasPermission('editor', permission)).toBe(true);
    }
    expect(roleHasPermission('editor', 'contracts.delete')).toBe(false);
    expect(roleHasPermission('manager', 'contracts.delete')).toBe(true);
  });

  it('never lets a field role through, those rank below the viewer', () => {
    expect(roleHasPermission('site_foreman', 'takeoff.update')).toBe(false);
    expect(roleHasPermission('field_worker', 'takeoff.update')).toBe(false);
  });
});
