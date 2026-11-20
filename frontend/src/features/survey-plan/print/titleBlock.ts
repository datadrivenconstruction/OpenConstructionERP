// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Title block of the printed plan. The company header comes from the same
 * source as every PDF report (the project's legal entity over the company
 * profile), served by `GET survey_core/projects/{id}/plan-title-block`.
 */

import type { jsPDF } from 'jspdf';
import { apiGet } from '@/shared/lib/api';
import { drawText, type Rect } from './pdfPlan';

export interface TitleBlockServer {
  company: { legal_name: string; address: string; registration_line: string; logo_data_url: string };
  project_name: string;
  project_code: string;
  epsg: number | null;
  crs_name: string;
  is_local_grid: boolean;
  author: string;
  date: string;
  paper: string;
  papers: string[];
  scales: number[];
  convergence_deg: number | null;
}

export function fetchTitleBlock(projectId: string, centre?: [number, number] | null): Promise<TitleBlockServer> {
  const q = centre ? `?e=${centre[0]}&n=${centre[1]}` : '';
  return apiGet<TitleBlockServer>(`/v1/survey-core/projects/${projectId}/plan-title-block${q}`);
}

/** What the title block prints: the server header plus what the user typed in the print dialog. */
export interface TitleBlockData {
  company: TitleBlockServer['company'];
  projectName: string;
  projectCode: string;
  title: string;
  drawingNo: string;
  revision: string;
  crs: string;
  author: string;
  date: string;
}

export function titleBlockData(server: TitleBlockServer, input: { title: string; drawingNo: string; revision: string }, t: (k: string, o?: Record<string, unknown>) => string): TitleBlockData {
  const crs = server.is_local_grid || !server.epsg
    ? t('plan.print.local_grid', { defaultValue: 'Local site grid' })
    : `EPSG:${server.epsg}${server.crs_name ? ` ${server.crs_name}` : ''}`;
  return {
    company: server.company,
    projectName: server.project_name,
    projectCode: server.project_code,
    title: input.title,
    drawingNo: input.drawingNo,
    revision: input.revision,
    crs,
    author: server.author,
    date: server.date,
  };
}

/** Rows of the block as label/value pairs, in print order. */
export function titleRows(d: TitleBlockData, scale: number, t: (k: string, o?: Record<string, unknown>) => string): Array<[string, string]> {
  return [
    [t('plan.print.project', { defaultValue: 'Project' }), [d.projectCode, d.projectName].filter(Boolean).join(' ')],
    [t('plan.print.drawing_title', { defaultValue: 'Title' }), d.title],
    [t('plan.print.drawing_no', { defaultValue: 'Drawing no.' }), d.drawingNo],
    [t('plan.print.revision', { defaultValue: 'Revision' }), d.revision],
    [t('plan.print.scale', { defaultValue: 'Scale' }), `1:${scale}`],
    [t('plan.print.crs', { defaultValue: 'Coordinate system' }), d.crs],
    [t('plan.print.drawn_by', { defaultValue: 'Drawn by' }), d.author],
    [t('plan.print.date', { defaultValue: 'Date' }), d.date],
  ];
}

/** Wraps text to lines no wider than `maxMm` with the estimate `mmPerChar`. */
export function wrap(text: string, maxMm: number, mmPerChar: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let cur = '';
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w;
    if (next.length * mmPerChar > maxMm && cur) {
      lines.push(cur);
      cur = w;
    } else cur = next;
  }
  if (cur) lines.push(cur);
  return lines;
}

/** Draws the block at the top of the title column; returns the height used, mm. */
export function drawTitleBlock(doc: jsPDF, r: Rect, d: TitleBlockData, t: (k: string, o?: Record<string, unknown>) => string, scale: number): number {
  const x = r.x + 3;
  const w = r.w - 6;
  let y = r.y + 4;
  doc.setTextColor(29, 29, 31);
  if (d.company.logo_data_url) {
    try {
      const fmt = d.company.logo_data_url.startsWith('data:image/jpeg') ? 'JPEG' : 'PNG';
      doc.addImage(d.company.logo_data_url, fmt, x, y, 18, 9);
      y += 11;
    } catch {
      // An unreadable logo never blocks the print.
    }
  }
  for (const line of wrap(d.company.legal_name, w, 1.6)) {
    drawText(doc, line, x, y + 3, 8, { bold: true });
    y += 3.6;
  }
  for (const line of [...wrap(d.company.address, w, 1.25), ...wrap(d.company.registration_line, w, 1.25)]) {
    drawText(doc, line, x, y + 3, 6);
    y += 2.8;
  }
  y += 2;
  doc.setDrawColor(29, 29, 31);
  doc.setLineWidth(0.25);
  doc.line(r.x, y, r.x + r.w, y);
  y += 1;
  for (const [label, value] of titleRows(d, scale, t)) {
    drawText(doc, label, x, y + 2.6, 5.5);
    const lines = wrap(value || '-', w, 1.45);
    for (const line of lines) {
      drawText(doc, line, x, y + 5.8, 7);
      y += 3;
    }
    y += 3.6;
    doc.setLineWidth(0.1);
    doc.line(r.x, y, r.x + r.w, y);
  }
  return y - r.y;
}
