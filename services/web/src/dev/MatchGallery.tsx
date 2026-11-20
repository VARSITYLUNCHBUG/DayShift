// /dev/screens/match (development builds only): every match-room screen, rendered from the
// snapshots Django writes, as a captain, a player and a spectator. Each runs on its own
// FakeServer, which accepts every action and changes nothing.
import { useState } from "react";
import { Link, Route, Routes, useParams } from "react-router";

import { ButtonLink } from "../components/Button";
import { Lockup } from "../components/Brand";
import { FakeServer } from "../live/FakeServer";
import type { AckScript } from "../live/FakeServer";
import { LiveProvider } from "../live/LiveProvider";
import type { AnySnap, Topic } from "../live/types";
import { FIXTURE_NOW, hasMatch, matchFixture, SCENES, viewerId, VIEWERS } from "../match/fixtures";
import type { Viewer } from "../match/fixtures";
import { MatchView } from "../screens/match/MatchRoute";

function answer(name: string): AckScript {
  if (name === "subs.options") {
    return {
      ok: true,
      result: { choices: [{ player_id: "3", name: "P3", is_self: true }], game_on: true, dodge: false, strikes: 1 },
    };
  }
  return { ok: true };
}

function Preview({ scene, viewer }: { scene: string; viewer: Viewer }) {
  const [match] = useState(() => matchFixture(scene, viewer));
  const [socket] = useState(() =>
    new FakeServer({
      auto: true,
      serverTime: FIXTURE_NOW,
      playerId: viewerId(scene, viewer),
      snaps: { [`match:${match.id}`]: match } as unknown as Partial<Record<Topic, AnySnap>>,
      answer,
    }).socket(),
  );
  return (
    <LiveProvider socket={socket}>
      <MatchView match={match} />
    </LiveProvider>
  );
}

function Entry() {
  const { scene = "", viewer = "player" } = useParams();
  const who = (VIEWERS as readonly string[]).includes(viewer) ? (viewer as Viewer) : "player";
  if (!hasMatch(scene, who)) return <Index />;
  return <Preview key={`${scene}.${who}`} scene={scene} viewer={who} />;
}

function Index() {
  return (
    <div className="mx-auto flex max-w-app flex-col gap-6 px-8 py-8">
      <header className="flex flex-wrap items-center gap-4">
        <Lockup size={22} />
        <span className="text-label font-bold text-muted">· The match room, from Django&apos;s fixtures</span>
        <ButtonLink to="/dev/screens" kind="ghost" size="sm" className="ml-auto">
          Components
        </ButtonLink>
      </header>
      <table className="w-full text-left text-body">
        <caption className="sr-only">Match room screens</caption>
        <thead>
          <tr className="border-b border-line text-caption text-muted">
            <th scope="col" className="py-2">
              Scene
            </th>
            {VIEWERS.map((v) => (
              <th key={v} scope="col" className="py-2 capitalize">
                {v}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {SCENES.map((scene) => (
            <tr key={scene} className="border-b border-line">
              <th scope="row" className="py-2 font-bold">
                {scene}
              </th>
              {VIEWERS.map((v) => (
                <td key={v} className="py-2">
                  {hasMatch(scene, v) ? (
                    <Link to={`/dev/screens/match/${scene}/${v}`} className="font-bold underline">
                      {v}
                    </Link>
                  ) : (
                    <span className="text-faint">·</span>
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function MatchGallery() {
  return (
    <Routes>
      <Route index element={<Index />} />
      <Route path=":scene/:viewer" element={<Entry />} />
      <Route path="*" element={<Index />} />
    </Routes>
  );
}
