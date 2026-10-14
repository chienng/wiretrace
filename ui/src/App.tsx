import { useEffect, useMemo } from 'react';
import { setForbiddenListener } from './api';
import { FaultsDialog } from './components/FaultsDialog';
import { LogsView } from './components/LogsView';
import { ReportDialog } from './components/ReportDialog';
import { SetupDialog } from './components/SetupDialog';
import { TitleBar } from './components/TitleBar';
import { Toast } from './components/Toast';
import { TrafficView } from './components/TrafficView';
import { Connection } from './connection';
import { useServerFilter } from './hooks';
import { applyFilters, hostCounts, quickCounts } from './logic/filters';
import { useDispatch, useStore } from './store';
import type { FlowSummary } from './types';

function useConnection() {
  const dispatch = useDispatch();
  useEffect(() => {
    const connection = new Connection({
      onPhase: (phase) => dispatch({ type: 'phase', phase }),
      onLoaded: (data, buffered) => dispatch({ type: 'loaded', data, buffered }),
      onMessage: (message) => dispatch({ type: 'message', message }),
    });
    setForbiddenListener(() => {
      connection.stop();
      dispatch({ type: 'phase', phase: 'forbidden' });
    });
    connection.start();
    return () => {
      setForbiddenListener(null);
      connection.stop();
    };
  }, [dispatch]);
}

export function App() {
  useConnection();
  const { phase, loaded, flows, ui } = useStore();

  const listed = useMemo(
    () => flows.filter((f) => !ui.hidden.has(f.id) && (ui.frozen === null || ui.frozen.has(f.id))),
    [flows, ui.hidden, ui.frozen],
  );
  const newCount = useMemo(
    () => (ui.frozen === null ? 0 : flows.filter((f) => !ui.hidden.has(f.id) && !ui.frozen!.has(f.id)).length),
    [flows, ui.hidden, ui.frozen],
  );
  const counts = useMemo(() => quickCounts(listed), [listed]);
  const hosts = useMemo(() => hostCounts(listed), [listed]);
  const server = useServerFilter(ui.search, flows);
  const filtered = useMemo(
    () => applyFilters(listed, { quick: ui.quick, host: ui.host, text: ui.search, serverIds: server.ids }),
    [listed, ui.quick, ui.host, ui.search, server.ids],
  );
  const selected = useMemo<FlowSummary | null>(
    () => (ui.selectedFlowId === null ? null : (flows.find((f) => f.id === ui.selectedFlowId) ?? null)),
    [flows, ui.selectedFlowId],
  );

  if (phase === 'forbidden') {
    return (
      <div className="fullpage">
        <h1>Open the link printed in the Terminal.</h1>
        <p>Wiretrace only answers to the link that carries its token.</p>
      </div>
    );
  }

  if (!loaded) {
    return (
      <div className="fullpage">
        <div className="spinner" />
        <p>{phase === 'reconnecting' ? 'Reconnecting…' : 'Connecting to Wiretrace…'}</p>
      </div>
    );
  }

  return (
    <div className="app">
      <TitleBar newCount={newCount} />
      <main className="main">
        {ui.view === 'traffic' ? (
          <TrafficView flows={filtered} selected={selected} counts={counts} hosts={hosts} filterError={server.error} />
        ) : (
          <LogsView />
        )}
      </main>
      {ui.dialog === 'setup' && <SetupDialog />}
      {ui.dialog === 'faults' && <FaultsDialog />}
      {ui.dialog === 'report' && <ReportDialog />}
      <Toast />
    </div>
  );
}
