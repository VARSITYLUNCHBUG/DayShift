// The pop-ups and toasts that can show over any signed-in page. Still the old screens' versions;
// FE-ROOM and FE-PAGES rebuild them on Dialog and NoticeSheet with the new protocol.
import { ReadyUpDialog } from "../legacy/screens/ReadyUpDialog";
import { OfferDialog } from "../legacy/screens/subs/OfferDialog";
import { MeToasts } from "../legacy/screens/useMeToasts";

export default function GlobalNotices() {
  return (
    <>
      <ReadyUpDialog />
      <OfferDialog />
      <MeToasts />
    </>
  );
}
