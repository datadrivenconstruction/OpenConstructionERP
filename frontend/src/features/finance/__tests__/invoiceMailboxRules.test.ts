// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { mailboxDraftProblems, type MailboxDraft } from '../invoiceMailboxRules';

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
