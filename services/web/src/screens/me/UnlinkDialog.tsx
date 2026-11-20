import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Icon } from "../../components/Icon";
import { InlineAlert } from "../../components/InlineAlert";
import { errorText, notify } from "../../components/toast";
import { useUnlinkSteam } from "../../api/queries";
import type { SteamRow } from "../../api/types";

interface Props {
  account: SteamRow | null;
  onClose: () => void;
}

/** "Unlink RookPlays?" (A09): what you lose, then the solid button that does it. The outlined
 * Unlink only ever opens this; Esc or Keep it linked backs out. */
export function UnlinkDialog({ account, onClose }: Props) {
  const unlink = useUnlinkSteam();
  const name = account?.name || "this Steam account";
  const losses = [
    ...(account?.proven
      ? [{ title: "Sign in with Steam", line: "Only Discord sign-in works for you until you link again." }]
      : []),
    { title: "Result matching", line: "New matches won't find you by Steam. A captain has to match your scoreboard name to you by hand." },
  ];
  return (
    <Dialog
      isOpen={account !== null}
      onOpenChange={(open) => {
        if (!open) {
          unlink.reset();
          onClose();
        }
      }}
      title={`Unlink ${name}?`}
      actions={
        <>
          <Button
            kind="danger-solid"
            isPending={unlink.isPending}
            pendingLabel="Unlinking…"
            onPress={() => {
              if (!account) return;
              unlink.mutate(account.id, {
                onSuccess: () => {
                  notify.success("Steam unlinked", `${name} is off your profile.`);
                  onClose();
                },
              });
            }}
          >
            Unlink Steam
          </Button>
          <Button kind="quiet" autoFocus onPress={onClose}>
            Keep it linked
          </Button>
        </>
      }
    >
      <b className="text-label font-extrabold text-foreground">You lose:</b>
      <ul className="flex flex-col gap-2.5">
        {losses.map((loss) => (
          <li key={loss.title} className="flex gap-2.5">
            <span className="pt-0.5 text-danger">
              <Icon name="close" size={16} />
            </span>
            <span className="flex flex-col">
              <b className="text-label font-extrabold text-foreground">{loss.title}</b>
              <span className="text-label">{loss.line}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="text-label">Past results stay. You can link again any time, and it&apos;s proven again straight away.</p>
      {unlink.isError ? <InlineAlert title="That didn't unlink">{errorText(unlink.error)}</InlineAlert> : null}
    </Dialog>
  );
}
