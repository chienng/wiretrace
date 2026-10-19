import { describe, expect, it } from 'vitest';
import { PAUSED_LABEL, PAUSED_TIP, recordingPill } from './recording';

describe('recording pill', () => {
  it('says Recording while the list is live', () => {
    expect(recordingPill(false, false)).toBe('recording');
  });
  it('does not say Recording once Pause is pressed', () => {
    expect(recordingPill(false, true)).toBe('paused');
    expect(PAUSED_LABEL).not.toMatch(/Recording/);
  });
  it('the tooltip says capture goes on', () => {
    expect(PAUSED_TIP).toMatch(/still recording/);
  });
  it('a lost connection wins over pause', () => {
    expect(recordingPill(true, true)).toBe('reconnecting');
    expect(recordingPill(true, false)).toBe('reconnecting');
  });
});
