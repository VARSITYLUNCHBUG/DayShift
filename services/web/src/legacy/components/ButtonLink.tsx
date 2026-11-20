import { buttonVariants } from "@heroui/react";
import type { ReactNode } from "react";
import { Link } from "react-router";

type Variant = NonNullable<Parameters<typeof buttonVariants>[0]>["variant"];

interface Props {
  to: string;
  children: ReactNode;
  variant?: Variant;
  size?: "sm" | "md" | "lg";
  fullWidth?: boolean;
  className?: string;
  /** A page Django serves (/auth/...): a full page load, not a client-side route. */
  external?: boolean;
  "aria-label"?: string;
  "aria-current"?: "page" | undefined;
}

/** A link that looks like a HeroUI Button. */
export function ButtonLink({
  to,
  children,
  variant = "primary",
  size = "md",
  fullWidth,
  className,
  external,
  ...aria
}: Props) {
  const classes = buttonVariants({ variant, size, fullWidth, className });
  if (external) {
    return (
      <a href={to} className={classes} {...aria}>
        {children}
      </a>
    );
  }
  return (
    <Link to={to} className={classes} {...aria}>
      {children}
    </Link>
  );
}
