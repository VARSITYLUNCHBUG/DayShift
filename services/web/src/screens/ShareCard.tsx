import { ButtonLink } from "../components/Button";
import { PageHeader } from "../components/Layout";
import { EmptyState } from "../components/States";

/** /me/share (E05): your share card. Built by FE-PAGES. */
export default function ShareCardPage() {
  return (
    <>
      <PageHeader title="Share card" lead="A picture of your night to post in Discord. Only you see this page." />
      <EmptyState
        title="Your share card isn't ready yet"
        action={
          <ButtonLink to="/me" kind="ghost">
            Back to Me
          </ButtonLink>
        }
      >
        It will show your rating, your record and your best match once you've played.
      </EmptyState>
    </>
  );
}
