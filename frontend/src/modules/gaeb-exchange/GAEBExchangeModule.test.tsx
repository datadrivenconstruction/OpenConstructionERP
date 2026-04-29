// @ts-nocheck
import { describe, it, expect } from 'vitest';
import {
  generateGAEBXML,
  toGaebUnitCode,
  fromGaebUnitCode,
  type ExportPosition,
  type GAEBExportOptions,
} from './data/gaebExport';
import { parseGAEBXML } from '@/features/boq/gaebImport';

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const samplePositions: ExportPosition[] = [
  {
    id: 'sec-1',
    ordinal: '01',
    description: 'Erdarbeiten',
    unit: '',
    quantity: 0,
    unitRate: 0,
    total: 0,
    isSection: true,
  },
  {
    id: 'pos-1',
    ordinal: '01.001',
    description: 'Baugrubenaushub, Boden DIN 18300 Kl.3-5, maschinell',
    unit: 'm3',
    quantity: 350.5,
    unitRate: 18.50,
    total: 6484.25,
    section: 'Erdarbeiten',
  },
  {
    id: 'pos-2',
    ordinal: '01.002',
    description: 'Bodenabtransport, inkl. Deponiegebühren',
    unit: 'm3',
    quantity: 420,
    unitRate: 24.00,
    total: 10080,
    section: 'Erdarbeiten',
  },
  {
    id: 'sec-2',
    ordinal: '02',
    description: 'Betonarbeiten',
    unit: '',
    quantity: 0,
    unitRate: 0,
    total: 0,
    isSection: true,
  },
  {
    id: 'pos-3',
    ordinal: '02.001',
    description: 'Stahlbeton C30/37 für Fundamente, inkl. Schalung',
    unit: 'm3',
    quantity: 85,
    unitRate: 380,
    total: 32300,
    section: 'Betonarbeiten',
  },
];

function makeOptions(overrides?: Partial<GAEBExportOptions>): GAEBExportOptions {
  return {
    format: 'X83',
    projectName: 'Testprojekt Berlin',
    boqName: 'Hauptangebot LV',
    currency: 'EUR',
    positions: samplePositions,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('generateGAEBXML', () => {
  it('generates valid XML structure with XML header', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<?xml version="1.0" encoding="UTF-8"?>');
    expect(result.xml).toContain('<GAEB');
    expect(result.xml).toContain('</GAEB>');
  });

  it('includes GAEBInfo with VersMajor/VersMinor 3.3 (spec-compliant)', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<VersMajor>3</VersMajor>');
    expect(result.xml).toContain('<VersMinor>3</VersMinor>');
    expect(result.xml).toContain('<ProgSystem>OpenEstimate</ProgSystem>');
  });

  it('includes project info', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<NamePrj>Testprojekt Berlin</NamePrj>');
    expect(result.xml).toContain('<Cur>EUR</Cur>');
  });

  it('generates X83 format with Award tag and prices', () => {
    const result = generateGAEBXML(makeOptions({ format: 'X83' }));
    expect(result.xml).toContain('<Award>');
    expect(result.xml).toContain('</Award>');
    expect(result.xml).toContain('<UP>');
    expect(result.xml).toContain('<IT>');
  });

  it('generates X81 format with Tender tag and no prices', () => {
    const result = generateGAEBXML(makeOptions({ format: 'X81' }));
    expect(result.xml).toContain('<Tender>');
    expect(result.xml).toContain('</Tender>');
    expect(result.xml).not.toContain('<UP>');
    expect(result.xml).not.toContain('<IT>');
  });

  it('exports correct number of positions and sections', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.positionCount).toBe(3); // 3 non-section positions
    expect(result.sectionCount).toBe(2);  // 2 sections
  });

  it('includes position descriptions', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('Baugrubenaushub');
    expect(result.xml).toContain('Stahlbeton C30/37');
  });

  it('includes quantities and units (with GAEB-DA short codes)', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<Qty>350.500</Qty>');
    // Internal "m3" should be mapped to GAEB-DA short code "m³"
    expect(result.xml).toContain('<QU>m³</QU>');
    expect(result.xml).not.toContain('<QU>m3</QU>');
  });

  it('includes section labels as BoQCtgy with LblTx', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<BoQCtgy');
    expect(result.xml).toContain('<LblTx>Erdarbeiten</LblTx>');
    expect(result.xml).toContain('<LblTx>Betonarbeiten</LblTx>');
  });

  it('generates correct filename for X83', () => {
    const result = generateGAEBXML(makeOptions({ format: 'X83' }));
    expect(result.filename).toMatch(/\.x83$/);
  });

  it('generates correct filename for X81', () => {
    const result = generateGAEBXML(makeOptions({ format: 'X81' }));
    expect(result.filename).toMatch(/\.x81$/);
  });

  it('escapes XML special characters in descriptions', () => {
    const positionsWithSpecialChars: ExportPosition[] = [
      {
        id: 'pos-special',
        ordinal: '01.001',
        description: 'Wall > 2m & "thick" <special>',
        unit: 'm2',
        quantity: 10,
        unitRate: 100,
        total: 1000,
      },
    ];
    const result = generateGAEBXML(makeOptions({ positions: positionsWithSpecialChars }));
    expect(result.xml).toContain('&gt;');
    expect(result.xml).toContain('&amp;');
    expect(result.xml).toContain('&quot;');
    expect(result.xml).toContain('&lt;');
  });

  it('handles empty positions list', () => {
    const result = generateGAEBXML(makeOptions({ positions: [] }));
    expect(result.positionCount).toBe(0);
    expect(result.xml).toContain('<GAEB');
    expect(result.xml).toContain('</GAEB>');
  });

  it('includes AwardInfo with bidder details in X83', () => {
    const result = generateGAEBXML(
      makeOptions({
        format: 'X83',
        awardInfo: { bidderName: 'Baufirma GmbH', bidderCity: '10115 Berlin' },
      }),
    );
    expect(result.xml).toContain('<AwardInfo>');
    expect(result.xml).toContain('<Name1>Baufirma GmbH</Name1>');
    expect(result.xml).toContain('<PCode>10115 Berlin</PCode>');
  });

  it('includes ShortText (truncated to 70 chars)', () => {
    const longDesc = 'A'.repeat(100);
    const positions: ExportPosition[] = [
      { id: '1', ordinal: '01', description: longDesc, unit: 'm', quantity: 1, unitRate: 1, total: 1 },
    ];
    const result = generateGAEBXML(makeOptions({ positions }));
    expect(result.xml).toContain('<ShortText>');
    // ShortText should be truncated
    const shortTextMatch = result.xml.match(/<ShortText>(.*?)<\/ShortText>/);
    expect(shortTextMatch).not.toBeNull();
    expect(shortTextMatch![1].length).toBeLessThanOrEqual(70);
  });

  it('includes BoQ name in BoQInfo', () => {
    const result = generateGAEBXML(makeOptions());
    expect(result.xml).toContain('<Name>Hauptangebot LV</Name>');
    expect(result.xml).toContain('<LblBoQ>Hauptangebot LV</LblBoQ>');
  });

  // ── New: filename includes project name ────────────────────────────────
  it('emits a filename with both project and BOQ name', () => {
    const result = generateGAEBXML(makeOptions());
    // safeProject: "Testprojekt_Berlin", safeBoq: "Hauptangebot_LV"
    expect(result.filename).toBe('Testprojekt_Berlin-Hauptangebot_LV.x83');
  });

  // ── New: Unit codes — internal -> GAEB-DA short codes ──────────────────
  it('maps internal canonical units to GAEB-DA short codes on export', () => {
    const positions: ExportPosition[] = [
      { id: 'a', ordinal: '01.001', description: 'Wall', unit: 'm2', quantity: 10, unitRate: 1, total: 10 },
      { id: 'b', ordinal: '01.002', description: 'Concrete', unit: 'm3', quantity: 5, unitRate: 1, total: 5 },
      { id: 'c', ordinal: '01.003', description: 'Doors', unit: 'pcs', quantity: 3, unitRate: 1, total: 3 },
      { id: 'd', ordinal: '01.004', description: 'Cleaning', unit: 'lsum', quantity: 1, unitRate: 1, total: 1 },
      { id: 'e', ordinal: '01.005', description: 'Labour', unit: 'hr', quantity: 8, unitRate: 1, total: 8 },
      { id: 'f', ordinal: '01.006', description: 'Travel', unit: 'day', quantity: 2, unitRate: 1, total: 2 },
    ];
    const result = generateGAEBXML(makeOptions({ positions }));
    expect(result.xml).toContain('<QU>m²</QU>');
    expect(result.xml).toContain('<QU>m³</QU>');
    expect(result.xml).toContain('<QU>Stk</QU>');
    expect(result.xml).toContain('<QU>psch</QU>');
    expect(result.xml).toContain('<QU>Std</QU>');
    expect(result.xml).toContain('<QU>Tag</QU>');
  });

  it('round-trips GAEB-DA short codes back to canonical units', () => {
    expect(fromGaebUnitCode('m²')).toBe('m2');
    expect(fromGaebUnitCode('m³')).toBe('m3');
    expect(fromGaebUnitCode('Stk')).toBe('pcs');
    expect(fromGaebUnitCode('psch')).toBe('lsum');
    expect(fromGaebUnitCode('Std')).toBe('hr');
    expect(fromGaebUnitCode('Tag')).toBe('day');
  });

  it('forwards unknown units verbatim instead of corrupting them', () => {
    expect(toGaebUnitCode('бр')).toBe('бр');
    expect(toGaebUnitCode('个')).toBe('个');
    expect(toGaebUnitCode('')).toBe('Stk'); // empty -> default
  });

  // ── New: Hierarchy preservation — multi-level (Los → Titel → Position) ─
  it('preserves multi-level hierarchy on export (Los → Titel → Position)', () => {
    const positions: ExportPosition[] = [
      { id: 's1', ordinal: '01', description: 'Los 1 — Rohbau', unit: '', quantity: 0, unitRate: 0, total: 0, isSection: true },
      { id: 's2', ordinal: '01.01', description: 'Titel 1.1 — Erdarbeiten', unit: '', quantity: 0, unitRate: 0, total: 0, isSection: true },
      { id: 'p1', ordinal: '01.01.001', description: 'Aushub', unit: 'm3', quantity: 100, unitRate: 12, total: 1200 },
      { id: 's3', ordinal: '01.02', description: 'Titel 1.2 — Beton', unit: '', quantity: 0, unitRate: 0, total: 0, isSection: true },
      { id: 'p2', ordinal: '01.02.001', description: 'C30/37', unit: 'm3', quantity: 50, unitRate: 220, total: 11000 },
    ];
    const result = generateGAEBXML(makeOptions({ positions }));
    // Verify nesting structure: Los 1 BoQCtgy contains Titel BoQCtgy children
    const losStart = result.xml.indexOf('<LblTx>Los 1 — Rohbau</LblTx>');
    const titel11 = result.xml.indexOf('<LblTx>Titel 1.1 — Erdarbeiten</LblTx>');
    const titel12 = result.xml.indexOf('<LblTx>Titel 1.2 — Beton</LblTx>');
    expect(losStart).toBeGreaterThan(0);
    expect(titel11).toBeGreaterThan(losStart);
    expect(titel12).toBeGreaterThan(titel11);
    // Re-parse and verify positions still carry their original ordinals
    const parsed = parseGAEBXML(result.xml);
    expect(parsed.length).toBe(2);
    expect(parsed.find((p) => p.description === 'Aushub')?.ordinal).toBe('01.01.001');
    expect(parsed.find((p) => p.description === 'C30/37')?.ordinal).toBe('01.02.001');
  });

  // ── New: Multi-paragraph descriptions round-trip ───────────────────────
  it('emits multi-paragraph descriptions as separate <Text> nodes', () => {
    const positions: ExportPosition[] = [
      {
        id: 'p1',
        ordinal: '01.001',
        description: 'Para 1: scope.\nPara 2: standards.\nPara 3: acceptance.',
        unit: 'm2',
        quantity: 10,
        unitRate: 50,
        total: 500,
      },
    ];
    const result = generateGAEBXML(makeOptions({ positions }));
    // Three Text elements
    const textMatches = result.xml.match(/<Text>[^<]*<\/Text>/g) ?? [];
    expect(textMatches.length).toBe(3);
    // Round-trip through parser preserves structure
    const parsed = parseGAEBXML(result.xml);
    expect(parsed[0].description.split('\n').length).toBe(3);
    expect(parsed[0].description).toContain('Para 1: scope.');
    expect(parsed[0].description).toContain('Para 3: acceptance.');
  });

  // ── New: Round-trip of special XML characters in description ──────────
  it('round-trips XML special characters in descriptions', () => {
    const positions: ExportPosition[] = [
      {
        id: 'p1',
        ordinal: '01.001',
        description: 'Wall > 2m & "tested" <special> apostrophe\'s',
        unit: 'm2',
        quantity: 10,
        unitRate: 50,
        total: 500,
      },
    ];
    const result = generateGAEBXML(makeOptions({ positions }));
    const parsed = parseGAEBXML(result.xml);
    expect(parsed[0].description).toBe('Wall > 2m & "tested" <special> apostrophe\'s');
  });

  // ── New: ShortText doesn't break on multi-paragraph descriptions ────────
  it('uses only first paragraph for ShortText (truncated to 70 chars)', () => {
    const positions: ExportPosition[] = [
      {
        id: 'p1',
        ordinal: '01.001',
        description: 'First short paragraph.\nLong second paragraph with lots of additional context.',
        unit: 'm',
        quantity: 1,
        unitRate: 1,
        total: 1,
      },
    ];
    const result = generateGAEBXML(makeOptions({ positions }));
    const m = result.xml.match(/<ShortText>(.*?)<\/ShortText>/);
    expect(m).not.toBeNull();
    expect(m![1]).toBe('First short paragraph.');
  });

  // ── New: X81 uses DA81 namespace ────────────────────────────────────────
  it('uses DA81 namespace for X81 export', () => {
    const result = generateGAEBXML(makeOptions({ format: 'X81' }));
    expect(result.xml).toContain('http://www.gaeb.de/GAEB_DA_XML/DA81/3.3');
  });
});
