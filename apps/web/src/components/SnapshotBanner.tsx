import { AlertTriangle, CheckCircle2, Clock3 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SnapshotEnvelope } from "@frw/shared-types";
import { isStale } from "../lib/snapshots";

export function SnapshotBanner<T>({ snapshot }: { snapshot: SnapshotEnvelope<T> }) {
  const { t } = useTranslation();
  const stale = isStale(snapshot.stale_after);
  return (
    <div
      className={`flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-md border px-5 py-3.5 text-sm leading-6 ${
        stale ? "border-warning/40 bg-warning/10 text-warning" : "border-success/35 bg-success/10 text-success"
      }`}
    >
      <div className="flex min-w-0 items-center gap-2">
        {stale ? <AlertTriangle className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
        <span className="font-semibold">{stale ? t("stale") : t("publicSnapshot")}</span>
        <span className="text-ink/80">v{snapshot.snapshot_version}</span>
      </div>
      <div className="flex min-w-0 items-center gap-2 text-ink/80">
        <Clock3 className="h-4 w-4" />
        <span className="break-words">
          {t("generated")}: {new Date(snapshot.generated_at).toLocaleString()}
        </span>
      </div>
    </div>
  );
}
