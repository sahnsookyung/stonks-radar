import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { entityDisplayName, resolveTrackedEntity, type TrackedEntity } from "../lib/trackedTickers";

export function EntityLink({
  value,
  locale,
  className = "badge min-h-11 border-accent/40 bg-accentSoft text-accent hover:border-accent",
  children
}: Readonly<{
  value: string | TrackedEntity;
  locale: "en" | "ko";
  className?: string;
  children?: ReactNode;
}>) {
  const entity = typeof value === "string" ? resolveTrackedEntity(value) : value;
  if (!entity || entity.routeKind === "unsupported") {
    return (
      <span className="badge min-h-11 border-line bg-panelAlt text-muted" title={locale === "ko" ? "추적하지 않는 항목" : "Not tracked"}>
        {typeof value === "string" ? value : entityDisplayName(value, locale)}
      </span>
    );
  }
  const label = children ?? entity.displaySymbol;
  if (entity.routeKind === "reference_entity") {
    return (
      <Link to="/$locale/entities/$routeKey" params={{ locale, routeKey: entity.routeKey }} className={className}>
        {label}
      </Link>
    );
  }
  return (
    <Link to="/$locale/tickers/$symbol" params={{ locale, symbol: entity.routeKey }} className={className}>
      {label}
    </Link>
  );
}
