/**
 * Visual Regression Tests — Structural Snapshots
 *
 * Uses Vitest snapshot matching on rendered HTML to detect structural changes
 * in key UI components. When a component's DOM structure changes, the snapshot
 * diff shows exactly what changed, serving as a lightweight visual regression
 * guard without requiring a browser-based screenshot tool.
 *
 * Run:  npx vitest run src/tests/visual-regression.test.tsx
 * Update snapshots:  npx vitest run src/tests/visual-regression.test.tsx -u
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

/* ── Mock @/app/i18n to prevent i18next initialization side-effects ─── */

vi.mock('@/app/i18n', () => ({
  CORE_LANGUAGES: [
    { code: 'en', name: 'English', flag: 'gb', country: 'gb' },
    { code: 'de', name: 'Deutsch', flag: 'de', country: 'de' },
  ],
  EXTRA_LANGUAGES: [],
  SUPPORTED_LANGUAGES: [
    { code: 'en', name: 'English', flag: 'gb', country: 'gb' },
    { code: 'de', name: 'Deutsch', flag: 'de', country: 'de' },
  ],
  getLanguageByCode: (code: string) =>
    code === 'de'
      ? { code: 'de', name: 'Deutsch', flag: 'de', country: 'de' }
      : { code: 'en', name: 'English', flag: 'gb', country: 'gb' },
  default: {
    use: () => ({ use: () => ({ use: () => ({ init: vi.fn() }) }) }),
    t: (key: string) => key,
    language: 'en',
    changeLanguage: vi.fn(),
  },
}));

/* ── Mock @tanstack/react-query to avoid real network calls ──────────── */

vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn().mockReturnValue({
    data: undefined,
    isLoading: true,
    isError: false,
    isSuccess: false,
    error: null,
    refetch: vi.fn(),
  }),
  useMutation: vi.fn().mockReturnValue({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: false,
  }),
  useQueryClient: vi.fn().mockReturnValue({
    invalidateQueries: vi.fn(),
    setQueryData: vi.fn(),
  }),
  QueryClient: vi.fn(),
  QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}));

/* ── Mock shared/lib/api to prevent import side-effects ──────────────── */

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn().mockResolvedValue([]),
  apiPost: vi.fn().mockResolvedValue({}),
  apiPatch: vi.fn().mockResolvedValue({}),
  apiDelete: vi.fn().mockResolvedValue(undefined),
  ApiError: class ApiError extends Error {
    status: number;
    statusText: string;
    body: unknown;
    constructor(status: number, statusText: string, body: unknown) {
      super(`API ${status}: ${statusText}`);
      this.name = 'ApiError';
      this.status = status;
      this.statusText = statusText;
      this.body = body;
    }
  },
}));

/* ── Mock stores to provide default state ────────────────────────────── */

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({
        accessToken: 'mock-token',
        isAuthenticated: true,
        userEmail: 'test@example.com',
        setTokens: vi.fn(),
        logout: vi.fn(),
        loadFromStorage: vi.fn(),
      }),
    {
      getState: () => ({
        accessToken: 'mock-token',
        isAuthenticated: true,
        userEmail: 'test@example.com',
        setTokens: vi.fn(),
        logout: vi.fn(),
        loadFromStorage: vi.fn(),
      }),
    },
  ),
}));

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({ toasts: [], addToast: vi.fn(), removeToast: vi.fn() }),
    {
      getState: () => ({ toasts: [], addToast: vi.fn(), removeToast: vi.fn() }),
    },
  ),
}));

/* ── Component imports ───────────────────────────────────────────────── */

import { EmptyState } from '@/shared/ui/EmptyState';
import { NotFoundPage } from '@/shared/ui/NotFoundPage';
import {
  SkeletonText,
  SkeletonCard,
  SkeletonTable,
  SkeletonGrid,
} from '@/shared/ui/SkeletonLoader';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { Button } from '@/shared/ui/Button';
import { Input } from '@/shared/ui/Input';
import { Badge } from '@/shared/ui/Badge';
import { Card, CardHeader, CardContent, CardFooter } from '@/shared/ui/Card';
import { Logo, LogoWithText } from '@/shared/ui/Logo';
import { InfoHint } from '@/shared/ui/InfoHint';

/* ── Helpers ─────────────────────────────────────────────────────────── */

function RouterWrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

/* ═══════════════════════════════════════════════════════════════════════
   1. EmptyState
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — EmptyState', () => {
  it('renders minimal (title only)', () => {
    const { container } = render(
      <EmptyState title="No items found" />,
    );
    expect(container).toMatchSnapshot();
  });

  it('renders with icon, description, and action button', () => {
    const { container } = render(
      <EmptyState
        icon={<span data-testid="mock-icon">icon</span>}
        title="No projects"
        description="Create your first project to get started."
        action={{ label: 'Create Project', onClick: () => {} }}
      />,
    );
    expect(container).toMatchSnapshot();
  });

  it('renders with custom ReactNode action', () => {
    const { container } = render(
      <EmptyState
        title="No data"
        description="Import data from an external source."
        action={<button className="custom-btn">Import Data</button>}
      />,
    );
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   2. NotFoundPage (404)
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — NotFoundPage', () => {
  it('renders the 404 page with navigation links', () => {
    const { container } = render(
      <RouterWrapper>
        <NotFoundPage />
      </RouterWrapper>,
    );
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   3. SkeletonLoader variants
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — SkeletonLoader', () => {
  it('SkeletonText — default width', () => {
    const { container } = render(<SkeletonText />);
    expect(container).toMatchSnapshot();
  });

  it('SkeletonText — custom width w-3/4', () => {
    const { container } = render(<SkeletonText width="w-3/4" />);
    expect(container).toMatchSnapshot();
  });

  it('SkeletonCard — single card', () => {
    const { container } = render(<SkeletonCard />);
    expect(container).toMatchSnapshot();
  });

  it('SkeletonTable — 3 rows x 4 columns', () => {
    const { container } = render(<SkeletonTable rows={3} columns={4} />);
    expect(container).toMatchSnapshot();
  });

  it('SkeletonTable — default dimensions (5x5)', () => {
    const { container } = render(<SkeletonTable />);
    expect(container).toMatchSnapshot();
  });

  it('SkeletonGrid — 4 items', () => {
    const { container } = render(<SkeletonGrid items={4} />);
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   4. ConfirmDialog
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — ConfirmDialog', () => {
  it('renders danger variant (open)', () => {
    const { container } = render(
      <ConfirmDialog
        open={true}
        variant="danger"
        title="Delete Project"
        message="Are you sure? This action cannot be undone."
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(container).toMatchSnapshot();
  });

  it('renders warning variant (open)', () => {
    const { container } = render(
      <ConfirmDialog
        open={true}
        variant="warning"
        title="Discard Changes"
        message="You have unsaved changes. Do you want to discard them?"
        confirmLabel="Discard"
        cancelLabel="Keep editing"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(container).toMatchSnapshot();
  });

  it('renders loading state', () => {
    const { container } = render(
      <ConfirmDialog
        open={true}
        variant="danger"
        title="Deleting..."
        message="Please wait while the item is being deleted."
        loading={true}
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(container).toMatchSnapshot();
  });

  it('renders nothing when closed', () => {
    const { container } = render(
      <ConfirmDialog
        open={false}
        title="Hidden"
        message="Should not render"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   5. Breadcrumb
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — Breadcrumb', () => {
  it('renders single breadcrumb item', () => {
    const { container } = render(
      <RouterWrapper>
        <Breadcrumb items={[{ label: 'Projects' }]} />
      </RouterWrapper>,
    );
    expect(container).toMatchSnapshot();
  });

  it('renders multi-level breadcrumb with links', () => {
    const { container } = render(
      <RouterWrapper>
        <Breadcrumb
          items={[
            { label: 'Projects', to: '/projects' },
            { label: 'Office Tower Berlin', to: '/projects/proj-001' },
            { label: 'Main Estimate' },
          ]}
        />
      </RouterWrapper>,
    );
    expect(container).toMatchSnapshot();
  });

  it('renders empty (returns null for empty items)', () => {
    const { container } = render(
      <RouterWrapper>
        <Breadcrumb items={[]} />
      </RouterWrapper>,
    );
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   6. Button variants
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — Button', () => {
  it('primary button', () => {
    const { container } = render(<Button variant="primary">Save</Button>);
    expect(container).toMatchSnapshot();
  });

  it('secondary button', () => {
    const { container } = render(<Button variant="secondary">Cancel</Button>);
    expect(container).toMatchSnapshot();
  });

  it('ghost button', () => {
    const { container } = render(<Button variant="ghost">Options</Button>);
    expect(container).toMatchSnapshot();
  });

  it('danger button', () => {
    const { container } = render(<Button variant="danger">Delete</Button>);
    expect(container).toMatchSnapshot();
  });

  it('loading state', () => {
    const { container } = render(<Button variant="primary" loading>Saving...</Button>);
    expect(container).toMatchSnapshot();
  });

  it('disabled state', () => {
    const { container } = render(<Button variant="primary" disabled>Disabled</Button>);
    expect(container).toMatchSnapshot();
  });

  it('with icon (left)', () => {
    const { container } = render(
      <Button variant="primary" icon={<span>+</span>}>Add Item</Button>,
    );
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   7. Input
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — Input', () => {
  it('default input with label', () => {
    const { container } = render(
      <Input label="Project Name" placeholder="Enter project name" />,
    );
    expect(container).toMatchSnapshot();
  });

  it('input with error state', () => {
    const { container } = render(
      <Input label="Email" type="email" error="Please enter a valid email address" />,
    );
    expect(container).toMatchSnapshot();
  });

  it('input with hint', () => {
    const { container } = render(
      <Input label="Password" type="password" hint="Minimum 8 characters" />,
    );
    expect(container).toMatchSnapshot();
  });

  it('input with icon', () => {
    const { container } = render(
      <Input label="Search" icon={<span>S</span>} placeholder="Search..." />,
    );
    expect(container).toMatchSnapshot();
  });

  it('disabled input', () => {
    const { container } = render(
      <Input label="Read Only" value="Fixed value" disabled />,
    );
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   8. Badge
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — Badge', () => {
  it('neutral badge', () => {
    const { container } = render(<Badge variant="neutral">Draft</Badge>);
    expect(container).toMatchSnapshot();
  });

  it('blue badge with dot', () => {
    const { container } = render(<Badge variant="blue" dot>Active</Badge>);
    expect(container).toMatchSnapshot();
  });

  it('success badge', () => {
    const { container } = render(<Badge variant="success">Completed</Badge>);
    expect(container).toMatchSnapshot();
  });

  it('warning badge', () => {
    const { container } = render(<Badge variant="warning">Pending</Badge>);
    expect(container).toMatchSnapshot();
  });

  it('error badge (small)', () => {
    const { container } = render(<Badge variant="error" size="sm">Failed</Badge>);
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   9. Card
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — Card', () => {
  it('card with header and content', () => {
    const { container } = render(
      <Card>
        <CardHeader title="Project Summary" subtitle="Overview of your project" />
        <CardContent>
          <p>Total cost: 1,200,000 EUR</p>
        </CardContent>
      </Card>,
    );
    expect(container).toMatchSnapshot();
  });

  it('card with footer and hoverable', () => {
    const { container } = render(
      <Card hoverable>
        <CardHeader
          title="Recent BOQ"
          action={<button>View All</button>}
        />
        <CardContent>
          <p>3 positions, 54,225 EUR total</p>
        </CardContent>
        <CardFooter>
          <button>Export</button>
          <button>Edit</button>
        </CardFooter>
      </Card>,
    );
    expect(container).toMatchSnapshot();
  });

  it('card with no padding', () => {
    const { container } = render(
      <Card padding="none">
        <div>Full-width content</div>
      </Card>,
    );
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   10. Logo
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — Logo', () => {
  it('Logo — small', () => {
    const { container } = render(<Logo size="sm" />);
    expect(container).toMatchSnapshot();
  });

  it('Logo — large with animation', () => {
    const { container } = render(<Logo size="lg" animate />);
    expect(container).toMatchSnapshot();
  });

  it('LogoWithText — default', () => {
    const { container } = render(<LogoWithText />);
    expect(container).toMatchSnapshot();
  });

  it('LogoWithText — without version', () => {
    const { container } = render(<LogoWithText showVersion={false} />);
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   11. InfoHint
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — InfoHint', () => {
  it('block mode — collapsed', () => {
    const { container } = render(
      <InfoHint text="This is helpful information about the current section." />,
    );
    expect(container).toMatchSnapshot();
  });

  it('inline mode — collapsed', () => {
    const { container } = render(
      <InfoHint text="Inline help tooltip content." inline />,
    );
    expect(container).toMatchSnapshot();
  });

  it('block mode with custom label', () => {
    const { container } = render(
      <InfoHint
        text="Detailed explanation goes here."
        label="What is this?"
      />,
    );
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   12. LoginPage
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — LoginPage', () => {
  // The LoginPage marketing background uses a typewriter ticker that
  // animates BOQ-table cells character-by-character via setInterval. Each
  // render captures the DOM at a slightly different point in the animation,
  // so a static snapshot match is inherently flaky. The login form itself
  // (form fields, submit button, demo access) is exercised by the e2e
  // Playwright suite where animation timing is deterministic.
  it.skip('renders the login form (skipped — flaky due to typewriter ticker)', async () => {
    const { LoginPage } = await import('@/features/auth/LoginPage');
    const { container } = render(
      <RouterWrapper>
        <LoginPage />
      </RouterWrapper>,
    );
    expect(container).toMatchSnapshot();
  });
});

/* ═══════════════════════════════════════════════════════════════════════
   13. DashboardPage (loading state)
═══════════════════════════════════════════════════════════════════════ */

describe('Visual Regression — DashboardPage', () => {
  it('renders loading/skeleton state', async () => {
    const { DashboardPage } = await import('@/features/dashboard/DashboardPage');
    const { container } = render(
      <RouterWrapper>
        <DashboardPage />
      </RouterWrapper>,
    );
    expect(container).toMatchSnapshot();
  }, 15000);
});
