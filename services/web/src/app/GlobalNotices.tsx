// The pop-ups and toasts that can show over any signed-in page: Ready Up (a must-answer dialog),
// spot offers (a notice sheet) and the player's own toasts. One notice at a time: Ready Up wins.
import { MeToasts } from "./notices/MeToasts";
import { ReadyUp } from "./notices/ReadyUp";
import { SpotOffer } from "./notices/SpotOffer";

export default function GlobalNotices() {
  return (
    <>
      <ReadyUp />
      <SpotOffer />
      <MeToasts />
    </>
  );
}
