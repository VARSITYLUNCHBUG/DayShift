import { AppShell } from "../components/AppShell";
import { ButtonLink } from "../components/ButtonLink";
import { EmptyState } from "../components/EmptyState";

export function NotFoundPage() {
  return (
    <AppShell>
      <EmptyState
        title="Page not found"
        action={
          <ButtonLink to="/" variant="secondary">
            Back to Play
          </ButtonLink>
        }
      />
    </AppShell>
  );
}
