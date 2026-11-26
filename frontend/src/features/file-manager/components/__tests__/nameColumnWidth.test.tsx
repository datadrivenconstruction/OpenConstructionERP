// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * #171 - on /files the NAME cell rendered as one letter and an ellipsis
 * ("F...", "C...") while TYPE, STATUS, VER., SIZE, MODIFIED and DISCIPLINE
 * all printed in full, and it held the same tenth of the table at 1120,
 * 1400 and 1720px. The name never won the slack at any window width.
 *
 * The cause is half an idiom. The cell carried `max-w-0` and the inner span
 * carried `truncate`, which is the pair that makes a long filename clip
 * instead of stretching the column. What was missing is `w-full` - in an
 * auto-layout table that is what says "this column takes what the others do
 * not need". Without it, `max-w-0` reads as "make this column as narrow as
 * you can", which is exactly what the browser did.
 *
 * WHAT THIS TEST CANNOT DO. jsdom does no table layout: every element here
 * measures 0x0, so no assertion in this file can show that the name column
 * got wider. It pins the structural rule instead - exactly one column claims
 * the slack, it is the free-text one, and it caps its own content - and that
 * rule is what was broken. Whether the result reads well needs a browser at
 * the three widths in the report. Same for the ChangeOrders guard below.
 *
 * Run:  npx vitest run src/features/file-manager/components/__tests__/nameColumnWidth.test.tsx
 */

import type { ReactElement } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

vi.mock('@/shared/ui/DateDisplay', () => ({
  DateDisplay: ({ value }: { value: string }) => <span>{value}</span>,
}));

vi.mock('@/features/file-search/SnippetHighlight', () => ({
  SnippetHighlight: ({ text }: { text: string }) => <span>{text}</span>,
}));

import { FileList } from '../FileList';
import type { FileRow } from '../../types';

/** The name from the report that got 120px at the widest window. */
const LONG_NAME = 'Coordinated model source.rvt';

const ROWS = [
  {
    id: 'f1',
    name: LONG_NAME,
    kind: 'bim_model',
    size_bytes: 4_200_000,
    modified_at: '2026-07-01T10:00:00Z',
    discipline: 'Structural',
    extension: 'rvt',
    extra: {},
  },
  {
    id: 'f2',
    name: 'D31_WV-2026-0417-coordination-review.pdf',
    kind: 'document',
    size_bytes: 91_000,
    modified_at: '2026-07-02T10:00:00Z',
    discipline: 'Architectural',
    extension: 'pdf',
    extra: {},
  },
] as unknown as FileRow[];

/* FileList draws a tag pill per row, and it reads those tags through react
   query, so a bare render of it throws "No QueryClient set" no matter what
   the test is actually looking at. A fresh client per render rather than one
   shared across the file: a shared cache carries one test's entries into the
   next and turns a failure into something that depends on test order. */
function withClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

function renderList() {
  return render(
    withClient(
      <FileList
        items={ROWS}
        selectedIds={new Set()}
        onSelect={() => undefined}
        onOpen={() => undefined}
        sort="name"
        onSortChange={() => undefined}
      />,
    ),
  );
}

describe('/files NAME column claims the leftover width (#171)', () => {
  it('gives the name cell both halves of the idiom', () => {
    const { container } = renderList();

    const nameCell = screen.getByTitle(LONG_NAME).closest('td');
    expect(nameCell).not.toBeNull();
    // w-full claims the slack, max-w-0 stops a long filename claiming more
    // than that. Either one alone is a different bug: w-full without
    // max-w-0 lets the name push the table into horizontal overflow, and
    // max-w-0 without w-full is what shipped.
    expect(nameCell!.className).toContain('w-full');
    expect(nameCell!.className).toContain('max-w-0');
    expect(container.querySelector('table')).not.toBeNull();
  });

  it('lets exactly one column claim the slack, and it is the name', () => {
    // Two columns both asking for the remaining width would split it, and
    // the name would be back to a fraction that no window width fixes.
    const { container } = renderList();

    const firstRow = container.querySelectorAll('tbody tr')[0]!;
    const claiming = [...firstRow.querySelectorAll('td')].filter((td) =>
      td.className.split(/\s+/).includes('w-full'),
    );

    expect(claiming).toHaveLength(1);
    expect(claiming[0]!.textContent).toContain(LONG_NAME);
  });

  it('keeps the header cell in step with the body cell', () => {
    // The column width is the widest specified width in the column, and the
    // header row is the only row present while the list is still loading.
    const { container } = renderList();

    const headers = [...container.querySelectorAll('thead th')];
    const claiming = headers.filter((th) => th.className.split(/\s+/).includes('w-full'));

    expect(claiming).toHaveLength(1);
    expect(claiming[0]!.textContent).toMatch(/name/i);
  });

  it('does not jump width when the skeleton rows are replaced', () => {
    // The loading skeleton draws its own cells. If the name column only
    // claims the slack once real rows arrive, the columns visibly resize
    // under the user at the moment the list loads.
    // Wrapped like the loaded case even though the skeleton draws no tag
    // cell and so needs no client today. Leaving the one bare render in the
    // file means the next person to give the skeleton a tag column gets the
    // same "No QueryClient set" the loaded rows already produced once.
    const { container } = render(
      withClient(
        <FileList
          items={[]}
          selectedIds={new Set()}
          onSelect={() => undefined}
          onOpen={() => undefined}
          sort="name"
          onSortChange={() => undefined}
          isLoading
        />,
      ),
    );

    const firstSkeletonRow = container.querySelectorAll('tbody tr')[0]!;
    const claiming = [...firstSkeletonRow.querySelectorAll('td')].filter((td) =>
      td.className.split(/\s+/).includes('w-full'),
    );

    expect(claiming).toHaveLength(1);
  });

  it('still reaches the full name, clipped or not', () => {
    // The report noted the whole name is in the DOM and CSS hides it, so a
    // copy-paste works and what the user reads does not. That stays true;
    // the point of the fix is that less of it needs hiding.
    renderList();

    expect(screen.getByTitle(LONG_NAME)).toHaveTextContent(LONG_NAME);
  });
});

/**
 * The second screen the report asks to check. The Change orders title cell
 * was capped at a flat `max-w-[200px]`, so it cut at the same ~40 characters
 * whether the window was 1120 or 1720px wide - the same defect as /files,
 * arrived at a different way.
 *
 * ChangeOrdersPage is a large page behind several queries, so this reads the
 * source rather than mounting it. It pins the rule, not the rendering.
 */
describe('Change orders title claims the leftover width (#171)', () => {
  it('no longer caps the title at a fixed pixel width', async () => {
    const { readFileSync } = await import('node:fs');
    const { resolve } = await import('node:path');
    const source = readFileSync(
      resolve(__dirname, '..', '..', '..', 'changeorders', 'ChangeOrdersPage.tsx'),
      'utf-8',
    );

    expect(source).not.toContain('max-w-[200px]');

    // Match the classes as separate tokens rather than as one exact string.
    // Reordering three class names is not a regression, and a guard that
    // fails on it costs someone an afternoon for nothing.
    const titleCell = /<td className="([^"]*)"\s+title=\{(?:designRecordName\(t, )?order\.title\)?\}>/.exec(source);
    expect(titleCell).not.toBeNull();
    const classes = titleCell![1]!.split(/\s+/);
    expect(classes).toContain('w-full');
    expect(classes).toContain('max-w-0');
    expect(classes).toContain('truncate');
  });
});
