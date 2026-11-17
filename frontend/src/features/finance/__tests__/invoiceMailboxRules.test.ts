// @vitest-environment node
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { isHostNotAllowed, mailboxDraftProblems, type MailboxDraft } from '../invoiceMailboxRules';

const ok: MailboxDraft = {
  enabled: true,
  host: 'imap.example.com',
  port: 993,
  use_ssl: true,
  username: 'invoices',
  password: 'x',
  folder: 'INBOX',
  processed_folder: 'Processed',
  intake_address: 'invoices@company.example',
};

describe('mailboxDraftProblems', () => {
  it('accepts a complete mailbox', () => {
    expect(mailboxDraftProblems(ok, false)).toEqual([]);
  });
  it('lets a disabled mailbox stay half filled', () => {
    expect(mailboxDraftProblems({ ...ok, enabled: false, host: '', username: '', password: '' }, false)).toEqual([]);
  });
  it('asks for the password only when none is stored', () => {
    expect(mailboxDraftProblems({ ...ok, password: '' }, false)).toEqual(['password']);
    expect(mailboxDraftProblems({ ...ok, password: '' }, true)).toEqual([]);
  });
  it('names each refused field', () => {
    expect(mailboxDraftProblems({ ...ok, host: 'imaps://x' }, true)).toEqual(['host']);
    expect(mailboxDraftProblems({ ...ok, port: 70000 }, true)).toEqual(['port']);
    expect(mailboxDraftProblems({ ...ok, use_ssl: false }, true)).toEqual(['ssl']);
    expect(mailboxDraftProblems({ ...ok, host: 'localhost', use_ssl: false }, true)).toEqual([]);
    expect(mailboxDraftProblems({ ...ok, processed_folder: 'inbox' }, true)).toEqual(['processed_folder']);
    expect(mailboxDraftProblems({ ...ok, intake_address: 'nope' }, true)).toEqual(['intake_address']);
  });
});

describe('isHostNotAllowed', () => {
  const err = (detail: unknown) => ({ status: 422, body: { detail } });
  it('recognises the refused-host error', () => {
    expect(isHostNotAllowed(err([{ field: 'host', code: 'host_not_allowed', message: 'x' }]))).toBe(true);
  });
  it('ignores other field errors and non-API errors', () => {
    expect(isHostNotAllowed(err([{ field: 'port', code: 'port_invalid' }]))).toBe(false);
    expect(isHostNotAllowed(err('boom'))).toBe(false);
    expect(isHostNotAllowed(new Error('x'))).toBe(false);
    expect(isHostNotAllowed(null)).toBe(false);
  });
});
