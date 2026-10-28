// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wire types for the inbound-capture read surface (GET
// /api/v1/inbound-capture/projects/{id}/captured). A captured message is an
// incoming correspondence row this gateway created from an inbound email or a
// provider chat / SMS webhook; the read shape mirrors the normalized envelope
// plus the correspondence ids it became.

export interface InboundAttachment {
  filename: string;
  content_type: string;
  size_bytes: number;
  storage_hint: string | null;
}

export interface InboundMessage {
  correspondence_id: string;
  project_id: string;
  reference_number: string;
  channel: string;
  external_message_id: string;
  idempotency_key: string;
  direction: string;
  sender: string;
  recipients: string[];
  sent_at: string;
  subject: string;
  body: string;
  in_reply_to: string | null;
  attachments: InboundAttachment[];
  raw_refs: string[];
  deduplicated: boolean;
}

export interface InboundCapturedList {
  items: InboundMessage[];
  total: number;
}
