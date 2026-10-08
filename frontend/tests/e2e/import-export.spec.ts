/**
 * import-export.spec.ts - BOQ import / export round trip through the real API and UI.
 *
 * For an XPWE and a GAEB X83 bill: the grand total the editor shows equals the
 * server total; GAEB, XLSX and PDF exports are non-empty; the XLSX "Grand Total"
 * cell equals the on-screen total; a GAEB X84 export re-imported into a fresh
 * bill yields the same total; and a truncated GAEB upload is refused without
 * changing the bill's position count.
 *
 * Fixtures are the backend's own conformance files, read in place.
 */
import fs from 'node:fs';
import path from 'node:path';
import ExcelJS from 'exceljs';
import type { APIRequestContext } from '@playwright/test';
import { test, expect, API_URL } from './fixtures';

const BACKEND_FIXTURES = path.resolve(__dirname, '../../../backend/tests/fixtures');
const XPWE = fs.readFileSync(path.join(BACKEND_FIXTURES, 'xpwe/computo_small.xpwe'));
const X83 = fs.readFileSync(path.join(BACKEND_FIXTURES, 'gaeb/oce_conformance_x83.x83'));

interface Project {
  id: string;
}
interface Boq {
  id: string;
}
interface BoqWithPositions {
  positions: unknown[];
}
interface CostBreakdown {
  grand_total: string | number;
}

/** "€12,345.67", "12.345,67 €", "12 345,67" -> 12345.67 */
function parseMoney(text: string): number {
  let s = text.replace(/[^\d.,-]/g, '');
  const lastDot = s.lastIndexOf('.');
  const lastComma = s.lastIndexOf(',');
  const dec = Math.max(lastDot, lastComma);
  if (dec >= 0 && s.length - dec - 1 <= 2) {
    s = s.slice(0, dec).replace(/[.,]/g, '') + '.' + s.slice(dec + 1);
  } else {
    s = s.replace(/[.,]/g, '');
  }
  return Number(s);
}

function v1(p: string): string {
  return `${API_URL}/api/v1${p}`;
}

test.describe('BOQ import / export', () => {
  let req: APIRequestContext;
  let auth: Record<string, string>;
  let projectId: string;

  test.beforeAll(async ({ playwright, accessToken, api }) => {
    req = await playwright.request.newContext();
    auth = { Authorization: `Bearer ${accessToken}`, 'X-DDC-Client': 'OE-QA/1.0' };
    const project = await api.post<Project>('/projects/', {
      name: `E2E import-export ${Date.now()}`,
      region: 'DACH',
      currency: 'EUR',
    });
    projectId = project.id;
  });

  test.afterAll(async ({ api }) => {
    if (projectId) await api.raw('DELETE', `/projects/${projectId}`).catch(() => undefined);
    await req?.dispose();
  });

  async function newBoq(name: string): Promise<string> {
    const res = await req.post(v1('/boq/boqs/'), {
      headers: auth,
      data: { project_id: projectId, name },
    });
    expect(res.status(), await res.text()).toBe(201);
    return ((await res.json()) as Boq).id;
  }

  async function upload(boqId: string, route: string, name: string, buffer: Buffer) {
    return req.post(v1(`/boq/boqs/${boqId}/${route}`), {
      headers: auth,
      multipart: { file: { name, mimeType: 'application/octet-stream', buffer } },
    });
  }

  async function apiTotal(boqId: string): Promise<number> {
    const res = await req.get(v1(`/boq/boqs/${boqId}/cost-breakdown/`), { headers: auth });
    expect(res.ok()).toBeTruthy();
    return Number(((await res.json()) as CostBreakdown).grand_total);
  }

  async function positionCount(boqId: string): Promise<number> {
    const res = await req.get(v1(`/boq/boqs/${boqId}`), { headers: auth });
    expect(res.ok()).toBeTruthy();
    return ((await res.json()) as BoqWithPositions).positions.length;
  }

  async function download(boqId: string, kind: string): Promise<Buffer> {
    const res = await req.get(v1(`/boq/boqs/${boqId}/export/${kind}`), { headers: auth });
    expect(res.status(), `export ${kind}`).toBe(200);
    const body = await res.body();
    expect(body.length, `export ${kind} is empty`).toBeGreaterThan(0);
    return body;
  }

  for (const fx of [
    { label: 'XPWE', file: 'computo.xpwe', buffer: XPWE },
    { label: 'GAEB X83', file: 'lv.x83', buffer: X83 },
  ]) {
    test(`${fx.label}: import, screen total, exports, round trip`, async ({ page }) => {
      const boqId = await newBoq(`E2E ${fx.label}`);
      const imp = await upload(boqId, 'import/auto/', fx.file, fx.buffer);
      expect(imp.status(), await imp.text()).toBe(200);
      expect(await positionCount(boqId)).toBeGreaterThan(0);

      const serverTotal = await apiTotal(boqId);

      await page.goto(`/boq/${boqId}`);
      const totalEl = page.getByTestId('boq-grand-total');
      await expect(totalEl).not.toHaveText('—', { timeout: 30_000 });
      const screenTotal = parseMoney((await totalEl.textContent()) ?? '');
      expect(screenTotal).toBeCloseTo(serverTotal, 2);

      await download(boqId, 'gaeb');
      await download(boqId, 'pdf');
      const xlsx = await download(boqId, 'excel');

      const wb = new ExcelJS.Workbook();
      await wb.xlsx.load(new Uint8Array(xlsx).buffer);
      let sheetTotal: number | null = null;
      const ws = wb.worksheets[0];
      expect(ws, 'XLSX has no sheet').toBeTruthy();
      ws?.eachRow((row) => {
        if (String(row.getCell(2).value ?? '').trim() === 'Grand Total') {
          sheetTotal = Number(row.getCell(6).value);
        }
      });
      expect(sheetTotal, 'XLSX has no Grand Total row').not.toBeNull();
      expect(sheetTotal as unknown as number).toBeCloseTo(screenTotal, 2);

      // X84 carries prices; an X83 is a call for tender and would round-trip to zero.
      const x84 = await download(boqId, 'gaeb?format=x84');
      const again = await newBoq(`E2E ${fx.label} round trip`);
      const re = await upload(again, 'import/auto/', 'roundtrip.x84', x84);
      expect(re.status(), await re.text()).toBe(200);
      expect(await apiTotal(again)).toBeCloseTo(serverTotal, 2);
    });
  }

  test('truncated GAEB upload is refused and leaves the bill unchanged', async ({ page }) => {
    const boqId = await newBoq('E2E truncated');
    expect((await upload(boqId, 'import/auto/', 'lv.x83', X83)).status()).toBe(200);
    const before = await positionCount(boqId);

    await page.goto(`/boq/${boqId}`);
    await expect(page.getByTestId('boq-grand-total')).not.toHaveText('—', { timeout: 30_000 });

    // Upload the cut file through the editor's own import so the UI error path is exercised.
    const cut = X83.subarray(0, Math.floor(X83.length * 0.6));
    const res = page.waitForResponse((r) => r.url().includes(`/boqs/${boqId}/import/`) && r.request().method() === 'POST');
    await page.locator('input[type="file"]').first().setInputFiles({
      name: 'cut.x83',
      mimeType: 'application/xml',
      buffer: cut,
    });
    const answered = await res;
    expect(answered.status()).toBeGreaterThanOrEqual(400);
    // Toasts render with role="alert" (shared/ui/Toast.tsx).
    await expect(page.getByRole('alert').first()).toBeVisible();

    expect(await positionCount(boqId)).toBe(before);
  });
});
