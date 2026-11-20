import { ButtonLink } from "../components/Button";
import { Icon } from "../components/Icon";
import { EmptyState } from "../components/States";

/** 404 (E09): what happened and the way back. The state is the page, so its title is the h1. */
export default function NotFoundPage() {
  return (
    <EmptyState
      headingLevel={1}
      art={
        <span className="text-muted">
          <Icon name="search" size={36} />
        </span>
      }
      title="We can't find that page"
      action={
        <div className="flex flex-wrap justify-center gap-2.5">
          <ButtonLink to="/">Back to Play</ButtonLink>
          <ButtonLink to="/matches" kind="ghost">
            Matches
          </ButtonLink>
        </div>
      }
    >
      The link may be old, or that match number doesn&apos;t exist. Nothing is broken on your side.
    </EmptyState>
  );
}
