#!/usr/bin/env node
/**
 * Render the raster app icons from the brand-kit SVGs (never redraw the mark).
 *
 *   node frontend/scripts/build-brand-icons.mjs
 *
 * Source: frontend/public/brand/erp/erp-appicon-512.svg and the favicon SVGs,
 * copied unmodified from the brand kit. Uses the Playwright Chromium already
 * installed for e2e, so no new dependency.
 *
 * Writes:
 *   frontend/public/pwa/icon-{192,256,384,512}.png, icon-maskable-512.png
 *   frontend/public/apple-touch-icon.png (180), frontend/public/favicon.ico
 *   desktop/src-tauri/icons: every existing PNG re-rendered at its own size,
 *   icon.ico (16-256) and icon.icns (16-1024).
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const here = path.dirname(fileURLToPath(import.meta.url));
const front = path.resolve(here, '..');
const brand = path.join(front, 'public', 'brand', 'erp');
const tauriIcons = path.resolve(front, '..', 'desktop', 'src-tauri', 'icons');
const INK = '#181B1F';

const dataUrl = async (file) =>
  `data:image/svg+xml;base64,${(await fs.readFile(path.join(brand, file))).toString('base64')}`;

async function renderer() {
  // PW_CHANNEL=msedge or chrome reuses an installed browser when Playwright's own is missing.
  const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined });
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  // `scale` < 1 centres the icon on a full-bleed ink plate (maskable safe zone).
  const render = async (src, size, { scale = 1, plate = null } = {}) => {
    const inner = Math.round(size * scale);
    await page.setViewportSize({ width: size, height: size });
    await page.setContent(
      `<html><body style="margin:0;width:${size}px;height:${size}px;display:flex;align-items:center;` +
        `justify-content:center;background:${plate ?? 'transparent'}">` +
        `<img src="${src}" width="${inner}" height="${inner}"></body></html>`,
    );
    await page.waitForFunction(() => document.images[0]?.complete);
    return page.screenshot({ omitBackground: !plate, clip: { x: 0, y: 0, width: size, height: size } });
  };
  return { render, close: () => browser.close() };
}

function ico(entries) {
  const head = Buffer.alloc(6 + 16 * entries.length);
  head.writeUInt16LE(1, 2);
  head.writeUInt16LE(entries.length, 4);
  let offset = head.length;
  entries.forEach(([size, png], i) => {
    const o = 6 + 16 * i;
    head.writeUInt8(size >= 256 ? 0 : size, o);
    head.writeUInt8(size >= 256 ? 0 : size, o + 1);
    head.writeUInt16LE(1, o + 4);
    head.writeUInt16LE(32, o + 6);
    head.writeUInt32LE(png.length, o + 8);
    head.writeUInt32LE(offset, o + 12);
    offset += png.length;
  });
  return Buffer.concat([head, ...entries.map(([, png]) => png)]);
}

function icns(entries) {
  const chunks = entries.map(([type, png]) => {
    const h = Buffer.alloc(8);
    h.write(type, 0, 'ascii');
    h.writeUInt32BE(png.length + 8, 4);
    return Buffer.concat([h, png]);
  });
  const total = 8 + chunks.reduce((n, c) => n + c.length, 0);
  const h = Buffer.alloc(8);
  h.write('icns', 0, 'ascii');
  h.writeUInt32BE(total, 4);
  return Buffer.concat([h, ...chunks]);
}

async function pngSize(file) {
  const b = await fs.readFile(file);
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

async function walkPngs(dir) {
  const out = [];
  for (const e of await fs.readdir(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...(await walkPngs(p)));
    else if (e.name.endsWith('.png')) out.push(p);
  }
  return out;
}

const r = await renderer();
try {
  const app = await dataUrl('erp-appicon-512.svg');
  const pwa = path.join(front, 'public', 'pwa');
  await fs.mkdir(pwa, { recursive: true });
  for (const s of [192, 256, 384, 512]) await fs.writeFile(path.join(pwa, `icon-${s}.png`), await r.render(app, s));
  await fs.writeFile(path.join(pwa, 'icon-maskable-512.png'), await r.render(app, 512, { scale: 0.75, plate: INK }));
  await fs.writeFile(path.join(front, 'public', 'apple-touch-icon.png'), await r.render(app, 180, { plate: INK, scale: 1 }));

  const fav16 = await dataUrl('erp-favicon-16-light.svg');
  const fav32 = await dataUrl('erp-favicon-32-light.svg');
  await fs.writeFile(
    path.join(front, 'public', 'favicon.ico'),
    ico([[16, await r.render(fav16, 16)], [32, await r.render(fav32, 32)], [48, await r.render(fav32, 48)]]),
  );

  for (const file of await walkPngs(tauriIcons)) {
    const [w, h] = await pngSize(file);
    if (w !== h) continue;
    await fs.writeFile(file, await r.render(app, w));
  }
  const at = async (s) => r.render(app, s);
  const icoEntries = [];
  for (const s of [16, 24, 32, 48, 64, 256]) icoEntries.push([s, await at(s)]);
  await fs.writeFile(path.join(tauriIcons, 'icon.ico'), ico(icoEntries));
  const icnsTypes = [['icp4', 16], ['icp5', 32], ['icp6', 64], ['ic07', 128], ['ic08', 256], ['ic09', 512], ['ic10', 1024],
    ['ic11', 32], ['ic12', 64], ['ic13', 256], ['ic14', 512]];
  const icnsEntries = [];
  for (const [type, s] of icnsTypes) icnsEntries.push([type, await at(s)]);
  await fs.writeFile(path.join(tauriIcons, 'icon.icns'), icns(icnsEntries));
  console.log('brand icons written');
} finally {
  await r.close();
}
