// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The export control of the site registers. What it has to get right is small
// and each part has a way of going wrong quietly: the usual document in one
// click, the other language without leaving the control, a refused download
// that says what the server said, and a disabled state that explains itself.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

import { DocumentExportMenu, type DocumentExportItem } from './DocumentExportMenu';
import { useToastStore } from '@/stores/useToastStore';

const runPdf = vi.fn<(locale: string) => Promise<void>>();
const runXlsx = vi.fn<(locale: string) => Promise<void>>();

function items(): DocumentExportItem[] {
  return [
    { id: 'pdf', label: 'PDF document', kind: 'pdf', run: runPdf },
    { id: 'xlsx', label: 'Excel workbook (.xlsx)', kind: 'xlsx', run: runXlsx },
  ];
}

beforeEach(() => {
  runPdf.mockResolvedValue(undefined);
  runXlsx.mockResolvedValue(undefined);
  useToastStore.setState({ toasts: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('DocumentExportMenu', () => {
  it('downloads the first document in the interface language in one click', async () => {
    render(<DocumentExportMenu label="Export register" items={items()} testId="exp" />);
    fireEvent.click(screen.getByTestId('exp'));
    await waitFor(() => expect(runPdf).toHaveBeenCalledWith('en'));
    expect(runXlsx).not.toHaveBeenCalled();
    expect(screen.queryByTestId('exp-menu')).toBeNull();
  });

  it('says on the main half which document and language the click gives', () => {
    render(<DocumentExportMenu label="Export register" items={items()} testId="exp" />);
    expect(screen.getByTestId('exp').getAttribute('title')).toBe('Export register: PDF document, English');
  });

  it('offers exactly the languages the documents exist in, with the current one marked', () => {
    render(<DocumentExportMenu label="Export register" items={items()} testId="exp" />);
    fireEvent.click(screen.getByTestId('exp-more'));
    const radios = screen.getAllByRole('radio');
    expect(radios.map((r) => r.textContent)).toEqual(['English', 'Türkçe']);
    expect(screen.getByTestId('exp-lang-en').getAttribute('aria-checked')).toBe('true');
    expect(screen.getByTestId('exp-lang-tr').getAttribute('aria-checked')).toBe('false');
  });

  it('downloads in the other language once it is picked, from the menu and from the main half', async () => {
    render(<DocumentExportMenu label="Export register" items={items()} testId="exp" />);
    fireEvent.click(screen.getByTestId('exp-more'));
    fireEvent.click(screen.getByTestId('exp-lang-tr'));
    // Choosing a language is not a download and does not close the menu.
    expect(runPdf).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('exp-item-xlsx'));
    await waitFor(() => expect(runXlsx).toHaveBeenCalledWith('tr'));

    fireEvent.click(screen.getByTestId('exp'));
    await waitFor(() => expect(runPdf).toHaveBeenCalledWith('tr'));
  });

  it('shows no language choice for a document that exists in one language', () => {
    render(<DocumentExportMenu label="Export" items={items()} locales={['en']} testId="exp" />);
    fireEvent.click(screen.getByTestId('exp-more'));
    expect(screen.queryByRole('radiogroup')).toBeNull();
    expect(screen.getAllByRole('menuitem')).toHaveLength(2);
  });

  it('downloads the entry named as primary rather than the first one', async () => {
    render(<DocumentExportMenu label="Export" items={items()} primaryId="xlsx" testId="exp" />);
    fireEvent.click(screen.getByTestId('exp'));
    await waitFor(() => expect(runXlsx).toHaveBeenCalledWith('en'));
    expect(runPdf).not.toHaveBeenCalled();
  });

  it('prints a heading once per group of entries and the note under them', () => {
    const grouped: DocumentExportItem[] = [
      { id: 'a-pdf', label: 'PDF document', kind: 'pdf', group: 'Variation register', run: runPdf },
      { id: 'a-xlsx', label: 'Excel workbook (.xlsx)', kind: 'xlsx', group: 'Variation register', run: runXlsx },
      { id: 'b-pdf', label: 'PDF document', kind: 'pdf', group: 'Notice register', run: runPdf },
    ];
    render(<DocumentExportMenu label="Export" items={grouped} note="The whole register is exported." testId="exp" />);
    fireEvent.click(screen.getByTestId('exp-more'));
    expect(screen.getAllByText('Variation register')).toHaveLength(1);
    expect(screen.getAllByText('Notice register')).toHaveLength(1);
    expect(screen.getByText('The whole register is exported.')).toBeTruthy();
    expect(screen.getByTestId('exp').getAttribute('title')).toBe('Variation register: PDF document, English');
  });

  it('puts the server message in a toast when the download is refused, and recovers', async () => {
    runPdf.mockRejectedValueOnce(new Error('You do not have access to this project'));
    render(<DocumentExportMenu label="Export register" items={items()} testId="exp" />);
    fireEvent.click(screen.getByTestId('exp'));
    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0];
    expect(toast?.type).toBe('error');
    expect(toast?.title).toBe('Export failed');
    expect(toast?.message).toBe('You do not have access to this project');
    // Not left spinning: the next click goes through.
    await waitFor(() => expect((screen.getByTestId('exp') as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId('exp'));
    await waitFor(() => expect(runPdf).toHaveBeenCalledTimes(2));
  });

  it('is busy while a download runs, so a second click does not start a second one', async () => {
    let finish: () => void = () => {};
    runPdf.mockImplementationOnce(() => new Promise<void>((resolve) => (finish = resolve)));
    render(<DocumentExportMenu label="Export register" items={items()} testId="exp" />);
    fireEvent.click(screen.getByTestId('exp'));
    await waitFor(() => expect((screen.getByTestId('exp') as HTMLButtonElement).disabled).toBe(true));
    expect((screen.getByTestId('exp-more') as HTMLButtonElement).disabled).toBe(true);
    finish();
    await waitFor(() => expect((screen.getByTestId('exp') as HTMLButtonElement).disabled).toBe(false));
    expect(runPdf).toHaveBeenCalledTimes(1);
  });

  it('is disabled with its reason as the tooltip, and opens nothing', () => {
    render(
      <DocumentExportMenu
        label="Export register"
        items={items()}
        disabledReason="Please select a project first"
        testId="exp"
      />,
    );
    const main = screen.getByTestId('exp') as HTMLButtonElement;
    const more = screen.getByTestId('exp-more') as HTMLButtonElement;
    expect(main.disabled).toBe(true);
    expect(more.disabled).toBe(true);
    expect(main.getAttribute('title')).toBe('Please select a project first');
    fireEvent.click(main);
    fireEvent.click(more);
    expect(runPdf).not.toHaveBeenCalled();
    expect(screen.queryByTestId('exp-menu')).toBeNull();
  });

  it('closes on Escape and on a click outside, and a click on it never reaches the row behind', () => {
    const rowClick = vi.fn();
    render(
      <div onClick={rowClick}>
        <DocumentExportMenu label="Print / PDF" items={items()} testId="exp" />
      </div>,
    );
    fireEvent.click(screen.getByTestId('exp-more'));
    expect(screen.getByTestId('exp-menu')).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('exp-menu')).toBeNull();

    fireEvent.click(screen.getByTestId('exp-more'));
    fireEvent.mouseDown(document.body);
    expect(screen.queryByTestId('exp-menu')).toBeNull();
    expect(rowClick).not.toHaveBeenCalled();
  });
});
