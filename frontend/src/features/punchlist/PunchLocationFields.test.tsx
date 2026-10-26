import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { listAssets } from '@/features/assets/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { updatePunchItem, type PunchItem } from './api';
import { PunchAssetField, PunchLocationAssignment, locationOptions } from './PunchLocationFields';

vi.mock('@/features/assets/api', () => ({ listAssets: vi.fn() }));
vi.mock('./api', () => ({ updatePunchItem: vi.fn() }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

function wrap(child: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{child}</QueryClientProvider>);
}

beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({ userRole: 'editor' });
  vi.mocked(listAssets).mockResolvedValue({
    items: [{ id: 'a1', stable_id: 'S1', name: 'Pump P-1', storey: 'L2' }], total: 1, offset: 0, limit: 100,
  } as never);
  vi.mocked(updatePunchItem).mockResolvedValue({} as PunchItem);
});

describe('punch asset field', () => {
  it('offers register assets and reports the chosen one with its name', async () => {
    const onChange = vi.fn();
    wrap(<PunchAssetField projectId="p1" value={null} onChange={onChange} />);
    await screen.findByRole('option', { name: /Pump P-1/ });
    fireEvent.change(screen.getByLabelText('punch.field_asset'), { target: { value: 'a1' } });
    expect(onChange).toHaveBeenCalledWith({ asset_kind: 'bim_element', asset_ref: 'a1', asset_label: 'Pump P-1' });
  });

  it('takes a free tag for an asset nobody modelled and clears when emptied', async () => {
    const onChange = vi.fn();
    wrap(<PunchAssetField projectId="p1" value={null} onChange={onChange} />);
    await screen.findByRole('option', { name: /Pump P-1/ });
    fireEvent.change(screen.getByLabelText('punch.field_asset'), { target: { value: 'tag' } });
    const input = screen.getByLabelText('punch.asset_tag');
    fireEvent.change(input, { target: { value: ' FAN-7 ' } });
    expect(onChange).toHaveBeenLastCalledWith({ asset_kind: 'tag', asset_ref: 'FAN-7', asset_label: 'FAN-7' });
  });

  it('clears the link when a typed tag is emptied', async () => {
    const onChange = vi.fn();
    wrap(<PunchAssetField projectId="p1" onChange={onChange}
      value={{ asset_kind: 'tag', asset_ref: 'FAN-7', asset_label: 'FAN-7' }} />);
    fireEvent.change(await screen.findByLabelText('punch.asset_tag'), { target: { value: '' } });
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it('keeps showing a linked asset that left the first register page', async () => {
    wrap(<PunchAssetField projectId="p1" onChange={vi.fn()}
      value={{ asset_kind: 'bim_element', asset_ref: 'gone', asset_label: 'Old boiler' }} />);
    expect(await screen.findByRole('option', { name: 'Old boiler' })).toBeInTheDocument();
    expect(screen.getByLabelText('punch.field_asset')).toHaveValue('gone');
  });
});

describe('punch location on an existing item', () => {
  const item = { id: 'i1', project_id: 'p1', area: 'Level 2', asset_ref: null } as PunchItem;

  it('saves a changed area on blur and clears it with null', async () => {
    const onSaved = vi.fn();
    wrap(<PunchLocationAssignment item={item} onSaved={onSaved} />);
    const area = screen.getByLabelText('punch.field_location');
    fireEvent.change(area, { target: { value: ' Level 3 ' } });
    fireEvent.blur(area);
    await waitFor(() => expect(updatePunchItem).toHaveBeenCalledWith('i1', { area: 'Level 3' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    fireEvent.change(area, { target: { value: '' } });
    fireEvent.blur(area);
    await waitFor(() => expect(updatePunchItem).toHaveBeenLastCalledWith('i1', { area: null }));
  });

  it('does not save an unchanged area', async () => {
    wrap(<PunchLocationAssignment item={item} onSaved={vi.fn()} />);
    fireEvent.blur(screen.getByLabelText('punch.field_location'));
    await screen.findByRole('option', { name: /Pump P-1/ });
    expect(updatePunchItem).not.toHaveBeenCalled();
  });

  it('unlinks the asset with an explicit null ref', async () => {
    const linked = { ...item, asset_kind: 'bim_element', asset_ref: 'a1', asset_label: 'Pump P-1' } as PunchItem;
    wrap(<PunchLocationAssignment item={linked} onSaved={vi.fn()} />);
    await screen.findByRole('option', { name: /Pump P-1/ });
    fireEvent.change(screen.getByLabelText('punch.field_asset'), { target: { value: '' } });
    await waitFor(() => expect(updatePunchItem).toHaveBeenCalledWith('i1', { asset_ref: null }));
  });

  it('is read-only for a viewer', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    wrap(<PunchLocationAssignment item={item} onSaved={vi.fn()} />);
    expect(screen.getByLabelText('punch.field_location')).toBeDisabled();
    await screen.findByRole('option', { name: /Pump P-1/ });
    expect(screen.getByLabelText('punch.field_asset')).toBeDisabled();
  });
});

describe('locationOptions', () => {
  it('lists distinct sorted areas and assets, keeping the active filter values', () => {
    const out = locationOptions(
      [
        { area: 'B', asset_ref: 'x', asset_label: 'Zed' },
        { area: 'A', asset_ref: 'x', asset_label: 'Zed' },
        { area: null, asset_ref: 'y', asset_label: null },
      ],
      'C',
      'gone',
    );
    expect(out.areas).toEqual(['A', 'B', 'C']);
    expect(out.assets).toEqual([
      { ref: 'gone', label: 'gone' },
      { ref: 'y', label: 'y' },
      { ref: 'x', label: 'Zed' },
    ]);
  });
});
