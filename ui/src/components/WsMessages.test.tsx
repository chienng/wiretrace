import { describe, expect, it } from 'vitest';
import {
  HEX_DUMP_BYTES,
  MAX_KEPT,
  NEWEST_NOTE,
  OVERSIZE,
  acceptLoad,
  connectionHeader,
  detailTabs,
  followAfter,
  hexDump,
  matchLabel,
  mergeMessages,
  newestNote,
  startLoad,
  trafficSize,
  trimWindow,
} from '../logic/wsMessages';

describe('Messages tab', () => {
  it('is only for a WebSocket row, and first for it', () => {
    const plain = detailTabs(false, false).map((tab) => tab.id);
    const socket = detailTabs(true, true).map((tab) => tab.id);
    expect(plain).not.toContain('messages');
    expect(socket[0]).toBe('messages');
    expect(socket).toContain('request');
    expect(socket).toContain('changes');
    expect(detailTabs(false, true).some((tab) => tab.id === 'messages')).toBe(false);
  });

  it('follows new messages until the tester scrolls up or selects one', () => {
    expect(followAfter('append', true)).toBe(true);
    expect(followAfter('scroll-up', true)).toBe(false);
    expect(followAfter('append', false)).toBe(false);
    expect(followAfter('select', true)).toBe(false);
    expect(followAfter('scroll-bottom', false)).toBe(true);
  });

  it('reads the filter as matched of total', () => {
    expect(matchLabel(12, 128)).toBe('12 of 128');
  });

  it('keeps the newest 5,000', () => {
    const items = new Map<number, { index: number }>();
    for (let i = 0; i < MAX_KEPT + 2; i++) items.set(i, { index: i });
    const kept = trimWindow(mergeMessages(items, []), MAX_KEPT, 'newest');
    expect(kept.size).toBe(MAX_KEPT);
    expect(kept.has(0)).toBe(false);
    expect(kept.has(1)).toBe(false);
    expect(kept.has(2)).toBe(true);
    expect(kept.has(MAX_KEPT + 1)).toBe(true);
    expect(newestNote(MAX_KEPT + 2, kept.size, 2)).toBe(NEWEST_NOTE);
  });

  it('discards a fetch from the row that was open before a switch', () => {
    const first = startLoad('row-a', 0);
    const second = startLoad('row-b', first.generation);
    expect(acceptLoad(first.token, second.generation)).toBe(false);
    expect(acceptLoad(second.token, second.generation)).toBe(true);
    expect(first.token.id).toBe('row-a');
  });

  it('says how the connection closed', () => {
    expect(connectionHeader(null, null, null, 128)).toBe('Open · 128 messages');
    expect(connectionHeader('server', 1000, null, 128)).toBe('Closed by the server · code 1000 (normal) · 128 messages');
    expect(connectionHeader('client', 1001, 'going away', 4)).toBe('Closed by the app · code 1001 · reason: going away · 4 messages');
    expect(connectionHeader(null, null, null, 1)).toBe('Open · 1 message');
  });

  it('shows the message count in the size column', () => {
    expect(trafficSize(true, 128, null)).toBe('↕ 128');
    expect(trafficSize(false, null, 418)).toBe('418 B');
  });

  it('dumps the first 4 KiB of a binary message as hex and ASCII', () => {
    const dump = hexDump('68656c6c6f');
    expect(dump).toContain('68 65 6c 6c 6f');
    expect(dump).toContain('hello');
    const long = 'ab'.repeat(HEX_DUMP_BYTES + 8);
    const lines = hexDump(long).split('\n');
    expect(lines).toHaveLength(HEX_DUMP_BYTES / 16);
    expect(OVERSIZE).toBe('Larger than 2 MiB: shown up to 2 MiB; the HAR in a bug report has it');
  });
});
