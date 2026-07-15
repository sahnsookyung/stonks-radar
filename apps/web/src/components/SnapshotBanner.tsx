import { AlertTriangle, CheckCircle2, Clock3 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SnapshotEnvelope } from "@frw/shared-types";
import { snapshotFreshness } from "../lib/snapshots";

export function SnapshotBanner<T>({ snapshot }: Readonly<{ snapshot: SnapshotEnvelope<T> }>) {
  const { t, i18n } = useTranslation();
  const freshness = snapshotFreshness(snapshot);
  const stale = freshness === "stale";
  const expired = freshness === "expired";
  const unavailableWarning = snapshot.warnings.find((warning) => warning.code === "live_data_unavailable");
  const unavailable = Boolean(unavailableWarning);
  const toneClass = snapshotBannerToneClass(expired, stale, unavailable);
  const statusLabel = unavailable
    ? i18n.language.startsWith("ko")
      ? "실시간 데이터 없음"
      : "Live data unavailable"
    : snapshotBannerStatusLabel(expired, stale, t);
  const timestampLabel = expired
    ? t("snapshotExpired")
    : unavailable
      ? i18n.language.startsWith("ko")
        ? "마지막 확인"
        : "Last checked"
      : t("generated");
  const timestampValue = expired ? snapshot.hard_expires_at : snapshot.generated_at;
  return (
    <div
      className={`flex w-full min-w-0 max-w-full flex-col items-start gap-2 rounded-md border px-4 py-3 text-sm leading-6 sm:flex-row sm:items-center sm:justify-between sm:gap-3 sm:px-5 ${toneClass}`}
    >
      <div className="flex min-w-0 max-w-full items-center gap-2">
        {stale || expired || unavailable ? <AlertTriangle className="h-4 w-4 shrink-0" /> : <CheckCircle2 className="h-4 w-4 shrink-0" />}
        <span className="font-semibold">{statusLabel}</span>
        <span className="text-ink/80">v{snapshot.snapshot_version}</span>
        {unavailableWarning ? <span className="safe-text text-ink/80">{unavailableWarning.message}</span> : null}
      </div>
      <div className="flex min-w-0 max-w-full items-center gap-2 text-ink/80">
        <Clock3 className="h-4 w-4 shrink-0" />
        <span className="safe-text min-w-0">
          {timestampLabel}: {new Date(timestampValue).toLocaleString()}
        </span>
      </div>
    </div>
  );
}

function snapshotBannerToneClass(expired: boolean, stale: boolean, unavailable: boolean) {
  if (expired) return "border-danger/45 bg-danger/10 text-danger";
  if (stale || unavailable) return "border-warning/40 bg-warning/10 text-warning";
  return "border-success/35 bg-success/10 text-success";
}

function snapshotBannerStatusLabel(expired: boolean, stale: boolean, t: (key: string) => string) {
  if (expired) return t("snapshotExpired");
  if (stale) return t("stale");
  return t("publicSnapshot");
}
