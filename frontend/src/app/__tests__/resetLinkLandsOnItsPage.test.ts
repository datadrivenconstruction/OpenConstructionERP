// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The password-reset email has to open a page that can use it.
//
// The backend has always built the link as
// `{frontend_url}/auth/reset?token=...`. App.tsx had no route for that path,
// so the catch-all `*` caught it. That route sits inside the signed-in shell,
// whose guard sent a signed-out visitor (which is who follows a reset link) to
// `/login?next=/auth/reset?token=...`: a sign-in form for the password the
// reader had just said they forgot, with the live token parked in the address
// bar. Signing in some other way would only have forwarded them to Not Found.
// Nothing was red: the email test asserted only that a URL went out, the
// frontend had a `/forgot-password` page that sent the email, and both halves
// passed alone.
//
// So the path is read from the backend source, not typed here: a rename on
// either side fails this file. Then three things are asserted about App.tsx:
// a route declares that exact path, it renders the reset page with no
// sign-in gate in front of it (no RequireAuth, no AuthedHome, no Navigate),
// and React Router's own matcher picks it over `*`. A control path that does
// fall through to `*` keeps the matcher honest.
//
// Comments are stripped from App.tsx first, so the route mentioned in prose
// is never read as wiring.
//
// Run:  npx vitest run src/app/__tests__/resetLinkLandsOnItsPage.test.ts

import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { matchRoutes, type RouteObject } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

/** Resolve the repo root whether vitest was started at `frontend/` or the repo root. */
function findRepoRoot(): string {
  const root = [resolve(process.cwd(), '..'), process.cwd()].find((p) =>
    existsSync(join(p, 'frontend/src/app/App.tsx')),
  );
  expect(root, 'could not locate the repo root from the test working directory').toBeTruthy();
  return root!;
}

const ROOT = findRepoRoot();
const read = (rel: string): string => readFileSync(join(ROOT, rel), 'utf8');

/** Drop JSX `{/* *\/}` blocks, `/* *\/` blocks and `//` tails. */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

const APP = stripComments(read('frontend/src/app/App.tsx'));
const USERS_SERVICE = read('backend/app/modules/users/service.py');

/** The path part of the reset link the backend emails. */
function backendResetPath(): string {
  const match = USERS_SERVICE.match(/reset_url\s*=\s*f"\{self\.settings\.resolved_frontend_url\}(\/[^"?{]*)\?token=\{token\}"/);
  expect(match, 'the reset_url f-string in users/service.py changed shape').toBeTruthy();
  return match![1]!;
}

/** Every `<Route path="..." element={...} />` in App.tsx, in source order. */
function declaredRoutes(): { path: string; element: string; index: number }[] {
  const out: { path: string; element: string; index: number }[] = [];
  const re = /<Route\s+path="([^"]+)"\s+element=\{([\s\S]*?)\}\s*\/>/g;
  for (let m = re.exec(APP); m; m = re.exec(APP)) {
    out.push({ path: m[1]!, element: m[2]!, index: m.index });
  }
  return out;
}

describe('the password-reset link lands on its page', () => {
  const resetPath = backendResetPath();
  const routes = declaredRoutes();

  it('reads a plausible population before judging it', () => {
    expect(resetPath).toBe('/auth/reset');
    expect(routes.length).toBeGreaterThan(100);
    expect(routes.some((r) => r.path === '/forgot-password')).toBe(true);
    expect(routes.some((r) => r.path === '*')).toBe(true);
  });

  it('declares a route for the exact path the email links to', () => {
    const hits = routes.filter((r) => r.path === resetPath);
    expect(hits, `no <Route path="${resetPath}"> in App.tsx`).toHaveLength(1);
    expect(hits[0]!.element).toContain('<ResetPasswordPage');
  });

  it('puts no sign-in gate in front of it', () => {
    const route = routes.find((r) => r.path === resetPath)!;
    expect(route.element).not.toMatch(/RequireAuth|AuthedHome|Navigate/);

    // Everything inside the AppShell layout route sits behind RequireAuth.
    const shell = APP.indexOf('<Route element={<AppShell />}>');
    expect(shell, 'the AppShell layout route moved; re-check this assertion').toBeGreaterThan(0);
    expect(route.index).toBeLessThan(shell);
  });

  it('is matched ahead of the catch-all', () => {
    const objects: RouteObject[] = routes.map((r) => ({ path: r.path }));
    const pick = (url: string) => matchRoutes(objects, url)?.at(-1)?.route.path;

    expect(pick(resetPath)).toBe(resetPath);
    // Control: a path nobody declared does fall through to `*`.
    expect(pick('/auth/no-such-page')).toBe('*');
  });
});
