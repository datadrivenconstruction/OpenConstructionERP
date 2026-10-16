// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A viewer could start an estimate it could never delete again, because
// `boq.create` was granted to viewers while `boq.delete` needs an editor. The
// backend now asks for editor on create; the new-estimate form follows it and
// disables its submit button for a viewer, with the reason in the tooltip,
// instead of firing a call the role cannot pass.
//
// The test setup's i18n mock renders each label's English defaultValue.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: () => Promise.resolve([{ id: 'proj-a', name: 'Alpha Tower' }]),
}));

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return { ...actual, boqApi: { ...actual.boqApi, create: vi.fn() } };
});

import { CreateBOQModal } from '../CreateBOQPage';
import { boqApi } from '../api';
import { roleHasPermission } from '@/shared/lib/permissionGates';
import { useAuthStore } from '@/stores/useAuthStore';

function renderModal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CreateBOQModal open onClose={() => {}} defaultProjectId="proj-a" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const submit = async () => {
  const actions = await screen.findByTestId('create-boq-actions');
  return actions.querySelector('button[type="submit"]') as HTMLButtonElement;
};

afterEach(() => {
  cleanup();
  useAuthStore.setState({ userRole: null });
});

describe('boq.create gate', () => {
  it('mirrors the backend: editor and above, never a viewer', () => {
    expect(roleHasPermission('viewer', 'boq.create')).toBe(false);
    expect(roleHasPermission(null, 'boq.create')).toBe(false);
    expect(roleHasPermission('editor', 'boq.create')).toBe(true);
    expect(roleHasPermission('manager', 'boq.create')).toBe(true);
    expect(roleHasPermission('admin', 'boq.create')).toBe(true);
  });
});

describe('New estimate form', () => {
  it('is disabled for a viewer and says why, without firing the call', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderModal();
    const button = await submit();
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', 'Creating an estimate needs the editor role.');
    fireEvent.submit(button.closest('form')!);
    expect(vi.mocked(boqApi.create)).not.toHaveBeenCalled();
  });

  it('is enabled for an editor, with no tooltip', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    renderModal();
    const button = await submit();
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute('title');
  });
});
