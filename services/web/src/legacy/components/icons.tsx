// Brand marks and the app mark. Everything else comes from @gravity-ui/icons.
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function Stroke({ children, ...props }: IconProps) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export function AppMark(props: IconProps) {
  return (
    <Stroke {...props}>
      <path d="M12 2l3 6 6 1-4.5 4.5L18 20l-6-3-6 3 1.5-6.5L3 9l6-1z" />
    </Stroke>
  );
}

export function DiscordMark(props: IconProps) {
  return (
    <Stroke {...props}>
      <path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.6 8.6 0 0 1-3.8-.9L3 21l1.9-5.2A8.4 8.4 0 1 1 21 11.5z" />
    </Stroke>
  );
}

export function SteamMark(props: IconProps) {
  return (
    <Stroke {...props}>
      <circle cx="12" cy="12" r="10" />
      <circle cx="15.5" cy="9" r="2.5" />
      <path d="M13.5 10.5 8 15" />
      <circle cx="7.5" cy="15.5" r="1.5" />
    </Stroke>
  );
}
