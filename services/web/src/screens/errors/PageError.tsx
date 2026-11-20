// "Something went wrong on our side" (E09): a page that crashed while drawing. Says what's safe and
// offers a retry, instead of a blank screen.
import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

import { Button, ButtonLink } from "../../components/Button";
import { ErrorState } from "../../components/States";

interface Props {
  children: ReactNode;
  /** Reset the boundary when this changes (the page's path). */
  resetKey?: string;
}

interface State {
  failed: boolean;
  key: string | undefined;
}

export class PageErrorBoundary extends Component<Props, State> {
  override state: State = { failed: false, key: this.props.resetKey };

  static getDerivedStateFromError(): Partial<State> {
    return { failed: true };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.key ? { failed: false, key: props.resetKey } : null;
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("A page failed to draw", error, info.componentStack);
  }

  override render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return <ServerError onRetry={() => this.setState({ failed: false })} />;
  }
}

export function ServerError({ onRetry }: { onRetry: () => void }) {
  return (
    <ErrorState
      headingLevel={1}
      title="Something went wrong on our side"
      action={
        <div className="flex flex-wrap justify-center gap-2.5">
          <Button onPress={onRetry}>Try again</Button>
          <ButtonLink to="/" kind="quiet">
            Back to Play
          </ButtonLink>
        </div>
      }
    >
      This page didn&apos;t load. Your place in the queue and any match you&apos;re in are safe. Try again in a moment.
    </ErrorState>
  );
}
