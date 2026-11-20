// A scrim's end (E06–E08): the draft is done; the two teams play it out of the league.
import { ButtonLink } from "../../components/Button";
import { StageHead } from "./Parts";
import { Room } from "./Room";
import type { MatchScreenProps } from "./types";

export function ScrimDrafted({ match }: MatchScreenProps) {
  return (
    <Room match={match} heroes now={{ eyebrow: "Scrim", title: "Drafted", line: "Play it out: scrims don't change ratings" }}>
      <StageHead
        eyebrow="Scrim"
        title="The draft is done"
        lead="Make the lobby in Deadlock with these heroes. Scrims don't change anyone's rating."
      />
      <ButtonLink to="/" kind="ghost" className="self-start">
        Back to Play
      </ButtonLink>
    </Room>
  );
}
