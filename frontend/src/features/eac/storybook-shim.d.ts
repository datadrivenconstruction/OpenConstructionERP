/**
 * Local Storybook type shim — keeps `*.stories.tsx` files typecheckable in
 * environments where `@storybook/react` isn't installed yet.
 *
 * Once Storybook is officially added to `frontend/package.json` as a dev
 * dependency (planned for EAC-3.x — see RFC 35 §7), this shim must be DELETED
 * so the real types from `@storybook/react` take over.
 *
 * The shim only declares the surface area used by the EAC stories
 * (CSF3: `Meta`, `StoryObj`, decorators, parameters). It deliberately does not
 * re-export everything; that would mask real type errors when the package
 * lands.
 */
declare module '@storybook/react' {
  import type { ComponentType, ReactElement } from 'react';

  // ── Decorator: a function that wraps a story's render output. ──────────────
  type StoryFn = () => ReactElement;
  type DecoratorFunction = (Story: StoryFn) => ReactElement;

  // ── Story args / parameters (loosely typed — Storybook is permissive). ─────
  // The type parameter `T` represents either a component or a `Meta<T>` object
  // — Storybook accepts both, so we keep `unknown` here and rely on `args` /
  // `render` for the actual checks.
  interface Meta<T = unknown> {
    title?: string;
    component?: ComponentType<unknown> | T;
    decorators?: DecoratorFunction[];
    parameters?: Record<string, unknown>;
    args?: Record<string, unknown>;
    argTypes?: Record<string, unknown>;
  }

  interface StoryObj<_T = unknown> {
    args?: Record<string, unknown>;
    render?: (args: Record<string, unknown>) => ReactElement;
    parameters?: Record<string, unknown>;
    decorators?: DecoratorFunction[];
  }
}
