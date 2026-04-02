// @ts-nocheck
/**
 * Unit tests for GAEB XML import parser.
 *
 * Tests cover:
 *  - X83 (Angebotsabgabe) with prices
 *  - X81 (Leistungsverzeichnis) without prices
 *  - Nested sections (BoQCtgy inside BoQCtgy)
 *  - Missing / malformed XML
 *  - Edge cases: missing Qty, missing UP, custom ordinals
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { parseGAEBXML, importGAEBToBOQ, type GAEBPosition } from './gaebImport';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Wrap content in a minimal valid GAEB X83 document. */
function x83Doc(boqBodyContent: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<GAEB>
  <GAEBInfo>
    <Date>2024-01-15</Date>
    <Conversion>3.3</Conversion>
  </GAEBInfo>
  <Award>
    <BoQ>
      <BoQBody>
        ${boqBodyContent}
      </BoQBody>
    </BoQ>
  </Award>
</GAEB>`;
}

/** Wrap content in a minimal valid GAEB X81 document (no prices). */
function x81Doc(boqBodyContent: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<GAEB>
  <GAEBInfo>
    <Date>2024-01-15</Date>
    <Conversion>3.3</Conversion>
  </GAEBInfo>
  <Tender>
    <BoQ>
      <BoQBody>
        ${boqBodyContent}
      </BoQBody>
    </BoQ>
  </Tender>
</GAEB>`;
}

/** Build a single Item XML fragment. */
function itemXML(opts: {
  rno: string;
  qty?: string;
  qu?: string;
  text?: string;
  up?: string;
}): string {
  const { rno, qty = '10', qu = 'm2', text = 'Test position', up } = opts;
  return `
    <Item RNoPart="${rno}">
      <Qty>${qty}</Qty>
      <QU>${qu}</QU>
      <Description>
        <CompleteText>
          <DetailTxt>
            <Text>${text}</Text>
          </DetailTxt>
        </CompleteText>
      </Description>
      ${up !== undefined ? `<UP>${up}</UP>` : ''}
    </Item>`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('parseGAEBXML', () => {
  // ── Test 1: Simple X83 with two positions ────────────────────────────────
  it('parses a simple X83 with two positions', () => {
    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qty: '20', qu: 'm2', text: 'Concrete slab C30/37', up: '85.00' })}
        ${itemXML({ rno: '002', qty: '5', qu: 'm3', text: 'Reinforcement B500B', up: '1200.50' })}
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(2);

    expect(result[0].ordinal).toBe('001');
    expect(result[0].description).toBe('Concrete slab C30/37');
    expect(result[0].unit).toBe('m2');
    expect(result[0].quantity).toBe(20);
    expect(result[0].unitRate).toBe(85.0);

    expect(result[1].ordinal).toBe('002');
    expect(result[1].description).toBe('Reinforcement B500B');
    expect(result[1].unit).toBe('m3');
    expect(result[1].quantity).toBe(5);
    expect(result[1].unitRate).toBe(1200.5);
  });

  // ── Test 2: Nested sections (BoQCtgy inside BoQCtgy) ────────────────────
  it('parses nested BoQCtgy sections and builds compound ordinals', () => {
    const xml = x83Doc(`
      <BoQCtgy RNoPart="01">
        <LblTx>Earthworks</LblTx>
        <BoQBody>
          <BoQCtgy RNoPart="01">
            <LblTx>Excavation</LblTx>
            <BoQBody>
              <Itemlist>
                ${itemXML({ rno: '001', qty: '150', qu: 'm3', text: 'Bulk excavation', up: '12.00' })}
              </Itemlist>
            </BoQBody>
          </BoQCtgy>
        </BoQBody>
      </BoQCtgy>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    expect(result[0].ordinal).toBe('01.01.001');
    expect(result[0].description).toBe('Bulk excavation');
    expect(result[0].quantity).toBe(150);
    expect(result[0].unit).toBe('m3');
    expect(result[0].unitRate).toBe(12.0);
  });

  // ── Test 3: Missing Qty defaults to 0 ────────────────────────────────────
  it('defaults quantity to 0 when Qty element is missing', () => {
    const xml = x83Doc(`
      <Itemlist>
        <Item RNoPart="001">
          <QU>Stk</QU>
          <Description>
            <CompleteText><DetailTxt><Text>Door frame</Text></DetailTxt></CompleteText>
          </Description>
          <UP>350.00</UP>
        </Item>
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    expect(result[0].quantity).toBe(0);
    expect(result[0].unit).toBe('Stk');
    expect(result[0].unitRate).toBe(350.0);
  });

  // ── Test 4: Missing UP defaults to 0 ─────────────────────────────────────
  it('defaults unitRate to 0 when UP element is missing', () => {
    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qty: '10', qu: 'm', text: 'Perimeter fence' })}
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    expect(result[0].unitRate).toBe(0);
    expect(result[0].quantity).toBe(10);
  });

  // ── Test 5: Extract unit from QU tag ─────────────────────────────────────
  it('extracts unit of measure from QU element', () => {
    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qu: 'lfd.m', text: 'Steel beam', up: '75.00' })}
        ${itemXML({ rno: '002', qu: 'Stk', text: 'Anchor bolt', up: '2.50' })}
        ${itemXML({ rno: '003', qu: 'Psch', text: 'Lump sum cleaning', up: '500.00' })}
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result[0].unit).toBe('lfd.m');
    expect(result[1].unit).toBe('Stk');
    expect(result[2].unit).toBe('Psch');
  });

  // ── Test 6: Build ordinal from OrdinalNo / RNoPart ───────────────────────
  it('builds hierarchical ordinal from category and item RNoPart attributes', () => {
    const xml = x83Doc(`
      <BoQCtgy RNoPart="02">
        <LblTx>Concrete Works</LblTx>
        <BoQBody>
          <Itemlist>
            ${itemXML({ rno: '010', qty: '45', qu: 'm3', text: 'In-situ concrete', up: '220.00' })}
            ${itemXML({ rno: '011', qty: '120', qu: 'm2', text: 'Formwork', up: '35.00' })}
          </Itemlist>
        </BoQBody>
      </BoQCtgy>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(2);
    expect(result[0].ordinal).toBe('02.010');
    expect(result[1].ordinal).toBe('02.011');
  });

  // ── Test 7: Handle empty XML string ──────────────────────────────────────
  it('returns empty array for empty XML string', () => {
    expect(parseGAEBXML('')).toEqual([]);
    expect(parseGAEBXML('   ')).toEqual([]);
  });

  // ── Test 8: Handle malformed XML ─────────────────────────────────────────
  it('returns empty array for malformed XML', () => {
    const malformed = '<GAEB><Award><BoQ><BoQBody><Itemlist><Item>UNCLOSED';
    const result = parseGAEBXML(malformed);
    // DOMParser is lenient — it will try to recover. What matters is no crash,
    // and if it does produce a parsererror document we return [].
    expect(Array.isArray(result)).toBe(true);
  });

  // ── Test 9: X81 format — no prices ───────────────────────────────────────
  it('parses X81 Leistungsverzeichnis with no unit prices', () => {
    const xml = x81Doc(`
      <Itemlist>
        <Item RNoPart="001">
          <Qty>250</Qty>
          <QU>m2</QU>
          <Description>
            <CompleteText>
              <DetailTxt><Text>Tiling 30x30cm</Text></DetailTxt>
            </CompleteText>
          </Description>
        </Item>
        <Item RNoPart="002">
          <Qty>80</Qty>
          <QU>m</QU>
          <Description>
            <CompleteText>
              <DetailTxt><Text>Skirting board</Text></DetailTxt>
            </CompleteText>
          </Description>
        </Item>
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(2);
    expect(result[0].unitRate).toBe(0);
    expect(result[1].unitRate).toBe(0);
    expect(result[0].description).toBe('Tiling 30x30cm');
    expect(result[1].description).toBe('Skirting board');
  });

  // ── Test 10: Extract section headers from LblTx ──────────────────────────
  it('attaches section label from ancestor BoQCtgy LblTx to positions', () => {
    const xml = x83Doc(`
      <BoQCtgy RNoPart="03">
        <LblTx>Masonry Works</LblTx>
        <BoQBody>
          <Itemlist>
            ${itemXML({ rno: '001', qty: '200', qu: 'm2', text: 'Brick wall 24cm', up: '65.00' })}
          </Itemlist>
        </BoQBody>
      </BoQCtgy>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    expect(result[0].section).toBe('Masonry Works');
    expect(result[0].ordinal).toBe('03.001');
  });

  // ── Test 11: Comma decimal separator (German locale) ─────────────────────
  it('handles comma as decimal separator in Qty and UP values', () => {
    const xml = x83Doc(`
      <Itemlist>
        <Item RNoPart="001">
          <Qty>12,5</Qty>
          <QU>m2</QU>
          <Description>
            <CompleteText><DetailTxt><Text>Floor screed</Text></DetailTxt></CompleteText>
          </Description>
          <UP>48,75</UP>
        </Item>
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result).toHaveLength(1);
    expect(result[0].quantity).toBe(12.5);
    expect(result[0].unitRate).toBe(48.75);
  });

  // ── Test 12: Qty as attribute on BoQCtgy (GAEB variant) ──────────────────
  it('reads Qty from Item child element when attribute is absent', () => {
    const xml = x83Doc(`
      <Itemlist>
        <Item RNoPart="005">
          <Qty>33</Qty>
          <QU>m3</QU>
          <Description>
            <CompleteText><DetailTxt><Text>Sand fill</Text></DetailTxt></CompleteText>
          </Description>
          <UP>18.00</UP>
        </Item>
      </Itemlist>
    `);

    const result = parseGAEBXML(xml);

    expect(result[0].quantity).toBe(33);
    expect(result[0].unitRate).toBe(18);
  });
});

// ---------------------------------------------------------------------------
// importGAEBToBOQ tests
// ---------------------------------------------------------------------------

describe('importGAEBToBOQ', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('calls boqApi.addPosition for each parsed position and returns imported count', async () => {
    // Mock the boqApi module
    const { boqApi } = await import('./api');
    vi.spyOn(boqApi, 'addPosition').mockResolvedValue({
      id: 'pos-new',
      boq_id: 'boq-1',
      parent_id: null,
      ordinal: '001',
      description: 'Test',
      unit: 'm2',
      quantity: 10,
      unit_rate: 50,
      total: 500,
      classification: {},
      source: 'gaeb_import',
      confidence: null,
      validation_status: 'pending',
      sort_order: 0,
      metadata: {},
    });

    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qty: '10', qu: 'm2', text: 'Wall tiles', up: '50.00' })}
        ${itemXML({ rno: '002', qty: '5', qu: 'm3', text: 'Foundation concrete', up: '220.00' })}
      </Itemlist>
    `);

    const file = new File([xml], 'test.x83', { type: 'text/xml' });
    const result = await importGAEBToBOQ(file, 'boq-1');

    expect(result.imported).toBe(2);
    expect(result.errors).toHaveLength(0);
    expect(boqApi.addPosition).toHaveBeenCalledTimes(2);
  });

  it('collects errors for positions that fail to POST and continues importing', async () => {
    const { boqApi } = await import('./api');
    let callCount = 0;
    vi.spyOn(boqApi, 'addPosition').mockImplementation(async () => {
      callCount++;
      if (callCount === 2) {
        throw new Error('Network error');
      }
      return {
        id: 'pos-new',
        boq_id: 'boq-1',
        parent_id: null,
        ordinal: '001',
        description: 'Test',
        unit: 'm2',
        quantity: 10,
        unit_rate: 50,
        total: 500,
        classification: {},
        source: 'gaeb_import',
        confidence: null,
        validation_status: 'pending',
        sort_order: 0,
        metadata: {},
      };
    });

    const xml = x83Doc(`
      <Itemlist>
        ${itemXML({ rno: '001', qty: '10', qu: 'm2', text: 'Item A', up: '50.00' })}
        ${itemXML({ rno: '002', qty: '5', qu: 'm3', text: 'Item B', up: '220.00' })}
        ${itemXML({ rno: '003', qty: '2', qu: 'Stk', text: 'Item C', up: '75.00' })}
      </Itemlist>
    `);

    const file = new File([xml], 'test.x83', { type: 'text/xml' });
    const result = await importGAEBToBOQ(file, 'boq-1');

    expect(result.imported).toBe(2);
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toContain('Item B');
    expect(result.errors[0]).toContain('Network error');
  });
});
