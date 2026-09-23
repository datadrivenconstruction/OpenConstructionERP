// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// GET /v1/projects/ answers with the first 50 projects when asked without a
// limit, and the body carries no total. Every picker in the app asked it that
// way, so a user with more than 50 projects silently lost the rest in every
// project list except the header switcher.
//
// The first half pins the reader: it pages until a short page, so the list it
// hands back is the whole list. The second half pins the call sites: nothing
// outside the reader asks for the list on its own, and every query cached under
// ['projects'] fills it through the reader and caches no fallback. The header
// switcher reads that entry and clears the active project when it is missing
// from it, so one reader caching 50 rows, or [] on error, would clear a valid
// selection.

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const api = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock('./api', () => api);

import { fetchProjectList, fetchProjectListByStatus, PROJECT_LIST_PAGE_SIZE } from './projectList';

type Row = { id: string; name: string };
const rows = (from: number, count: number): Row[] =>
  Array.from({ length: count }, (_, i) => ({ id: `p-${from + i}`, name: `Project ${from + i}` }));

beforeEach(() => {
  api.apiGet.mockReset();
});

describe('fetchProjectList', () => {
  it('asks for the server maximum and stops after a short page', async () => {
    api.apiGet.mockResolvedValueOnce(rows(0, 3));
    const list = await fetchProjectList<Row[]>();
    expect(list).toHaveLength(3);
    expect(api.apiGet.mock.calls.map((c) => c[0])).toEqual(['/v1/projects/?limit=500']);
  });

  it('reads past the first page, so a user with more projects than a page sees all of them', async () => {
    api.apiGet
      .mockResolvedValueOnce(rows(0, PROJECT_LIST_PAGE_SIZE))
      .mockResolvedValueOnce(rows(PROJECT_LIST_PAGE_SIZE, PROJECT_LIST_PAGE_SIZE))
      .mockResolvedValueOnce(rows(2 * PROJECT_LIST_PAGE_SIZE, 7));
    const list = await fetchProjectList<Row[]>();
    expect(list).toHaveLength(2 * PROJECT_LIST_PAGE_SIZE + 7);
    expect(new Set(list.map((p) => p.id)).size).toBe(list.length);
    expect(api.apiGet.mock.calls.map((c) => c[0])).toEqual([
      '/v1/projects/?limit=500',
      '/v1/projects/?limit=500&offset=500',
      '/v1/projects/?limit=500&offset=1000',
    ]);
  });

  it('drops a row repeated across pages, which a project created mid-read causes', async () => {
    const first = rows(0, PROJECT_LIST_PAGE_SIZE);
    api.apiGet
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce([first[PROJECT_LIST_PAGE_SIZE - 1]!, ...rows(PROJECT_LIST_PAGE_SIZE, 2)]);
    const list = await fetchProjectList<Row[]>();
    expect(list).toHaveLength(PROJECT_LIST_PAGE_SIZE + 2);
  });

  it('stops when a full page brings nothing new instead of asking forever', async () => {
    const page = rows(0, PROJECT_LIST_PAGE_SIZE);
    api.apiGet.mockResolvedValue(page);
    const list = await fetchProjectList<Row[]>();
    expect(list).toHaveLength(PROJECT_LIST_PAGE_SIZE);
    expect(api.apiGet).toHaveBeenCalledTimes(2);
  });

  it('fails on a body that is not a list rather than reporting no projects', async () => {
    api.apiGet.mockResolvedValueOnce({ items: rows(0, 2) });
    await expect(fetchProjectList<Row[]>()).rejects.toThrow(TypeError);
  });

  it('passes a status filter on every page', async () => {
    api.apiGet.mockResolvedValueOnce(rows(0, PROJECT_LIST_PAGE_SIZE)).mockResolvedValueOnce([]);
    await fetchProjectListByStatus<Row[]>('on_hold');
    expect(api.apiGet.mock.calls.map((c) => c[0])).toEqual([
      '/v1/projects/?limit=500&status=on_hold',
      '/v1/projects/?limit=500&offset=500&status=on_hold',
    ]);
  });
});

function srcRoot(): string {
  const candidates = [resolve(process.cwd(), 'src'), resolve(process.cwd(), 'frontend/src')];
  const hit = candidates.find((c) => existsSync(join(c, 'shared', 'lib', 'projectList.ts')));
  if (!hit) throw new Error(`no src root among ${candidates.join(', ')}`);
  return hit;
}

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === '__tests__' || name === 'tests') continue;
      sources(p, out);
    } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      out.push(p);
    }
  }
  return out;
}

/** The object literal that encloses `index`, found by brace depth. */
function enclosingObject(text: string, index: number): string {
  let depth = 0;
  let start = index;
  for (; start >= 0; start -= 1) {
    const c = text[start];
    if (c === '}') depth += 1;
    else if (c === '{') {
      if (depth === 0) break;
      depth -= 1;
    }
  }
  depth = 0;
  let end = start;
  for (; end < text.length; end += 1) {
    const c = text[end];
    if (c === '{') depth += 1;
    else if (c === '}') {
      depth -= 1;
      if (depth === 0) break;
    }
  }
  return text.slice(start, end + 1);
}

describe('the project list call sites', () => {
  const files = sources(srcRoot()).map((file) => ({ file, text: readFileSync(file, 'utf8') }));

  it('never GET the list except through the reader', () => {
    // A type argument has no parentheses, so the match cannot run from one
    // call into the next.
    const bare = /apiGet\s*<[^()]*?>\s*\(\s*['"`]\/v1\/projects\/(\?[^'"`]*)?['"`]/;
    // Block comments and whole-line comments only, so a usage example in a
    // docstring does not count and a URL inside a string is left alone.
    const code = (text: string) => text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    const offenders = files
      .filter(({ file }) => !file.endsWith(join('shared', 'lib', 'projectList.ts')))
      .filter(({ text }) => bare.test(code(text)))
      .map(({ file }) => file);
    expect(offenders).toEqual([]);
  });

  it("fill ['projects'] through the reader and cache no fallback", () => {
    const sites: Array<{ file: string; object: string }> = [];
    for (const { file, text } of files) {
      for (const m of text.matchAll(/queryKey:\s*\['projects'\]\s*[,}]/g)) {
        const object = enclosingObject(text, m.index!);
        // Invalidations name the key without a queryFn and fill nothing.
        if (object.includes('queryFn')) sites.push({ file, object });
      }
    }
    // Not vacuous: dozens of pages read this entry, the header among them.
    expect(sites.length).toBeGreaterThan(50);
    expect(sites.some((s) => s.file.endsWith('Header.tsx'))).toBe(true);

    const reader =
      /queryFn:\s*(?:\(\)\s*=>\s*)?(?:fetchProjectList<[^\n]*?>\(\)|projectsApi\.list(?:\(\))?)(?=\s*[,}\n])/;
    const offenders = sites.filter((s) => !reader.test(s.object)).map((s) => `${s.file}\n${s.object}`);
    expect(offenders).toEqual([]);
  });
});
