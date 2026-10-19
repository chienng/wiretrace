export const PAUSED_LABEL = 'List paused';
export const PAUSED_TIP = 'Only the list is paused: Wiretrace is still recording. Resume shows the new requests.';

export type RecordingPill = 'reconnecting' | 'paused' | 'recording';

/** What the title bar shows next to the view switch. While the list is paused it does not say Recording. */
export function recordingPill(reconnecting: boolean, paused: boolean): RecordingPill {
  if (reconnecting) return 'reconnecting';
  return paused ? 'paused' : 'recording';
}
