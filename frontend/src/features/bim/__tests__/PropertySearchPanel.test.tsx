// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BIM property search panel: what it sends and what it does with the answer.
 *
 * Pins the four things a restoration estimator hit on a Revit model:
 *   - the property list is searchable and shows the parameter as Revit names
 *     it ("Phase Created"), not the lowercased key plus a "(string)" suffix;
 *   - the query uses the column KEY, so the server finds the column;
 *   - Parquet hits (Revit ElementIds) are translated to the element ids the
 *     viewer isolates by, instead of being forwarded verbatim;
 *   - zero matches say so and leave the view alone, instead of silently
 *     showing the whole model as if no filter had run;
 *   - "=" / "!=" offer the values present in the model, and free text still works.
 */
import type { ComponentProps } from 'react';
import { afterEach, describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import PropertySearchPanel from '../PropertySearchPanel';
import * as api from '../api';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

vi.mock('../api', async (orig) => {
  const actual = await orig<typeof import('../api')>();
  return {
    ...actual,
    fetchBIMDataframeSchema: vi.fn(),
    queryBIMDataframe: vi.fn(),
    fetchBIMDataframeColumnValues: vi.fn(),
    fetchBIMSidecarState: vi.fn(),
  };
});

const schemaMock = vi.mocked(api.fetchBIMDataframeSchema);
const queryMock = vi.mocked(api.queryBIMDataframe);
const valuesMock = vi.mocked(api.fetchBIMDataframeColumnValues);
const sidecarMock = vi.mocked(api.fetchBIMSidecarState);

const SCHEMA: api.BIMDataframeColumn[] = [
  { name: 'id', type: 'string', label: 'ID' },
  { name: 'category', type: 'string', label: 'Category' },
  { name: 'phase created', type: 'string', label: 'Phase Created' },
  { name: 'phase demolished', type: 'string', label: 'Phase Demolished' },
  { name: 'area', type: 'string', label: 'Area' },
];

const ELEMENTS = [
  { id: 'uuid-1', mesh_ref: '312001', stable_id: 'a-1' },
  { id: 'uuid-2', mesh_ref: '312002', stable_id: 'a-2' },
  { id: 'uuid-4', mesh_ref: '312004', stable_id: 'a-4' },
];

function renderPanel(overrides: Partial<ComponentProps<typeof PropertySearchPanel>> = {}) {
  const onIsolate = vi.fn();
  const onClear = vi.fn();
  render(
    <PropertySearchPanel
      modelId="m1"
      elements={ELEMENTS}
      onIsolate={onIsolate}
      onClear={onClear}
      {...overrides}
    />,
  );
  return { onIsolate, onClear };
}

async function pickColumn(typed: string, label: string) {
  const input = await screen.findByTestId('property-search-column');
  await waitFor(() => expect(input).not.toBeDisabled());
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: typed } });
  const list = await screen.findByTestId('property-search-column-listbox');
  fireEvent.mouseDown(within(list).getByText(label));
}

beforeEach(() => {
  sidecarMock.mockReset().mockResolvedValue('full');
  schemaMock.mockReset().mockResolvedValue(SCHEMA);
  queryMock.mockReset();
  valuesMock.mockReset().mockResolvedValue({ items: [
    { value: 'Progetto', count: 2 },
    { value: 'Stato di fatto', count: 1 },
  ], total: 2, offset: 0, limit: 200 });
});

describe('PropertySearchPanel', () => {
  it('lists properties by their Revit name and filters the list as you type', async () => {
    renderPanel();
    const input = await screen.findByTestId('property-search-column');
    await waitFor(() => expect(input).not.toBeDisabled());
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'phase' } });

    const list = await screen.findByTestId('property-search-column-listbox');
    const options = within(list).getAllByRole('option').map((o) => o.textContent);
    expect(options).toEqual(['Phase Created', 'Phase Demolished']);
    expect(screen.queryByText(/\(string\)/)).toBeNull();
  });

  it('keeps a long property list usable by capping what it renders', async () => {
    const many: api.BIMDataframeColumn[] = [{ name: 'id', type: 'string' }];
    for (let i = 0; i < 1200; i += 1) many.push({ name: `param ${String(i).padStart(4, '0')}`, type: 'string' });
    schemaMock.mockResolvedValue(many);
    renderPanel();
    const input = await screen.findByTestId('property-search-column');
    await waitFor(() => expect(input).not.toBeDisabled());
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: 'ArrowDown' });

    const list = await screen.findByTestId('property-search-column-listbox');
    expect(within(list).getAllByRole('option').length).toBeLessThanOrEqual(200);
    expect(screen.getByTestId('property-search-column-more')).toBeInTheDocument();

    fireEvent.change(input, { target: { value: 'param 1199' } });
    expect(within(screen.getByTestId('property-search-column-listbox')).getAllByRole('option')).toHaveLength(1);
  });

  it('queries by the column key and isolates the matching elements by their viewer id', async () => {
    queryMock.mockResolvedValue([{ id: '312002' }, { id: '312004' }]);
    const { onIsolate } = renderPanel();
    await pickColumn('phase cr', 'Phase Created');
    fireEvent.change(screen.getByTestId('property-search-op'), { target: { value: '=' } });
    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: 'Progetto' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));

    await waitFor(() => expect(onIsolate).toHaveBeenCalledWith(['uuid-2', 'uuid-4']));
    expect(queryMock).toHaveBeenCalledWith('m1', {
      columns: ['id'],
      // "=" always says whether the text is a number; this one is not.
      filters: [{ column: 'phase created', op: '=', value: 'Progetto', number: null }],
      limit: 50000,
    });
    expect(screen.getByTestId('property-search-result-count')).toHaveTextContent('2 matching elements');
  });

  it('says when some matches have no element in the 3D view', async () => {
    queryMock.mockResolvedValue([{ id: '312002' }, { id: '999999' }]);
    const { onIsolate } = renderPanel();
    await pickColumn('phase', 'Phase Created');
    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: 'prog' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));

    await waitFor(() => expect(onIsolate).toHaveBeenCalledWith(['uuid-2']));
    expect(screen.getByTestId('property-search-unmatched')).toHaveTextContent('1');
  });

  it('reports zero matches and leaves the view as it was', async () => {
    queryMock.mockResolvedValue([]);
    const { onIsolate, onClear } = renderPanel();
    await pickColumn('phase', 'Phase Created');
    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: 'nothing like this' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));

    expect(await screen.findByTestId('property-search-no-match')).toBeInTheDocument();
    expect(onIsolate).not.toHaveBeenCalled();
    expect(onClear).not.toHaveBeenCalled();
  });

  it('offers the values present in the model for "=" and still accepts typed text', async () => {
    queryMock.mockResolvedValue([{ id: '312001' }]);
    const { onIsolate } = renderPanel();
    await pickColumn('phase', 'Phase Created');
    fireEvent.change(screen.getByTestId('property-search-op'), { target: { value: '=' } });
    await waitFor(() => expect(valuesMock).toHaveBeenCalledWith('m1', 'phase created', 200, expect.anything(), 0));

    const valueInput = screen.getByTestId('property-search-value');
    fireEvent.focus(valueInput);
    fireEvent.keyDown(valueInput, { key: 'ArrowDown' });
    const list = await screen.findByTestId('property-search-value-listbox');
    expect(within(list).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Progetto2',
      'Stato di fatto1',
    ]);
    fireEvent.mouseDown(within(list).getByText('Stato di fatto'));
    expect(valueInput).toHaveValue('Stato di fatto');

    fireEvent.change(valueInput, { target: { value: 'Stato di f' } });
    expect(valueInput).toHaveValue('Stato di f');
    fireEvent.click(screen.getByTestId('property-search-submit'));
    await waitFor(() => expect(onIsolate).toHaveBeenCalledWith(['uuid-1']));
  });

  it('refuses text that is no number for a comparison before asking the server', async () => {
    renderPanel();
    await pickColumn('area', 'Area');
    fireEvent.change(screen.getByTestId('property-search-op'), { target: { value: '>' } });
    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: 'big' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));

    expect(await screen.findByTestId('property-search-error')).toHaveTextContent(
      'This comparison needs a number, for example 1234.5.',
    );
    expect(queryMock).not.toHaveBeenCalled();
  });

  it('sends a grouped number as a number and says how it read one that reads two ways', async () => {
    queryMock.mockResolvedValue([{ id: '312001' }]);
    renderPanel();
    await pickColumn('area', 'Area');
    fireEvent.change(screen.getByTestId('property-search-op'), { target: { value: '>' } });
    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: '1,500' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));

    await waitFor(() => expect(queryMock).toHaveBeenCalled());
    expect(queryMock.mock.calls[0]![1].filters).toEqual([{ column: 'area', op: '>', value: 1500 }]);
    expect(await screen.findByTestId('property-search-read-as')).toHaveTextContent('Read as 1500');
  });

  describe('"=" and "!=" send the number the reader meant beside the text', () => {
    // The server used to read the typed text as a number itself, dot-decimal,
    // so "= 1.500" typed in a comma-decimal convention matched cells of 1.5.
    afterEach(() => usePreferencesStore.setState({ numberLocale: 'auto' }));

    async function search(op: '=' | '!=', typed: string) {
      queryMock.mockResolvedValue([{ id: '312001' }]);
      renderPanel();
      await pickColumn('area', 'Area');
      fireEvent.change(screen.getByTestId('property-search-op'), { target: { value: op } });
      fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: typed } });
      fireEvent.click(screen.getByTestId('property-search-submit'));
      await waitFor(() => expect(queryMock).toHaveBeenCalled());
      return queryMock.mock.calls[0]![1].filters![0];
    }

    it('reads "1.500" as fifteen hundred where the dot groups thousands', async () => {
      usePreferencesStore.setState({ numberLocale: 'de-DE' });
      expect(await search('=', '1.500')).toEqual({ column: 'area', op: '=', value: '1.500', number: 1500 });
      expect(await screen.findByTestId('property-search-read-as')).toHaveTextContent('Read as 1500');
    });

    it('reads "1.500" as one and a half where the dot is the decimal mark', async () => {
      expect(await search('=', '1.500')).toEqual({ column: 'area', op: '=', value: '1.500', number: 1.5 });
      expect(await screen.findByTestId('property-search-read-as')).toHaveTextContent('Read as 1.5');
    });

    it('keeps text with a number inside it as text', async () => {
      usePreferencesStore.setState({ numberLocale: 'de-DE' });
      expect(await search('=', 'Muro 1.500')).toEqual({ column: 'area', op: '=', value: 'Muro 1.500', number: null });
      await screen.findByTestId('property-search-result-count');
      expect(screen.queryByTestId('property-search-read-as')).toBeNull();
    });

    it('does the same for "!="', async () => {
      usePreferencesStore.setState({ numberLocale: 'de-DE' });
      expect(await search('!=', '1.500')).toEqual({ column: 'area', op: '!=', value: '1.500', number: 1500 });
    });

    it('sends "!=" text with no number as text', async () => {
      expect(await search('!=', 'Muro 1.500')).toEqual({ column: 'area', op: '!=', value: 'Muro 1.500', number: null });
    });
  });

  it('shows no reading for a number that reads one way only', async () => {
    queryMock.mockResolvedValue([{ id: '312001' }]);
    renderPanel();
    await pickColumn('area', 'Area');
    fireEvent.change(screen.getByTestId('property-search-op'), { target: { value: '>=' } });
    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: '1.234,56' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));

    await waitFor(() => expect(queryMock).toHaveBeenCalled());
    expect(queryMock.mock.calls[0]![1].filters![0]!.value).toBe(1234.56);
    await screen.findByTestId('property-search-result-count');
    expect(screen.queryByTestId('property-search-read-as')).toBeNull();
  });

  it('shows its own text for a coded server refusal, never the server sentence', async () => {
    queryMock.mockRejectedValue(
      new api.BIMDataframeError("Unknown column: 'area'. The model has no property with that name.", 'unknown_column', {
        column: 'area',
      }),
    );
    renderPanel();
    await pickColumn('area', 'Area');
    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));

    const error = await screen.findByTestId('property-search-error');
    expect(error).toHaveTextContent('The model has no property "area".');
    expect(error).not.toHaveTextContent('Unknown column');
  });

  it('does not render an uncoded server message either', async () => {
    queryMock.mockRejectedValue(new Error('The property search could not run: Binder Error: something'));
    renderPanel();
    await pickColumn('area', 'Area');
    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));

    const error = await screen.findByTestId('property-search-error');
    expect(error).toHaveTextContent('The property search could not run. Try again, or pick another property.');
    expect(error).not.toHaveTextContent('Binder');
  });

  it('puts the chosen property back when Enter is pressed on a partial name', async () => {
    queryMock.mockResolvedValue([]);
    renderPanel();
    await pickColumn('area', 'Area');
    const input = screen.getByTestId('property-search-column');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'phase cr' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input).toHaveValue('Area');

    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));
    await waitFor(() => expect(queryMock).toHaveBeenCalled());
    expect(queryMock.mock.calls[0]![1].filters![0]!.column).toBe('area');
  });

  it('searches on Enter when the typed value is spelled like a value in the model', async () => {
    queryMock.mockResolvedValue([{ id: '312002' }]);
    const { onIsolate } = renderPanel();
    await pickColumn('phase', 'Phase Created');
    fireEvent.change(screen.getByTestId('property-search-op'), { target: { value: '=' } });
    await waitFor(() => expect(valuesMock).toHaveBeenCalled());
    const valueInput = screen.getByTestId('property-search-value');
    fireEvent.focus(valueInput);
    fireEvent.change(valueInput, { target: { value: 'progetto' } });
    fireEvent.keyDown(valueInput, { key: 'Enter' });

    await waitFor(() => expect(onIsolate).toHaveBeenCalledWith(['uuid-2']));
    expect(queryMock.mock.calls[0]![1].filters![0]!.value).toMatch(/^progetto$/i);
  });

  it('takes a property name typed in full on Enter', async () => {
    renderPanel();
    await pickColumn('area', 'Area');
    const input = screen.getByTestId('property-search-column');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'phase created' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input).toHaveValue('Phase Created');
  });
});

describe('a model whose property table lost what the import capped', () => {
  // The import keeps 30 properties per element in the database. A table
  // rebuilt from those rows lacks the rest ("phase created" on a Revit wall),
  // so a property the user looks for may simply not be there any more.
  const NOTICE = 'property-search-capped-properties';

  it('says a re-import brings it back when the property typed is not in the list', async () => {
    sidecarMock.mockResolvedValue('rebuilt');
    renderPanel();
    const input = await screen.findByTestId('property-search-column');
    await waitFor(() => expect(sidecarMock).toHaveBeenCalledWith('m1', expect.anything()));
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'fase restauro' } });

    expect(await screen.findByTestId(NOTICE)).toHaveTextContent('Re-import the model to get every property back.');
    fireEvent.change(input, { target: { value: 'phase' } });
    expect(screen.queryByTestId(NOTICE)).toBeNull();
  });

  it('says so when a search on a rebuilt table finds nothing', async () => {
    sidecarMock.mockResolvedValue('rebuilt');
    queryMock.mockResolvedValue([]);
    renderPanel();
    await pickColumn('phase cr', 'Phase Created');
    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: 'Progetto' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));

    await screen.findByTestId('property-search-no-match');
    expect(screen.getByTestId(NOTICE)).toBeInTheDocument();
  });

  it('stays quiet on a rebuilt table when the search finds elements', async () => {
    sidecarMock.mockResolvedValue('rebuilt');
    queryMock.mockResolvedValue([{ id: '312001' }]);
    renderPanel();
    await pickColumn('phase cr', 'Phase Created');
    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: 'Progetto' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));

    await screen.findByTestId('property-search-result-count');
    expect(screen.queryByTestId(NOTICE)).toBeNull();
  });

  it('stays quiet on a full table, where a missing property really is missing', async () => {
    queryMock.mockResolvedValue([]);
    renderPanel();
    const input = await screen.findByTestId('property-search-column');
    await waitFor(() => expect(sidecarMock).toHaveBeenCalled());
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'fase restauro' } });
    expect(screen.queryByTestId(NOTICE)).toBeNull();

    await pickColumn('phase cr', 'Phase Created');
    fireEvent.change(screen.getByTestId('property-search-value'), { target: { value: 'Progetto' } });
    fireEvent.click(screen.getByTestId('property-search-submit'));
    await screen.findByTestId('property-search-no-match');
    expect(screen.queryByTestId(NOTICE)).toBeNull();
  });
});

it('loads later value options only after Load more and keeps manual input', async () => {
  const first = Array.from({ length: 200 }, (_, i) => ({ value: `v${i}`, count: 1 }));
  valuesMock.mockResolvedValueOnce({ items: first, total: 201, offset: 0, limit: 200 })
    .mockResolvedValueOnce({ items: [{ value: 'late option', count: 2 }], total: 201, offset: 200, limit: 200 });
  renderPanel();
  await pickColumn('phase', 'Phase Created');
  fireEvent.change(screen.getByTestId('property-search-op'), { target: { value: '=' } });
  const more = await screen.findByTestId('property-search-values-more');
  expect(more.textContent).toContain('200 / 201');
  expect(valuesMock).toHaveBeenCalledTimes(1);
  const input = screen.getByTestId('property-search-value');
  fireEvent.change(input, { target: { value: 'manual value' } });
  fireEvent.click(more);
  await waitFor(() => expect(valuesMock).toHaveBeenLastCalledWith('m1', 'phase created', 200, expect.anything(), 200));
  await waitFor(() => expect(screen.queryByTestId('property-search-values-more')).toBeNull());
  expect(input).toHaveValue('manual value');
  fireEvent.change(input, { target: { value: 'late' } });
  fireEvent.focus(input);
  expect(await screen.findByText('late option')).toBeInTheDocument();
});
