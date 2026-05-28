import { Link } from "@tanstack/react-router";
import { ExternalLink } from "lucide-react";
import type { NewsEventListItem, NewsRegionRelation, NewsSourceRef } from "@frw/shared-types";

export function NewsEventCard({
  event,
  locale,
  compact = false
}: {
  event: NewsEventListItem;
  locale: "en" | "ko";
  compact?: boolean;
}) {
  const primarySources = event.source_links.filter((source) => source.is_primary);
  const displayedSources = (primarySources.length ? primarySources : event.source_links)
    .filter((source) => safeSourceUrl(source.url))
    .slice(0, 3);
  return (
    <article className="panel min-w-0 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <NewsScoreBadge label={locale === "ko" ? "속보" : "Breaking"} value={event.breaking_score} />
        <NewsScoreBadge label={locale === "ko" ? "신뢰" : "Trust"} value={event.trust_score} />
        <span className="badge border-line bg-panelAlt text-muted">{event.severity}</span>
        <span className="badge border-line bg-panelAlt text-muted">{Math.round(event.confidence * 100)}%</span>
      </div>
      <h2 className={`${compact ? "mt-3 text-base" : "mt-4 text-xl"} safe-text font-bold leading-7`}>
        <Link
          to="/$locale/news/events/$eventId"
          params={{ locale, eventId: event.id }}
          className="focus-ring rounded-md hover:text-accent"
        >
          {event.title}
        </Link>
      </h2>
      <p className="safe-text mt-2 text-sm leading-6 text-muted">{event.summary}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {event.tickers.slice(0, compact ? 4 : 8).map((ticker) => (
          <Link
            key={`${ticker.symbol}-${ticker.relationship}`}
            to="/$locale/tickers/$symbol"
            params={{ locale, symbol: ticker.symbol }}
            className="badge min-h-11 border-accent/40 bg-accentSoft text-accent hover:border-accent"
          >
            {ticker.symbol}
          </Link>
        ))}
        {event.regions.slice(0, compact ? 5 : 10).map((region) => (
          <span key={`${region.key}-${region.relation}`} className="badge border-line bg-panelAlt text-muted">
            {region.name} · {regionRelationLabel(region.relation, locale)}
          </span>
        ))}
        {event.topics.slice(0, compact ? 4 : 8).map((topic) => (
          <span key={topic.key} className="badge border-line bg-panelAlt text-muted">
            {topic.label}
          </span>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs leading-5 text-muted">
        <span>{locale === "ko" ? "업데이트" : "Updated"} {formatNewsDate(event.last_seen_at)}</span>
        <span>{locale === "ko" ? "출처" : "Sources"} {event.source_count}</span>
        <span>{marketDirectionLabel(event.market_direction, locale)}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {displayedSources.map((source) => (
          <SourcePill key={`${event.id}-${source.source_key}-${source.url}`} source={source} />
        ))}
      </div>
    </article>
  );
}

export function NewsScoreBadge({ label, value }: { label: string; value: number }) {
  const tone =
    value >= 80
      ? "border-danger/50 bg-danger/10 text-danger"
      : value >= 60
        ? "border-warning/50 bg-warning/10 text-warning"
        : "border-line bg-panelAlt text-muted";
  return <span className={`badge ${tone}`}>{label} {value}</span>;
}

export function SourcePill({ source }: { source: NewsSourceRef }) {
  const href = safeSourceUrl(source.url);
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="focus-ring inline-flex min-h-11 max-w-full items-center gap-1 rounded-md border border-line bg-panelAlt px-3 py-2 text-xs font-semibold text-muted hover:border-accent hover:text-accent"
      title={source.title}
    >
      <span className="truncate">{source.label}</span>
      <span className="hidden sm:inline">· {trustTierLabel(source.trust_tier)}</span>
      <ExternalLink className="h-3.5 w-3.5 shrink-0" />
    </a>
  );
}

function safeSourceUrl(value: string) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

function trustTierLabel(tier: string) {
  const labels: Record<string, string> = {
    T0_OFFICIAL: "official",
    T1_REGULATED_FILING: "filing",
    T2_REPUTABLE_MEDIA: "media",
    T3_REVIEWED_PUBLIC_SOURCE: "reviewed",
    T4_WEAK_SIGNAL: "discovery",
    T5_UNREVIEWED: "unreviewed",
    T6_BLOCKED: "blocked"
  };
  return labels[tier] ?? tier;
}

export function regionRelationLabel(relation: NewsRegionRelation, locale: "en" | "ko") {
  const labels: Record<NewsRegionRelation, [string, string]> = {
    source_region: ["published in", "게시 지역"],
    event_region: ["about", "발생 지역"],
    company_region: ["company", "기업 지역"],
    affected_region: ["affecting", "영향 지역"],
    market_region: ["market", "시장 지역"],
    mentioned_region: ["mentioned", "언급"]
  };
  const [en, ko] = labels[relation];
  return locale === "ko" ? ko : en;
}

export function marketDirectionLabel(direction: string, locale: "en" | "ko") {
  const labels: Record<string, [string, string]> = {
    bullish: ["bullish context", "강세 맥락"],
    bearish: ["bearish context", "약세 맥락"],
    mixed: ["mixed context", "혼재된 맥락"],
    unclear: ["direction unclear", "방향 불명확"]
  };
  const [en, ko] = labels[direction] ?? [direction, direction];
  return locale === "ko" ? ko : en;
}

export function formatNewsDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
