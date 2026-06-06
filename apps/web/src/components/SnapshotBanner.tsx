import { AlertTriangle, CheckCircle2, Clock3 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SnapshotEnvelope } from "@frw/shared-types";
import { snapshotFreshness } from "../lib/snapshots";

export function SnapshotBanner<T>({ snapshot }: { snapshot: SnapshotEnvelope<T> }) {
  const { t } = useTranslation();
  const freshness = snapshotFreshness(snapshot);
  const stale = freshness === "stale";
  const expired = freshness === "expired";
  return (
    <div
      className={`flex w-full min-w-0 max-w-full flex-col items-start gap-2 rounded-md border px-4 py-3 text-sm leading-6 sm:flex-row sm:items-center sm:justify-between sm:gap-3 sm:px-5 ${
        expired
          ? "border-danger/45 bg-danger/10 text-danger"
          : stale
            ? "border-warning/40 bg-warning/10 text-warning"
            : "border-success/35 bg-success/10 text-success"
      }`}
    >
      <div className="flex min-w-0 max-w-full items-center gap-2">
        {stale || expired ? <AlertTriangle className="h-4 w-4 shrink-0" /> : <CheckCircle2 className="h-4 w-4 shrink-0" />}
        <span className="font-semibold">{expired ? t("snapshotExpired") : stale ? t("stale") : t("publicSnapshot")}</span>
        <span className="text-ink/80">v{snapshot.snapshot_version}</span>
      </div>
      <div className="flex min-w-0 max-w-full items-center gap-2 text-ink/80">
        <Clock3 className="h-4 w-4 shrink-0" />
        <span className="safe-text min-w-0">
          {expired ? t("snapshotExpired") : t("generated")}: {new Date(expired ? snapshot.hard_expires_at : snapshot.generated_at).toLocaleString()}
        </span>
      </div>
    </div>
  );
}
