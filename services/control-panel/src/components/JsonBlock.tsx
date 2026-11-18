/** Pretty JSON in a scrollable mono block. */
export function JsonBlock({ value, className = "" }: { value: unknown; className?: string }) {
  let text: string;
  try {
    text = value === undefined ? "undefined" : JSON.stringify(value, null, 2);
  } catch {
    text = String(value);
  }
  return (
    <pre
      className={`mono max-h-72 overflow-auto rounded-md border border-border bg-background-secondary p-2 whitespace-pre-wrap break-all ${className}`}
    >
      {text}
    </pre>
  );
}
