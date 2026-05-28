import type { Freshness, Severity } from "@frw/shared-types";
import { useTranslation } from "react-i18next";

const freshnessClass: Record<Freshness, string> = {
  fresh: "border-success/40 bg-success/10 text-success",
  watch: "border-sky/40 bg-sky/10 text-sky",
  stale: "border-warning/40 bg-warning/10 text-warning",
  unsupported: "border-line bg-panelLift text-muted"
};

const severityClass: Record<Severity, string> = {
  low: "border-line bg-panelLift text-muted",
  medium: "border-sky/40 bg-sky/10 text-sky",
  high: "border-warning/40 bg-warning/10 text-warning",
  critical: "border-danger/40 bg-danger/10 text-danger"
};

export function FreshnessBadge({ value }: { value: Freshness }) {
  const { t } = useTranslation();
  return <span className={`badge whitespace-nowrap ${freshnessClass[value]}`}>{t(`freshnessStates.${value}`)}</span>;
}

export function SeverityBadge({ value }: { value: Severity }) {
  const { t } = useTranslation();
  return <span className={`badge whitespace-nowrap ${severityClass[value]}`}>{t(`severityStates.${value}`)}</span>;
}

export function SourceBadge({ label }: { label: string }) {
  return <span className="badge whitespace-normal border-line bg-panelLift text-ink">{label}</span>;
}
