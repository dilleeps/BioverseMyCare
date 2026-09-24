import { useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { WorkspaceLayout } from "../../layouts.jsx";
import AgentsTab from "./AgentsTab.jsx";
import ActivityTab from "./ActivityTab.jsx";
import EvalsTab from "./EvalsTab.jsx";
import MonitoringTab from "./MonitoringTab.jsx";
import MatrixTab from "./MatrixTab.jsx";

const TABS = [
  { id: "agents", label: "Agents", component: AgentsTab },
  { id: "activity", label: "Activity", component: ActivityTab },
  { id: "evaluations", label: "Evaluations", component: EvalsTab },
  { id: "monitoring", label: "Monitoring", component: MonitoringTab },
  { id: "matrix", label: "Review matrix", component: MatrixTab },
];

export default function AiConsole() {
  const [params, setParams] = useSearchParams();
  const current = TABS.find((t) => t.id === params.get("tab")) || TABS[0];
  const refs = useRef({});

  function select(id, focus = false) {
    setParams({ tab: id }, { replace: true });
    if (focus) refs.current[id]?.focus();
  }

  // Arrow keys move between tabs (WAI-ARIA tabs pattern, automatic activation).
  function onKeyDown(e) {
    const i = TABS.findIndex((t) => t.id === current.id);
    const to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: TABS.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    select(TABS[(to + TABS.length) % TABS.length].id, true);
  }

  const Panel = current.component;
  return (
    <WorkspaceLayout>
      <header style={{ marginBottom: 14 }}>
        <div className="eyebrow">AI platform</div>
        <h1 className="page-title">AI governance</h1>
        <div className="page-sub">What each agent is allowed to do, what it did, how it tests, and how it is behaving.</div>
      </header>
      <div role="tablist" aria-label="AI governance sections" className="aip-tabs" onKeyDown={onKeyDown}>
        {TABS.map((t) => (
          <button
            key={t.id}
            ref={(el) => { refs.current[t.id] = el; }}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={t.id === current.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={t.id === current.id ? 0 : -1}
            className="aip-tab"
            onClick={() => select(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <section role="tabpanel" id={`panel-${current.id}`} aria-labelledby={`tab-${current.id}`} className="aip-panel">
        <Panel />
      </section>
    </WorkspaceLayout>
  );
}
