import type { Faults } from '../types';

/** Number of active fault effects; zero while no filter selects any request. */
export function activeFaultCount(faults: Faults, on: boolean): number {
  if (!on) return 0;
  return (faults.status ? 1 : 0) + (faults.delay_ms ? 1 : 0) + (faults.drop ? 1 : 0);
}

export function isFaultsOn(faults: Faults): boolean {
  return faults.filter.trim() !== '' && activeFaultCount(faults, true) > 0;
}
