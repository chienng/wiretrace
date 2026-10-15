import { useEffect, useMemo } from 'react';
import { setForbiddenListener } from './api';
import { CompareDialog } from './components/CompareDialog';
import { LogsView } from './components/LogsView';
import { ReportDialog } from './components/ReportDialog';
import { RulesView } from './components/RulesView';
import { SetupWizard } from './components/SetupWizard';
import { TitleBar } from './components/TitleBar';
import { Toast } from './components/Toast';
import { TrafficView } from './components/TrafficView';
import { Connection } from './connection';
import { useServerFilter } from './hooks';
import { applyFilters, hostCounts, quickCounts } from './logic/filters';
import { useData, useDispatch, useStore } from './store';
import type { FlowSummary } from './types';
import { backToLive } from './viewing';

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

function ViewingBanner({ name, cutOff }: { name: string; cutOff: boolean }) {
  const dispatch = useDispatch();
  return (
    <div className="banner viewing" role="status">
      <span>
        Viewing <b>{name}</b> · read-only. The live session is still being recorded.
        {cutOff && ' Its flows.mitm ends early: the requests that could be read are shown.'}
      </span>
      <span className="spacer" />
      <button type="button" className="btn small" onClick={() => void backToLive(dispatch)}>
        Back to live
      </button>
    </div>
  );
}

export function App() {
  useConnection();
  const { phase, loaded, ui, view } = useStore();
  const { flows, viewing } = useData();

  // Pause and Clear act on the live session only.
  const listed = useMemo(
    () => (viewing ? flows : flows.filter((f) => !ui.hidden.has(f.id) && (ui.frozen === null || ui.frozen.has(f.id)))),
    [viewing, flows, ui.hidden, ui.frozen],
  );
  const newCount = useMemo(
    () => (viewing || ui.frozen === null ? 0 : flows.filter((f) => !ui.hidden.has(f.id) && !ui.frozen!.has(f.id)).length),
    [viewing, flows, ui.hidden, ui.frozen],
  );
  const counts = useMemo(() => quickCounts(listed), [listed]);
  const hosts = useMemo(() => hostCounts(listed), [listed]);
  const server = useServerFilter(ui.search, flows, viewing);
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
      {view && <ViewingBanner name={view.name} cutOff={view.cutOff} />}
      <main className="main">
        {ui.view === 'traffic' && <TrafficView flows={filtered} selected={selected} counts={counts} hosts={hosts} filterError={server.error} />}
        {ui.view === 'logs' && <LogsView />}
        {ui.view === 'rules' && !view && <RulesView />}
      </main>
      {ui.dialog === 'setup' && !view && <SetupWizard />}
      {ui.dialog === 'report' && <ReportDialog session={viewing} />}
      {ui.dialog === 'compare' && selected && <CompareDialog flow={selected} flows={flows} session={viewing} />}
      <Toast />
    </div>
  );
}
