// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Adversarial tests for the thread grouping.
 *
 * Filing a reply under the wrong outbound mail is not a cosmetic bug: the
 * log is the account of who said what to whom, and a reply shown under
 * the wrong supplier reads as that supplier having said it.
 */

import { describe, expect, it } from 'vitest';
import { buildThread } from './EmailThread';
import type { ThreadEntry } from './registers-api';

const sent = (at: string, ref: string, who: string, contactId?: string): ThreadEntry => ({
  type: 'send',
  at,
  who,
  subject: `RFQ - ${who}`,
  email_ref: ref,
  contact_id: contactId ?? null,
  html: '<p>x</p>',
});

const reply = (at: string, id: string, subject: string, reference?: string): ThreadEntry => ({
  type: 'correspondence',
  at,
  id,
  subject,
  direction: 'incoming',
  reference,
});

describe('buildThread', () => {
  it('files a reply under the mail whose number it quotes', () => {
    const { nodes, loose } = buildThread([
      sent('2026-08-01T09:00', 'REG-MSG-000001', 'Alpha', 'c-alpha'),
      sent('2026-08-01T09:05', 'REG-MSG-000002', 'Bravo', 'c-bravo'),
      reply('2026-08-02T10:00', 'r1', 'Re: quote', 'REG-MSG-000001'),
    ]);
    expect(loose).toHaveLength(0);
    expect(nodes[0]!.replies.map((r) => r.id)).toEqual(['r1']);
    expect(nodes[1]!.replies).toHaveLength(0);
  });

  it('prefers the quoted number over "whatever was most recent"', () => {
    // The reply arrives AFTER the Bravo mail but quotes the Alpha one.
    // Time order must not beat an explicit reference.
    const { nodes } = buildThread([
      sent('2026-08-01T09:00', 'REG-MSG-000001', 'Alpha', 'c-alpha'),
      sent('2026-08-01T09:05', 'REG-MSG-000002', 'Bravo', 'c-bravo'),
      reply('2026-08-03T10:00', 'r1', 'Re: quote', 'REG-MSG-000001'),
    ]);
    expect(nodes[0]!.replies.map((r) => r.id)).toEqual(['r1']);
    expect(nodes[1]!.replies).toHaveLength(0);
  });

  it('files an unreferenced reply under the most recent mail before it', () => {
    const { nodes, loose } = buildThread([
      sent('2026-08-01T09:00', 'REG-MSG-000001', 'Alpha', 'c-alpha'),
      sent('2026-08-02T09:00', 'REG-MSG-000002', 'Bravo', 'c-bravo'),
      reply('2026-08-03T10:00', 'r1', 'no reference here'),
    ]);
    expect(loose).toHaveLength(0);
    expect(nodes[1]!.replies.map((r) => r.id)).toEqual(['r1']);
  });

  it('never files a reply under a mail that was sent AFTER it', () => {
    // The dangerous case: a reply shown under a mail it cannot answer.
    const { nodes, loose } = buildThread([
      sent('2026-08-05T09:00', 'REG-MSG-000001', 'Alpha', 'c-alpha'),
      reply('2026-08-01T10:00', 'r1', 'arrived first'),
    ]);
    expect(nodes[0]!.replies).toHaveLength(0);
    expect(loose.map((r) => r.id)).toEqual(['r1']);
  });

  it('keeps a reply with no timestamp out of the thread rather than guessing', () => {
    const { nodes, loose } = buildThread([
      sent('2026-08-01T09:00', 'REG-MSG-000001', 'Alpha', 'c-alpha'),
      reply(null as unknown as string, 'r1', 'undated'),
    ]);
    expect(nodes[0]!.replies).toHaveLength(0);
    expect(loose.map((r) => r.id)).toEqual(['r1']);
  });

  it('reads oldest first, so the conversation runs downwards', () => {
    const { nodes } = buildThread([
      sent('2026-08-03T09:00', 'REG-MSG-000003', 'Charlie'),
      sent('2026-08-01T09:00', 'REG-MSG-000001', 'Alpha'),
      sent('2026-08-02T09:00', 'REG-MSG-000002', 'Bravo'),
    ]);
    expect(nodes.map((n) => n.out.who)).toEqual(['Alpha', 'Bravo', 'Charlie']);
  });

  it('puts several replies to one mail in the order they arrived', () => {
    const { nodes } = buildThread([
      sent('2026-08-01T09:00', 'REG-MSG-000001', 'Alpha', 'c-alpha'),
      reply('2026-08-04T10:00', 'r2', 'and another', 'REG-MSG-000001'),
      reply('2026-08-02T10:00', 'r1', 'first', 'REG-MSG-000001'),
    ]);
    expect(nodes[0]!.replies.map((r) => r.id)).toEqual(['r1', 'r2']);
  });

  it('does not treat our own outgoing correspondence as a reply', () => {
    const { nodes, loose } = buildThread([
      sent('2026-08-01T09:00', 'REG-MSG-000001', 'Alpha', 'c-alpha'),
      { type: 'correspondence', at: '2026-08-02T10:00', id: 'o1', subject: 'ours', direction: 'outgoing' },
    ]);
    expect(nodes[0]!.replies).toHaveLength(0);
    expect(loose).toHaveLength(0);
  });

  it('survives an empty thread and a thread of replies only', () => {
    expect(buildThread([])).toEqual({ nodes: [], loose: [] });
    const onlyReplies = buildThread([reply('2026-08-01T10:00', 'r1', 'orphan')]);
    expect(onlyReplies.nodes).toHaveLength(0);
    expect(onlyReplies.loose).toHaveLength(1);
  });

  it('files each reply under the supplier it actually came from', () => {
    // Two packages out on the SAME DAY, both answered. Falling back to
    // "most recent before it" alone would put both replies under Bravo
    // and report that Alpha never answered - the exact wrong answer
    // the tracking column is there to give.
    const { nodes } = buildThread([
      sent('2026-08-01T09:00', 'REG-MSG-000001', 'Alpha', 'c-alpha'),
      sent('2026-08-01T09:05', 'REG-MSG-000002', 'Bravo', 'c-bravo'),
      reply('2026-08-02T10:00', 'r-alpha', 'Re: Alpha quote', 'REG-MSG-000001'),
      reply('2026-08-02T11:00', 'r-bravo', 'Re: Bravo quote', 'REG-MSG-000002'),
    ]);
    expect(nodes[0]!.replies.map((r) => r.id)).toEqual(['r-alpha']);
    expect(nodes[1]!.replies.map((r) => r.id)).toEqual(['r-bravo']);
  });
});

describe('buildThread — the limit of guessing', () => {
  it('an UNREFERENCED reply is filed by time alone, not by who sent it', () => {
    // Documents real behaviour rather than the intent. Rule 2 was written
    // to mean "the last mail sent to THIS person", but a reply entry
    // carries no contact id, so it cannot be matched by recipient. An
    // unreferenced reply from Alpha therefore lands under the Bravo mail
    // simply because that went out most recently.
    //
    // In practice rule 1 covers real mail: every email we send carries a
    // REG-MSG number and the inbound matcher looks for it. This pins the
    // fallback's honest behaviour so nobody reads the code as doing more.
    const { nodes } = buildThread([
      sent('2026-08-01T09:00', 'REG-MSG-000001', 'Alpha', 'c-alpha'),
      sent('2026-08-01T09:05', 'REG-MSG-000002', 'Bravo', 'c-bravo'),
      reply('2026-08-02T10:00', 'r-from-alpha', 'quote attached, no ref quoted'),
    ]);
    expect(nodes[0]!.replies).toHaveLength(0);
    expect(nodes[1]!.replies.map((r) => r.id)).toEqual(['r-from-alpha']);
  });
});
