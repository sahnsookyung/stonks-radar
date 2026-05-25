export function LoadingState({ label = "Loading snapshot" }: { label?: string }) {
  return (
    <div className="grid min-h-[70vh] place-items-center rounded-md border border-dashed border-line bg-panel text-sm text-muted">
      {label}
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  return (
    <div className="signal-danger p-4 text-sm">
      {error instanceof Error ? error.message : "Unable to load snapshot"}
    </div>
  );
}
