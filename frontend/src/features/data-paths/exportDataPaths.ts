// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Export of one module's data paths without a new dependency: a standalone SVG
// drawn from the flow model with the theme's colours inlined at export time,
// a PNG made by drawing that SVG on a 2x canvas, and a CSV of the List tab.

import { formatNumber } from '@/shared/lib/formatters';

import type { FlowCard, FlowModel } from './flowModel';
import { listRows } from './flowModel';

export interface ExportColors {
  surface: string;
  border: string;
  text: string;
  muted: string;
  accent: string;
  warning: string;
  error: string;
}

/** Resolve the theme tokens the export needs; jsdom and old engines fall back to neutral greys. */
export function themeColors(root: Element = document.documentElement): ExportColors {
  const css = getComputedStyle(root);
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  return {
    surface: v('--oe-bg', '#ffffff'),
    border: v('--oe-border', '#d4d4d8'),
    text: v('--oe-text-primary', '#18181b'),
    muted: v('--oe-text-tertiary', '#71717a'),
    accent: v('--oe-blue', '#2563eb'),
    warning: v('--oe-warning', '#b45309'),
    error: v('--oe-error', '#b91c1c'),
  };
}

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

const W = 960;
const COL = 260;
const CARD_H = 64;
const GAP = 14;

function cardSvg(c: FlowCard, x: number, y: number, col: ExportColors): string {
  const stroke = c.state === 'broken' || c.state === 'not_installed' ? col.error : c.state === 'stale' ? col.warning : col.border;
  const line2 = c.count !== null ? `${formatNumber(c.count)}${c.valueText ? `  ·  ${c.valueText}` : ''}` : c.entityLabel;
  return [
    `<rect x="${x}" y="${y}" width="${COL}" height="${CARD_H}" rx="10" fill="${col.surface}" stroke="${stroke}"/>`,
    `<text x="${x + 12}" y="${y + 24}" font-size="13" font-weight="600" fill="${col.text}">${esc(c.moduleLabel)}</text>`,
    `<text x="${x + 12}" y="${y + 46}" font-size="12" fill="${col.muted}">${esc(line2)}</text>`,
  ].join('');
}

/** A standalone SVG document of the three-column picture. */
export function buildFlowSvg(model: FlowModel, col: ExportColors): string {
  const rows = Math.max(model.inputs.length, model.outputs.length, 1);
  const centreH = 48 + model.entities.length * 26 + (model.params.length ? 24 + model.params.length * 22 : 0);
  const height = Math.max(rows * (CARD_H + GAP), centreH) + 80;
  const cx = (W - COL * 1.4) / 2;
  const cw = COL * 1.4;
  const top = 56;
  const parts: string[] = [];
  parts.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${height}" viewBox="0 0 ${W} ${height}" font-family="Inter, system-ui, sans-serif">`,
    `<rect width="100%" height="100%" fill="${col.surface}"/>`,
    `<text x="24" y="32" font-size="16" font-weight="600" fill="${col.text}">${esc(model.moduleLabel)}</text>`,
  );
  const centreMid = top + centreH / 2;
  model.inputs.forEach((c, i) => {
    const y = top + i * (CARD_H + GAP);
    parts.push(cardSvg(c, 24, y, col));
    const dash = c.state === 'stale' ? ' stroke-dasharray="6 4"' : '';
    parts.push(
      `<path d="M ${24 + COL} ${y + CARD_H / 2} C ${cx - 40} ${y + CARD_H / 2}, ${cx - 40} ${centreMid}, ${cx} ${centreMid}" fill="none" stroke="${col.accent}" stroke-opacity="0.6" stroke-width="1.5"${dash}/>`,
    );
  });
  model.outputs.forEach((c, i) => {
    const y = top + i * (CARD_H + GAP);
    const x = W - 24 - COL;
    parts.push(cardSvg(c, x, y, col));
    const dash = c.state === 'stale' ? ' stroke-dasharray="6 4"' : '';
    parts.push(
      `<path d="M ${cx + cw} ${centreMid} C ${x + 40 - 80} ${centreMid}, ${x - 40} ${y + CARD_H / 2}, ${x} ${y + CARD_H / 2}" fill="none" stroke="${col.accent}" stroke-opacity="0.6" stroke-width="1.5"${dash}/>`,
    );
  });
  parts.push(`<rect x="${cx}" y="${top}" width="${cw}" height="${centreH}" rx="12" fill="${col.surface}" stroke="${col.accent}"/>`);
  parts.push(`<text x="${cx + 14}" y="${top + 28}" font-size="14" font-weight="600" fill="${col.text}">${esc(model.moduleLabel)}</text>`);
  model.entities.forEach((e, i) => {
    const y = top + 52 + i * 26;
    const value = [e.count !== null ? formatNumber(e.count) : '', e.valueText ?? ''].filter(Boolean).join('  ·  ');
    parts.push(`<text x="${cx + 14}" y="${y}" font-size="12" fill="${col.muted}">${esc(e.label)}</text>`);
    parts.push(`<text x="${cx + cw - 14}" y="${y}" font-size="12" text-anchor="end" fill="${col.text}">${esc(value)}</text>`);
  });
  model.params.forEach((p, i) => {
    const y = top + 52 + model.entities.length * 26 + 18 + i * 22;
    parts.push(`<text x="${cx + 14}" y="${y}" font-size="11" fill="${col.accent}">${esc(p.label)}</text>`);
  });
  parts.push('</svg>');
  return parts.join('');
}

export function buildCsv(model: FlowModel, headers: { section: string; text: string; link: string }, sections: Record<'in' | 'centre' | 'out', string>): string {
  const q = (s: string) => `"${s.replace(/"/g, '""')}"`;
  const lines = [[headers.section, headers.text, headers.link].map(q).join(',')];
  for (const r of listRows(model)) lines.push([sections[r.section], r.text, r.href].map(q).join(','));
  return `﻿${lines.join('\r\n')}\r\n`;
}

export function download(name: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Draw the SVG on a canvas at 2x and save it as PNG. */
export async function svgToPng(svg: string, scale = 2): Promise<Blob> {
  const img = new Image();
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }));
  try {
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error('svg render failed'));
      img.src = url;
    });
    const canvas = document.createElement('canvas');
    canvas.width = img.width * scale;
    canvas.height = img.height * scale;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('no canvas');
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('png encode failed'))), 'image/png'),
    );
  } finally {
    URL.revokeObjectURL(url);
  }
}
