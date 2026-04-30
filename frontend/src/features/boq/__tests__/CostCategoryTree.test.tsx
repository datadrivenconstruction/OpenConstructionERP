// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CostCategoryTree contract tests:
//   • Renders root nodes with their counts
//   • Children stay hidden until the parent is expanded
//   • Clicking a node emits the slash-joined path on onSelect
//   • Search-within-tree filters by node name AND keeps ancestors visible
//     for matched descendants
//   • Sentinel "__unspecified__" is rendered via the boq.uncategorized i18n key

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { TFunction } from 'i18next';
import { CostCategoryTree } from '../CostCategoryTree';
import type { CategoryTreeNode } from '../api';

// Minimal t() that honours `defaultValue` — matches what the test setup mocks
// for `useTranslation` so behaviour stays consistent across the suite.
const t = ((key: string, opts?: Record<string, unknown>) => {
  if (opts && typeof opts === 'object' && 'defaultValue' in opts) {
    let str = String(opts.defaultValue);
    for (const k of Object.keys(opts)) {
      if (k === 'defaultValue') continue;
      str = str.replace(new RegExp(`{{${k}}}`, 'g'), String(opts[k]));
    }
    return str;
  }
  return key;
}) as unknown as TFunction;

const SAMPLE_TREE: CategoryTreeNode[] = [
  {
    name: 'Buildings',
    count: 12044,
    children: [
      {
        name: 'Concrete',
        count: 3200,
        children: [
          { name: 'C25/30', count: 850, children: [] },
          { name: 'C30/37', count: 1100, children: [] },
        ],
      },
      { name: 'Masonry', count: 2400, children: [] },
    ],
  },
  {
    name: 'Infrastructure',
    count: 5000,
    children: [{ name: '__unspecified__', count: 100, children: [] }],
  },
];

describe('CostCategoryTree', () => {
  it('renders root nodes with their counts', () => {
    render(
      <CostCategoryTree
        tree={SAMPLE_TREE}
        selectedPath=""
        onSelect={vi.fn()}
        t={t}
      />,
    );
    expect(screen.getByText('Buildings')).toBeInTheDocument();
    expect(screen.getByText('Infrastructure')).toBeInTheDocument();
    // Counts use locale formatting; assert on the raw digits.
    expect(screen.getByText('12,044')).toBeInTheDocument();
    expect(screen.getByText('5,000')).toBeInTheDocument();
  });

  it('keeps children hidden until the parent is expanded', () => {
    render(
      <CostCategoryTree
        tree={SAMPLE_TREE}
        selectedPath=""
        onSelect={vi.fn()}
        t={t}
      />,
    );
    expect(screen.queryByText('Concrete')).toBeNull();
    expect(screen.queryByText('Masonry')).toBeNull();
  });

  it('expands a node when its chevron button is clicked', () => {
    render(
      <CostCategoryTree
        tree={SAMPLE_TREE}
        selectedPath=""
        onSelect={vi.fn()}
        t={t}
      />,
    );
    const expandBtn = screen
      .getAllByRole('button', { name: /Expand|Collapse/i })
      .find((b) => b.getAttribute('aria-label')?.includes('Expand'));
    expect(expandBtn).toBeTruthy();
    fireEvent.click(expandBtn!);
    expect(screen.getByText('Concrete')).toBeInTheDocument();
    expect(screen.getByText('Masonry')).toBeInTheDocument();
  });

  it('emits the slash-joined path when a node is clicked', () => {
    const onSelect = vi.fn();
    render(
      <CostCategoryTree
        tree={SAMPLE_TREE}
        selectedPath=""
        onSelect={onSelect}
        t={t}
      />,
    );

    // Top-level click → just the segment.
    fireEvent.click(screen.getByText('Buildings'));
    expect(onSelect).toHaveBeenLastCalledWith('Buildings');

    // After clicking Buildings the node auto-expands; click into the child.
    fireEvent.click(screen.getByText('Concrete'));
    expect(onSelect).toHaveBeenLastCalledWith('Buildings/Concrete');
  });

  it('filters node names recursively and keeps ancestors visible', () => {
    render(
      <CostCategoryTree
        tree={SAMPLE_TREE}
        selectedPath=""
        onSelect={vi.fn()}
        t={t}
      />,
    );
    const filter = screen.getByPlaceholderText('Filter categories...');
    fireEvent.change(filter, { target: { value: 'C30' } });

    // The matching descendant + its ancestors are visible …
    expect(screen.getByText('C30/37')).toBeInTheDocument();
    expect(screen.getByText('Buildings')).toBeInTheDocument();
    expect(screen.getByText('Concrete')).toBeInTheDocument();

    // … and unrelated branches are hidden.
    expect(screen.queryByText('Infrastructure')).toBeNull();
    expect(screen.queryByText('Masonry')).toBeNull();
  });

  it('renders the __unspecified__ sentinel as the localized "(Uncategorized)" label', () => {
    render(
      <CostCategoryTree
        tree={SAMPLE_TREE}
        selectedPath=""
        onSelect={vi.fn()}
        t={t}
      />,
    );
    // Expand the Infrastructure branch.
    const infraExpand = screen
      .getAllByRole('button', { name: /Expand/i })
      .at(-1);
    fireEvent.click(infraExpand!);

    expect(screen.getByText('(Uncategorized)')).toBeInTheDocument();
    // The literal sentinel token must NOT leak to the UI.
    expect(screen.queryByText('__unspecified__')).toBeNull();
  });

  it('marks the selected path as aria-selected', () => {
    render(
      <CostCategoryTree
        tree={SAMPLE_TREE}
        selectedPath="Buildings"
        onSelect={vi.fn()}
        t={t}
      />,
    );
    const buildingsRow = screen.getByText('Buildings').closest('[role="treeitem"]');
    expect(buildingsRow?.getAttribute('aria-selected')).toBe('true');
  });
});
