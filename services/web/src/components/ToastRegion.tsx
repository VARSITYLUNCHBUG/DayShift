import { Toast } from "@heroui/react";

/** Where toasts appear: bottom-left at 420 wide, one at a time (P04); on phones the full width,
 * above the tab bar. The app loads it lazily, just after the first paint. */
export default function ToastRegion() {
  return <Toast.Provider placement="bottom start" width={420} maxVisibleToasts={1} className="max-md:bottom-18" />;
}
