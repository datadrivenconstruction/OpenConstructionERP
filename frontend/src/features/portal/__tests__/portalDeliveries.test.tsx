// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The supplier's delivery form: only lines with a quantity are sent, a
// certificate goes with its line only when it is identified, and the file
// upload reaches the server as multipart with the portal session token.

import { describe, it, expect, vi, afterEach } from 'vitest';

import { buildDeliveryPayload, draftLinesFor } from '../PortalDeliveriesTab';
import { PORTAL_SESSION_KEY, uploadMyDeliveryDocument, type PortalPurchaseOrder } from '../api';

const PO: PortalPurchaseOrder = {
  id: 'po-1',
  po_number: 'PO-7',
  status: 'issued',
  delivery_date: null,
  currency_code: 'EUR',
  can_deliver: true,
  lines: [
    {
      id: 'l-1',
      description: 'Rebar',
      unit: 't',
      quantity_ordered: '10',
      quantity_received: '0',
      required_certificate_type: 'en10204_3_1',
      requires_inspection: true,
    },
    {
      id: 'l-2',
      description: 'Spacers',
      unit: 'pcs',
      quantity_ordered: '100',
      quantity_received: '0',
      required_certificate_type: null,
      requires_inspection: false,
    },
  ],
};

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe('buildDeliveryPayload', () => {
  it('prefills the certificate type the order asks for', () => {
    expect(draftLinesFor(PO).map((l) => l.certificate_type)).toEqual(['en10204_3_1', '']);
  });

  it('sends lines with a quantity and identified certificates only', () => {
    const lines = draftLinesFor(PO);
    lines[0] = { ...lines[0]!, quantity: '4', batch_lot: ' H-20931 ', certificate_number: 'Z-118' };
    const payload = buildDeliveryPayload({
      po_id: 'po-1',
      delivery_note_number: ' LS-4711 ',
      delivery_date: '2026-10-16',
      delivery_note_document_id: '',
      lines,
    });
    expect(payload).toEqual({
      po_id: 'po-1',
      delivery_note_number: 'LS-4711',
      delivery_date: '2026-10-16',
      delivery_note_document_id: null,
      lines: [
        {
          po_item_id: 'l-1',
          quantity: '4',
          batch_lot: 'H-20931',
          certificates: [
            {
              certificate_type: 'en10204_3_1',
              certificate_number: 'Z-118',
              document_id: null,
              batch_number: 'H-20931',
            },
          ],
        },
      ],
    });
  });

  it('drops a certificate that has a type but neither number nor scan', () => {
    const lines = draftLinesFor(PO);
    lines[0] = { ...lines[0]!, quantity: '1' };
    const payload = buildDeliveryPayload({
      po_id: 'po-1',
      delivery_note_number: 'LS-1',
      delivery_date: '2026-10-16',
      delivery_note_document_id: '',
      lines,
    });
    expect(payload.lines[0]!.certificates).toEqual([]);
  });
});

describe('uploadMyDeliveryDocument', () => {
  it('posts multipart with the session token and no JSON content type', async () => {
    sessionStorage.setItem(PORTAL_SESSION_KEY, 'tok');
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify({ document_id: 'd-1', name: 'LS.pdf' }), { status: 201 }));
    const out = await uploadMyDeliveryDocument('po-1', new File(['x'], 'LS.pdf', { type: 'application/pdf' }));
    expect(out.document_id).toBe('d-1');
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/v1/portal/me/purchase-orders/po-1/documents');
    const headers = new Headers((init as RequestInit).headers);
    expect(headers.get('Authorization')).toBe('Bearer tok');
    expect(headers.get('Content-Type')).toBeNull();
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
  });
});
