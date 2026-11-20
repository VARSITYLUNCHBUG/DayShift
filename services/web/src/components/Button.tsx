import { Button as HeroButton, buttonVariants, Spinner } from "@heroui/react";
import type { ButtonProps as HeroButtonProps } from "@heroui/react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { cn } from "../lib/cn";
import { Icon } from "./Icon";
import type { IconName } from "./Icon";

/** The wireframe's buttons (ds.btn / ghost / danger / quiet), on HeroUI's variants:
 * - `primary`: cream on ink, the one main action. With `team`, the acting team's fill.
 * - `ghost`: outlined pill (2px strong line), the secondary action.
 * - `danger`: outlined red, for leaving, voiding, disputing, banning; `danger-solid` only to
 *   confirm the destructive step.
 * - `quiet`: text only, for low-stakes actions (Cancel, Not now).
 * - `secondary`: a raised pill (chat's Send). */
export type ButtonKind = "primary" | "ghost" | "danger" | "danger-solid" | "quiet" | "secondary";
export type TeamKey = "hk" | "am";

const VARIANT = {
  primary: "primary",
  ghost: "outline",
  danger: "danger-soft",
  "danger-solid": "danger",
  quiet: "ghost",
  secondary: "secondary",
} as const satisfies Record<ButtonKind, NonNullable<HeroButtonProps["variant"]>>;

/** 44 tall (`sm`), 48 (`md`, the default) or 60 (`lg`, a page's big moment). Never smaller. */
export type ButtonSize = "sm" | "md" | "lg";

interface StyleProps {
  kind?: ButtonKind;
  /** A team's turn: the button takes that team's fill and ink. Only with `primary`. */
  team?: TeamKey | null;
  size?: ButtonSize;
  fullWidth?: boolean;
  className?: string;
}

export function buttonClass({ kind = "primary", team, size = "md", fullWidth, className }: StyleProps): string {
  return buttonVariants({
    variant: VARIANT[kind],
    size,
    fullWidth: fullWidth ?? false,
    className: cn(team && kind === "primary" && `button--team-${team}`, className),
  });
}

export interface ButtonProps extends Omit<HeroButtonProps, "variant" | "size" | "className" | "children">, StyleProps {
  children: ReactNode;
  icon?: IconName;
  /** While pending the label changes to this ("Locking in Ivy…"), the button keeps its place and
   * can't be pressed twice; React Aria announces the pending state. */
  pendingLabel?: ReactNode;
}

/** A DayShift button: a pill, at least 44px, Figtree 800. */
export function Button({
  kind = "primary",
  team,
  size = "md",
  fullWidth,
  className,
  icon,
  children,
  pendingLabel,
  isPending,
  ...rest
}: ButtonProps) {
  return (
    <HeroButton
      {...rest}
      variant={VARIANT[kind]}
      size={size}
      fullWidth={fullWidth}
      isPending={isPending}
      className={cn(team && kind === "primary" && `button--team-${team}`, className)}
    >
      {isPending ? <Spinner color="current" size="sm" /> : icon ? <Icon name={icon} /> : null}
      {isPending && pendingLabel ? pendingLabel : children}
    </HeroButton>
  );
}

interface IconButtonProps extends Omit<HeroButtonProps, "variant" | "size" | "className" | "children" | "isIconOnly"> {
  icon: IconName;
  /** What it does, for screen readers and the tooltip-less: "Copy the lobby code". */
  label: string;
  kind?: "ghost" | "quiet";
  className?: string;
}

/** An icon-only control: 44 x 44, outlined (ds.icon_btn) or quiet. */
export function IconButton({ icon, label, kind = "ghost", className, ...rest }: IconButtonProps) {
  return (
    <HeroButton {...rest} variant={VARIANT[kind]} isIconOnly aria-label={label} className={className}>
      <Icon name={icon} />
    </HeroButton>
  );
}

interface ButtonLinkProps extends StyleProps {
  to: string;
  children: ReactNode;
  icon?: IconName;
  /** A page Django serves (/auth/…, an invite): a full page load, not a client-side route. */
  external?: boolean;
  "aria-label"?: string;
  "aria-current"?: "page" | "step" | undefined;
}

/** A link that looks like a button: for actions that go somewhere. */
export function ButtonLink({ to, children, icon, external, kind, team, size, fullWidth, className, ...aria }: ButtonLinkProps) {
  const classes = buttonClass({ kind, team, size, fullWidth, className });
  const inner = (
    <>
      {icon ? <Icon name={icon} /> : null}
      {children}
    </>
  );
  if (external) {
    return (
      <a href={to} className={classes} {...aria}>
        {inner}
      </a>
    );
  }
  return (
    <Link to={to} className={classes} {...aria}>
      {inner}
    </Link>
  );
}
