import { Kbd, Spinner, Tabs, Toast } from "@heroui/react";
import { lazy, Suspense, useCallback, useState, type ReactNode } from "react";

import { control, sim } from "./api";
import { Header, type Health } from "./components/Header";
import { describeError, useAction } from "./hooks/useAction";
import { useEventLog } from "./hooks/useEventLog";
import { useHotkeys } from "./hooks/useHotkeys";
import { usePoll } from "./hooks/usePoll";

// Each screen is its own chunk, fetched the first time its tab opens.
const PlayersScreen = lazy(() => import("./screens/PlayersScreen").then((m) => ({ default: m.PlayersScreen })));
const MatchesScreen = lazy(() => import("./screens/matches/MatchesScreen").then((m) => ({ default: m.MatchesScreen })));
const DiscordScreen = lazy(() => import("./screens/discord/DiscordScreen").then((m) => ({ default: m.DiscordScreen })));
const ScenariosScreen = lazy(() => import("./screens/ScenariosScreen").then((m) => ({ default: m.ScenariosScreen })));

function Screen({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <span className="flex items-center gap-2 text-muted">
          <Spinner size="sm" /> Loading…
        </span>
      }
    >
      {children}
    </Suspense>
  );
}

const TABS = [
  { id: "players", label: "Players", key: "1" },
  { id: "matches", label: "Queue & matches", key: "2" },
  { id: "discord", label: "Discord view", key: "3" },
  { id: "scenarios", label: "Scenarios", key: "4" },
] as const;
type TabId = (typeof TABS)[number]["id"];

const loadState = (signal: AbortSignal) => control.state(signal);
const loadSimState = (signal: AbortSignal) => sim.state(signal);
const loadSimHealth = (signal: AbortSignal) => sim.health(signal);

export function App() {
  const [tab, setTab] = useState<TabId>("players");
  const state = usePoll(loadState, 1500);
  const simState = usePoll(loadSimState, 2000);
  const simHealth = usePoll(loadSimHealth, 3000);
  const eventLog = useEventLog();

  const refreshState = state.refresh;
  const refreshSim = simState.refresh;
  const refreshAll = useCallback(() => {
    refreshState();
    refreshSim();
  }, [refreshState, refreshSim]);
  const { run } = useAction(refreshAll);

  useHotkeys(Object.fromEntries(TABS.map((t) => [t.key, () => { setTab(t.id); }])));

  const web: Health = state.error
    ? { ok: false, detail: `control API: ${describeError(state.error)}` }
    : state.data
      ? { ok: true, detail: "control API answering" }
      : { ok: null, detail: "waiting for the control API" };
  const simOk: Health = simHealth.error
    ? { ok: false, detail: `simulator: ${describeError(simHealth.error)}` }
    : simHealth.data
      ? { ok: simHealth.data.ok, detail: `simulator ${simHealth.data.version ?? ""} answering` }
      : { ok: null, detail: "waiting for the simulator" };
  const botConnected = simHealth.data?.botConnected ?? simState.data?.botConnected ?? null;
  const bot: Health =
    state.data?.botOnSim === false
      ? { ok: null, detail: "bot is on real Discord: check it there, the simulator can't see it" }
      : botConnected === null
        ? { ok: null, detail: "bot gateway session: unknown" }
        : { ok: botConnected, detail: botConnected ? "bot connected to the sim gateway" : "bot not connected" };
  const botName = state.data?.botOnSim === false ? "bot · real Discord" : "bot";

  return (
    <div className="flex h-full flex-col">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-accent px-3 py-1 text-accent-foreground focus:not-sr-only focus:absolute focus:left-2 focus:top-2"
      >
        Skip to the screen
      </a>
      <Toast.Provider placement="bottom end" />
      <Header
        state={state.data}
        web={web}
        sim={simOk}
        bot={bot}
        botName={botName}
        onReset={(fixture) => run("Reset", () => control.reset(fixture || undefined), "Reset to fixtures")}
        onPauseTimers={() => void run("Pause timers", () => control.pauseTimers())}
        onResumeTimers={() => void run("Resume timers", () => control.resumeTimers())}
      />
      <main id="main" tabIndex={-1} className="flex min-h-0 flex-1 flex-col outline-none">
        <Tabs
          className="flex min-h-0 flex-1 flex-col"
          selectedKey={tab}
          onSelectionChange={(key) => { setTab(String(key) as TabId); }}
        >
          <Tabs.ListContainer className="px-4 pt-2">
            <Tabs.List aria-label="Screens">
              {TABS.map((t) => (
                <Tabs.Tab key={t.id} id={t.id}>
                  <span className="flex items-center gap-2">
                    {t.label}
                    <Kbd className="hidden sm:inline-flex">
                      <Kbd.Content>{t.key}</Kbd.Content>
                    </Kbd>
                  </span>
                  <Tabs.Indicator />
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </Tabs.ListContainer>
          <Tabs.Panel id="players" className="min-h-0 flex-1 overflow-auto p-4">
            <Screen>
              <PlayersScreen onChanged={refreshAll} />
            </Screen>
          </Tabs.Panel>
          <Tabs.Panel id="matches" className="min-h-0 flex-1 overflow-auto p-4">
            <Screen>
              <MatchesScreen state={state.data} error={state.error} botConnected={botConnected} onChanged={refreshAll} />
            </Screen>
          </Tabs.Panel>
          <Tabs.Panel id="discord" className="min-h-0 flex-1 overflow-hidden p-4">
            <Screen>
              <DiscordScreen simState={simState.data} error={simState.error} eventLog={eventLog} onChanged={refreshAll} />
            </Screen>
          </Tabs.Panel>
          <Tabs.Panel id="scenarios" className="min-h-0 flex-1 overflow-auto p-4">
            <Screen>
              <ScenariosScreen onChanged={refreshAll} />
            </Screen>
          </Tabs.Panel>
        </Tabs>
      </main>
    </div>
  );
}
