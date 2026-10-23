import { api } from '../api';
import { REMOVE_LEAD, removeNote, removeTitle } from '../logic/proxyDevices';
import { DeviceChangeFoot, useDeviceChange } from './AllowDeviceDialog';
import { Modal } from './Modal';

/** Asked before an accepted device is refused again in this session (spec 022). */
export function RemoveDeviceDialog({ address, accepted, onClose }: {
  address: string;
  accepted: readonly string[];
  onClose: () => void;
}) {
  const { busy, error, close, send } = useDeviceChange(onClose, 'Could not remove the device');
  return (
    <Modal title={removeTitle(address)} lead={REMOVE_LEAD} onClose={close}>
      <div className="callout info">{removeNote(address, accepted)}</div>
      <DeviceChangeFoot
        busy={busy}
        error={error}
        label="Remove"
        danger
        onCancel={close}
        onConfirm={() => void send(() => api.removeDevice(address), `${address} is refused from now on`)}
      />
    </Modal>
  );
}
