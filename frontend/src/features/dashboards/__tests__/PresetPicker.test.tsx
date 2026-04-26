// @ts-nocheck
/**
 * Tests for PresetPicker (T05).
 *
 * Covers:
 *   - opening the dropdown lists "My presets" + "Shared collections"
 *   - clicking "Save current as preset…" opens the save modal
 *   - submitting the modal calls createDashboardPreset with the
 *     captured snapshot + form fields
 *   - selecting a preset calls onSelect
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    listDashboardPresets: vi.fn(),
    createDashboardPreset: vi.fn(),
  };
});

import { createDashboardPreset, listDashboardPresets } from '../api';
import { PresetPicker } from '../PresetPicker';

const samplePresets = {
  total: 3,
  items: [
    {
      id: 'p1',
      tenant_id: 't',
      project_id: 'proj-1',
      owner_id: 'u1',
      name: 'My weekly view',
      description: 'Walls + doors',
      kind: 'preset',
      config_json: {},
      shared_with_project: false,
      created_at: '2026-04-26T00:00:00Z',
      updated_at: '2026-04-26T00:00:00Z',
    },
    {
      id: 'c1',
      tenant_id: 't',
      project_id: 'proj-1',
      owner_id: 'u2',
      name: 'Project compliance',
      description: 'Shared template',
      kind: 'collection',
      config_json: {},
      shared_with_project: true,
      created_at: '2026-04-26T00:00:00Z',
      updated_at: '2026-04-26T00:00:00Z',
    },
    {
      id: 'c2',
      tenant_id: 't',
      project_id: 'proj-1',
      owner_id: 'u3',
      name: 'Subcontractor scope',
      description: null,
      kind: 'collection',
      config_json: {},
      shared_with_project: true,
      created_at: '2026-04-26T00:00:00Z',
      updated_at: '2026-04-26T00:00:00Z',
    },
  ],
};

function withQueryClient(child: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={qc}>{child}</QueryClientProvider>;
}

beforeEach(() => {
  (listDashboardPresets as ReturnType<typeof vi.fn>).mockReset();
  (listDashboardPresets as ReturnType<typeof vi.fn>).mockResolvedValue(
    samplePresets,
  );
  (createDashboardPreset as ReturnType<typeof vi.fn>).mockReset();
  (createDashboardPreset as ReturnType<typeof vi.fn>).mockResolvedValue({
    ...samplePresets.items[0],
    id: 'new-preset',
    name: 'New from test',
  });
});

afterEach(() => {
  cleanup();
});

describe('PresetPicker', () => {
  it('renders a trigger button by default', () => {
    render(
      withQueryClient(
        <PresetPicker projectId="proj-1" snapshot={() => ({})} />,
      ),
    );
    expect(screen.getByTestId('preset-picker-trigger')).toBeInTheDocument();
  });

  it('opens dropdown listing my presets and shared collections', async () => {
    render(
      withQueryClient(
        <PresetPicker projectId="proj-1" snapshot={() => ({})} />,
      ),
    );
    fireEvent.click(screen.getByTestId('preset-picker-trigger'));

    // Wait for the data fetch to land.
    await waitFor(() => {
      expect(screen.getByTestId('my-preset-p1')).toBeInTheDocument();
    });

    expect(screen.getByTestId('my-preset-p1')).toHaveTextContent(
      'My weekly view',
    );
    expect(screen.getByTestId('shared-collection-c1')).toHaveTextContent(
      'Project compliance',
    );
    expect(screen.getByTestId('shared-collection-c2')).toHaveTextContent(
      'Subcontractor scope',
    );
  });

  it('selecting a preset fires onSelect and closes the dropdown', async () => {
    const onSelect = vi.fn();
    render(
      withQueryClient(
        <PresetPicker
          projectId="proj-1"
          snapshot={() => ({})}
          onSelect={onSelect}
        />,
      ),
    );
    fireEvent.click(screen.getByTestId('preset-picker-trigger'));

    await waitFor(() => {
      expect(screen.getByTestId('my-preset-p1')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('my-preset-p1'));

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0].id).toBe('p1');
    // Dropdown closes after select.
    expect(screen.queryByTestId('preset-picker-dropdown')).not.toBeInTheDocument();
  });

  it('opens the save modal when "Save current as preset…" is clicked', async () => {
    render(
      withQueryClient(
        <PresetPicker projectId="proj-1" snapshot={() => ({ a: 1 })} />,
      ),
    );

    fireEvent.click(screen.getByTestId('preset-picker-trigger'));
    await waitFor(() => {
      expect(screen.getByTestId('preset-picker-dropdown')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('preset-picker-save-current'));

    await waitFor(() => {
      expect(screen.getByTestId('preset-save-modal')).toBeInTheDocument();
    });
    expect(screen.getByTestId('preset-save-name')).toBeInTheDocument();
  });

  it('submitting the save modal calls createDashboardPreset with the snapshot', async () => {
    const captured = { x: 'y' };
    render(
      withQueryClient(
        <PresetPicker projectId="proj-1" snapshot={() => captured} />,
      ),
    );

    fireEvent.click(screen.getByTestId('preset-picker-trigger'));
    await waitFor(() =>
      expect(screen.getByTestId('preset-picker-dropdown')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('preset-picker-save-current'));

    await waitFor(() =>
      expect(screen.getByTestId('preset-save-modal')).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByTestId('preset-save-name'), {
      target: { value: 'Test preset' },
    });
    fireEvent.change(screen.getByTestId('preset-save-description'), {
      target: { value: 'From a vitest run' },
    });
    fireEvent.click(screen.getByTestId('preset-save-kind-shared'));

    fireEvent.click(screen.getByTestId('preset-save-submit'));

    await waitFor(() => {
      expect(createDashboardPreset).toHaveBeenCalledTimes(1);
    });

    const [arg] = (createDashboardPreset as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(arg.name).toBe('Test preset');
    expect(arg.description).toBe('From a vitest run');
    expect(arg.kind).toBe('collection');
    expect(arg.shared_with_project).toBe(true);
    expect(arg.project_id).toBe('proj-1');
    expect(arg.config_json).toEqual(captured);
  });

  it('submit is disabled when name is empty', async () => {
    render(
      withQueryClient(
        <PresetPicker projectId="proj-1" snapshot={() => ({})} />,
      ),
    );
    fireEvent.click(screen.getByTestId('preset-picker-trigger'));
    await waitFor(() =>
      expect(screen.getByTestId('preset-picker-dropdown')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('preset-picker-save-current'));
    await waitFor(() =>
      expect(screen.getByTestId('preset-save-modal')).toBeInTheDocument(),
    );

    expect(screen.getByTestId('preset-save-submit')).toBeDisabled();
  });
});
