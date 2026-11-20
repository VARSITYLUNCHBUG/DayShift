import { ButtonLink } from "../components/Button";
import { EmptyState } from "../components/States";

/** 404 (E09): what happened and the way back. */
export default function NotFoundPage() {
  return (
    <EmptyState
      title="There's nothing here"
      action={
        <ButtonLink to="/" kind="ghost">
          Back to Play
        </ButtonLink>
      }
    >
      The link may be old, or the match was never played. Everything live starts from Play.
    </EmptyState>
  );
}
