// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every link a notification carries has to open a page.
//
// The backend writes an `action_url` on each notification, deadline item and
// inbox row. The bell, the notifications page, the inbox and the deadlines
// page hand it to the router as is, and the notification email turns it into
// the button the reader clicks. A path no route declares falls through to the
// catch-all `*` and shows Not Found, and nothing is red anywhere: the backend
// test asserts a string went out, the frontend test asserts navigate() was
// called with it. The file comment mention pointed at `/files/{kind}/{id}`
// for its whole life that way.
//
// So the links are read from the backend source, not typed here: every
// string literal that starts with `/` on the right-hand side of an
// `action_url` assignment or keyword anywhere under `backend/app`. Each
// f-string placeholder becomes a sample segment, the query string is dropped,
// and React Router's own matcher must pick a declared route (App.tsx plus the
// module registry) over `*`. When this file was written, 45 of the 100 paths
// it read fell through. An `action_url` written from a variable cannot be
// matched, so each of those is on a reviewed list and a new one is red.
//
// Rows already stored keep the link they were written with; the second block
// holds the client-side rewrite of every old shape to a page that exists.
//
// Run:  npx vitest run src/app/__tests__/notificationLinksLandOnARoute.test.ts

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { matchRoutes, type RouteObject } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { getAllModuleRoutes } from '@/modules/_registry';
import { ACTION_URL_REWRITES, normalizeActionUrl } from '@/shared/lib/notificationActionUrl';

/** Resolve the repo root whether vitest was started at `frontend/` or the repo root. */
function findRepoRoot(): string {
  const root = [resolve(process.cwd(), '..'), process.cwd()].find((p) =>
    existsSync(join(p, 'frontend/src/app/App.tsx')),
  );
  expect(root, 'could not locate the repo root from the test working directory').toBeTruthy();
  return root!;
}

const ROOT = findRepoRoot();

/** Drop JSX `{/* *\/}` blocks, `/* *\/` blocks and `//` tails. */
function stripTsComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

/** Every route path the app can render: App.tsx plus every module manifest. */
function declaredRoutePaths(): string[] {
  const app = stripTsComments(readFileSync(join(ROOT, 'frontend/src/app/App.tsx'), 'utf8'));
  const fromApp = [...app.matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]!);
  const fromModules = getAllModuleRoutes().map((r) => r.path);
  return [...fromApp, ...fromModules];
}

/** Every `.py` file under `dir`, skipping test folders and caches. */
function pythonFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    if (name === 'tests' || name === '__pycache__') continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...pythonFiles(full));
    else if (name.endsWith('.py')) out.push(full);
  }
  return out;
}

/** Blank out docstrings and comment lines so prose never reads as wiring. */
function stripPythonProse(source: string): string {
  return source
    .replace(/("""|''')[\s\S]*?\1/g, (m) => m.replace(/[^\n]/g, ' '))
    .replace(/^[ \t]*#[^\n]*/gm, '');
}

const SAMPLE = 'x0';

/**
 * The expression that starts at `start` and the string literals in it, with
 * every f-string placeholder replaced by a sample segment. The expression ends
 * at a comma or newline outside brackets, or at the bracket that closes the call.
 */
function expressionAt(src: string, start: number): { text: string; literals: string[] } {
  const out: string[] = [];
  let depth = 0;
  let i = start;
  while (i < src.length) {
    const ch = src[i]!;
    const prefix = /[fFrRbB]{0,2}$/.exec(src.slice(Math.max(start, i - 2), i))![0];
    if (ch === '"' || ch === "'") {
      const isF = /f/i.test(prefix);
      let j = i + 1;
      let text = '';
      while (j < src.length && src[j] !== ch) {
        if (src[j] === '\\') {
          text += src[j + 1] ?? '';
          j += 2;
          continue;
        }
        if (isF && src[j] === '{' && src[j + 1] !== '{') {
          let braces = 1;
          j += 1;
          while (j < src.length && braces > 0) {
            if (src[j] === '{') braces += 1;
            else if (src[j] === '}') braces -= 1;
            j += 1;
          }
          text += SAMPLE;
          continue;
        }
        text += src[j];
        j += 1;
      }
      out.push(text);
      i = j + 1;
      continue;
    }
    if (ch === '(' || ch === '[' || ch === '{') depth += 1;
    else if (ch === ')' || ch === ']' || ch === '}') {
      depth -= 1;
      if (depth < 0) break;
    } else if ((ch === ',' || ch === '\n') && depth === 0) break;
    i += 1;
  }
  return { text: src.slice(start, i).replace(/\s+/g, ' ').trim(), literals: out };
}

interface Producer {
  file: string;
  line: number;
  url: string;
}

/**
 * Every in-app path a backend producer writes into an `action_url`, and every
 * assignment that writes no path literal at all (a variable, a parameter, a
 * pass-through). The route check cannot see the second kind, so it is held to
 * a reviewed list below and a new one turns this file red.
 */
function backendActionUrls(): { producers: Producer[]; opaque: string[] } {
  const producers: Producer[] = [];
  const opaque: string[] = [];
  for (const file of pythonFiles(join(ROOT, 'backend/app'))) {
    const rel = relative(ROOT, file).replace(/\\/g, '/');
    const src = stripPythonProse(readFileSync(file, 'utf8'));
    // `action_url=` (keyword or assignment) and `"action_url":` (dict key);
    // an annotation `action_url: str` or a test `if action_url:` is neither.
    for (const m of src.matchAll(/\baction_url\s*=(?!=)|["']action_url["']\s*:/g)) {
      const at = m.index! + m[0].length;
      const line = src.slice(0, m.index).split('\n').length;
      const { text, literals } = expressionAt(src, at);
      // A call to a helper in the same file is read through to its returns.
      const helper = /^(\w+)\(/.exec(text)?.[1];
      const body = helper ? new RegExp(`\\ndef ${helper}\\([\\s\\S]*?(?=\\n\\S|$)`).exec(src) : null;
      if (body) {
        for (const r of body[0].matchAll(/\breturn\b/g)) literals.push(...expressionAt(body[0], r.index! + 6).literals);
      }
      const paths = literals.filter((url) => url.startsWith('/'));
      for (const url of paths) producers.push({ file: rel, line, url });
      if (paths.length === 0) opaque.push(`${rel}: ${text}`);
    }
  }
  return { producers, opaque: [...new Set(opaque)].sort() };
}

/**
 * Assignments that carry no path literal, each read by hand. Every one is a
 * pass-through of a value whose literal this file already checks where it is
 * built (a local variable, the `_notify` helper's parameter, a deadline item,
 * a stored notification row), or an absolute link for an external reader that
 * the app router never sees (portal sign-in, subcontractor bid link).
 */
const REVIEWED_OPAQUE: string[] = [
  'backend/app/modules/bid_management/service.py: action_url',
  'backend/app/modules/dashboard/inbox.py: action_url',
  'backend/app/modules/deadlines/sweeper.py: item.action_url',
  'backend/app/modules/integrations/notification_bridge.py: action_url',
  'backend/app/modules/integrations/router.py: None',
  'backend/app/modules/integrations/router.py: action_url',
  'backend/app/modules/notifications/_collaboration_subscribers.py: action_url',
  'backend/app/modules/notifications/_wave23_subscribers.py: action_url',
  // The email renderer, which resolves whatever it is given or drops it.
  'backend/app/modules/notifications/dispatcher.py: payload.get("action_url")',
  'backend/app/modules/notifications/events.py: action_url',
  'backend/app/modules/notifications/router.py: n.action_url',
  'backend/app/modules/notifications/service.py: action_url',
  'backend/app/modules/notifications/service.py: payload.get("action_url")',
  'backend/app/modules/portal/login_email.py: portal_link_url(token, role)',
  'backend/app/modules/tendering/service.py: action_url',
  'backend/app/modules/tendering/service.py: bid_link_url(token)',
];

describe('every notification link lands on a declared route', () => {
  const routes = declaredRoutePaths();
  const objects: RouteObject[] = routes.map((path) => ({ path }));
  const pick = (url: string) => matchRoutes(objects, url.split(/[?#]/)[0]!)?.at(-1)?.route.path;
  const { producers, opaque } = backendActionUrls();

  it('reads a plausible population before judging it', () => {
    expect(routes.length).toBeGreaterThan(300);
    expect(routes).toContain('*');
    expect(routes).toContain('/boq/:boqId');
    expect(producers.length).toBeGreaterThanOrEqual(90);
    const files = new Set(producers.map((p) => p.file));
    expect(files).toContain('backend/app/modules/notifications/events.py');
    expect(files).toContain('backend/app/modules/deadlines/service.py');
    expect(files).toContain('backend/app/core/event_handlers.py');
    // A literal inside a multi-line conditional is read too.
    expect(producers.some((p) => p.file.endsWith('notifications/events.py') && p.url.includes('comment='))).toBe(
      true,
    );
  });

  it('keeps the matcher honest', () => {
    expect(pick('/boq/x0')).toBe('/boq/:boqId');
    expect(pick('/rfi?id=x0')).toBe('/rfi');
    expect(pick('/files/pdf/x0')).toBe('*');
  });

  it('declares a route for every path a producer writes', () => {
    const dead = producers
      .filter((p) => pick(p.url) === '*' || pick(p.url) === undefined)
      .map((p) => `${p.file}:${p.line}  ${p.url}`);
    expect(dead, `action_url paths that open Not Found:\n${dead.join('\n')}`).toEqual([]);
  });

  it('writes no action_url it cannot read, apart from the reviewed ones', () => {
    expect(opaque).toEqual(REVIEWED_OPAQUE);
  });
});

describe('a notification stored before the fix still opens a page', () => {
  const routes = declaredRoutePaths();
  const objects: RouteObject[] = routes.map((path) => ({ path }));
  const pick = (url: string) => matchRoutes(objects, url.split(/[?#]/)[0]!)?.at(-1)?.route.path;
  const ID = '0b6f1c2e-6a52-4f0e-9f61-3d2a7c9e8b10';

  // One link per shape the producers used to write, as stored rows carry it.
  const STALE = [
    '/risk?id=x0',
    `/boq?id=${ID}`,
    `/files/document/${ID}?comment=${ID}`,
    `/projects/${ID}/documents`,
    `/approvals/${ID}`,
    `/bid-management/packages/${ID}`,
    `/bid-management/invitations/${ID}`,
    `/costmodel?line=${ID}`,
    `/file-approvals/${ID}`,
    `/changeorders/${ID}`,
    `/discussions?entity_type=rfi&entity_id=${ID}`,
    `/service/tickets/${ID}`,
    `/service/work-orders/${ID}`,
    `/subcontractors/prequalifications/${ID}`,
    `/subcontractors/payment-applications/${ID}`,
    `/subcontractors/retention/${ID}`,
    `/equipment/${ID}`,
    `/equipment/damage/${ID}`,
    `/contracts/${ID}`,
    `/contracts/${ID}/claims/${ID}`,
    `/contracts//claims/${ID}`,
    `/crm/leads/${ID}`,
    `/crm/opportunities/${ID}`,
    `/resources/assignments/${ID}`,
    `/resources/${ID}`,
    `/property-dev/buyers/${ID}`,
    `/property-dev/handovers/${ID}`,
    `/property-dev/warranty/${ID}`,
    `/schedule-advanced/constraints/${ID}`,
    `/daily-diary/${ID}`,
    '/bi-dashboards/alerts',
    '/bi-dashboards/reports',
    `/api/v1/bi-dashboards/report-runs/${ID}/file`,
    `/procurement/po/${ID}`,
    `/procurement/vendors/${ID}`,
    `/finance/invoices/${ID}`,
    `/warehouses/${ID}`,
    `/carbon/inventories/${ID}`,
    `/qms/ncrs/${ID}`,
  ];

  it('each sample really is stale, and the rewrite lands on a route', () => {
    for (const url of STALE) {
      // `/boq?id=` opened the list rather than Not Found; its rewrite only
      // sharpens the target, so it is the one sample exempt from being dead.
      if (!url.startsWith('/boq?')) {
        expect(pick(url), `${url} already opens a page; drop it from the samples`).toBe('*');
      }
      const next = normalizeActionUrl(url);
      expect(pick(next), `${url} -> ${next} still opens Not Found`).not.toBe('*');
    }
  });

  it('every rewrite has a sample', () => {
    for (const [re] of ACTION_URL_REWRITES) {
      expect(
        STALE.some((url) => re.test(url)),
        `no sample for ${re}`,
      ).toBe(true);
    }
  });

  it('never rewrites a path some route declares', () => {
    for (const path of routes) {
      if (path === '*') continue;
      const sample = path.replace(/:\w+/g, ID).replace(/\/\*$/, '');
      expect(normalizeActionUrl(sample), `rewrites the live route ${path}`).toBe(sample);
    }
  });
});
