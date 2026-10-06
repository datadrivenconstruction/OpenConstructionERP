// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Ways into the Quantity Rules page from the BIM page.
//
// A tester could not find the quantity rules from the BIM page: the header
// "Rules" button opened the compliance requirements (?mode=requirements hides
// the Quantity Rules tab) in a new tab, which the desktop app may not open at
// all, and the right-click "Create quantity rule" item had no handler. BIMPage
// pulls in the whole 3D stack and is not rendered under vitest, so its two
// wires are asserted on the source; the banner it mounts is rendered for real.

import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      let d = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
      for (const [k, v] of Object.entries(opts ?? {})) d = d.replace(`{{${k}}}`, String(v));
      return d;
    },
  }),
}));

import { LinkToPositionBanner } from './LinkToPositionBanner';

const CANDIDATES = [
  resolve(process.cwd(), 'src/features/bim/BIMPage.tsx'),
  resolve(process.cwd(), 'frontend/src/features/bim/BIMPage.tsx'),
];
const PAGE_PATH = CANDIDATES.find(existsSync);
if (!PAGE_PATH) throw new Error(`cannot find BIMPage.tsx, looked in ${CANDIDATES.join(' and ')}`);
const PAGE = readFileSync(PAGE_PATH, 'utf8');

/** The JSX element carrying `data-testid="bim-rules-link-top"`, from its
 *  opening `<` to the end of its opening tag's attribute list. */
function rulesButtonSource(): string {
  const at = PAGE.indexOf('data-testid="bim-rules-link-top"');
  expect(at).toBeGreaterThan(-1);
  const open = PAGE.lastIndexOf('<', at);
  const close = PAGE.indexOf('>', at);
  return PAGE.slice(open, close + 1);
}

describe('the BIM page header Rules button', () => {
  it('is a same-tab button that opens the quantity rules with the project and model', () => {
    const src = rulesButtonSource();
    expect(src.startsWith('<button')).toBe(true);
    expect(src).not.toContain('target=');
    expect(src).toContain('navigate(buildQuantityRulesUrl({ projectId, modelId: activeModelId }))');
    expect(PAGE).not.toContain('/bim/rules?mode=requirements');
  });

  it('is shown for any loaded model and disabled, not hidden, without elements', () => {
    const src = rulesButtonSource();
    expect(src).toContain('disabled={elements.length === 0}');
    const before = PAGE.slice(Math.max(0, PAGE.indexOf('data-testid="bim-rules-link-top"') - 1500), PAGE.indexOf('data-testid="bim-rules-link-top"'));
    expect(before).toContain('{activeModelId && (');
    expect(before).not.toMatch(/\{elements\.length > 0 && \(\s*<span/);
  });
});

describe('the right-click Create quantity rule item', () => {
  it('is wired from BIMPage into the viewer', () => {
    expect(PAGE).toContain('onCreateQuantityRule={handleCreateQuantityRule}');
    expect(PAGE).toMatch(/const handleCreateQuantityRule = useCallback\([\s\S]{0,600}navigate\(\s*buildQuantityRulesUrl\(/);
  });
});

describe("the viewer's Open requirement item", () => {
  it('lands on the requirements tab, where requirements live', () => {
    // /bim/rules without a tab is the quantity rules, and the page reads no
    // requirement id: the old `/bim/rules?id=` link showed the wrong half.
    expect(PAGE).toContain('/bim/rules?tab=requirements');
    expect(PAGE).not.toContain('/bim/rules?id=');
  });
});

describe('LinkToPositionBanner', () => {
  const target = { positionId: 'pos-1', boqId: 'boq-1', label: '02.010 Plaster' };

  it('names the position and links the current selection', () => {
    const onLink = vi.fn();
    render(<LinkToPositionBanner target={target} selectionCount={3} onLink={onLink} onBack={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByTestId('bim-link-position-banner').textContent).toContain('02.010 Plaster');
    const go = screen.getByTestId('bim-link-position-go') as HTMLButtonElement;
    expect(go.textContent).toBe('Link selection (3)');
    fireEvent.click(go);
    expect(onLink).toHaveBeenCalledTimes(1);
  });

  it('cannot link an empty selection', () => {
    render(<LinkToPositionBanner target={target} selectionCount={0} onLink={vi.fn()} onBack={vi.fn()} onCancel={vi.fn()} />);
    expect((screen.getByTestId('bim-link-position-go') as HTMLButtonElement).disabled).toBe(true);
  });

  // Linking (POST /bim_hub/links/) needs bim.create. A viewer who follows a
  // link here gets the way back, and a sentence instead of a button that 403s.
  it('offers no link action to a role that cannot link, and says why', () => {
    const onBack = vi.fn();
    render(
      <LinkToPositionBanner target={target} selectionCount={3} canLink={false} onLink={vi.fn()} onBack={onBack} onCancel={vi.fn()} />,
    );
    expect(screen.queryByTestId('bim-link-position-go')).toBeNull();
    expect(screen.getByTestId('bim-link-position-banner').textContent).toContain('cannot link');
    fireEvent.click(screen.getByRole('button', { name: /Back to BOQ/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('is told by BIMPage whether the role may create links', () => {
    expect(PAGE).toContain("const canCreateBimLinks = useHasPermission('bim.create');");
    expect(PAGE).toMatch(/<LinkToPositionBanner[\s\S]{0,400}canLink=\{canCreateBimLinks\}/);
  });
});

describe('the legacy /requirements link', () => {
  it('lands on the requirements tab, not on the quantity rules', () => {
    const app = readFileSync(PAGE_PATH.replace(/features[\\/]bim[\\/]BIMPage\.tsx$/, 'app/App.tsx'), 'utf8');
    expect(app).toContain('<Route path="/requirements" element={<Navigate to="/bim/rules?tab=requirements" replace />} />');
  });
});
