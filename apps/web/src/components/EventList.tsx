import type { PublicEvent } from "@frw/shared-types";
import { ExternalLink, MapPinned } from "lucide-react";
import { FreshnessBadge, SeverityBadge, SourceBadge } from "./Badge";
import { safeExternalUrl } from "../lib/safeExternalUrl";

type EventListProps = Readonly<{
  events: PublicEvent[];
  selectedEventId?: string | null;
  onEventSelect?: (eventId: string) => void;
}>;

export function EventList({ events, selectedEventId = null, onEventSelect }: EventListProps) {
  return (
    <div className="grid gap-3">
      {events.map((event) => {
        const selected = selectedEventId === event.id;
        return (
          <article
            key={event.id}
            className={`panel p-5 ${selected ? "border-accent shadow-[0_0_0_1px_rgba(83,216,245,0.35)]" : ""}`}
          >
            <div className="flex flex-wrap items-center gap-2.5">
              <SeverityBadge value={event.severity} />
              <FreshnessBadge value={event.freshness} />
              <SourceBadge label={event.source_strength} />
              {event.review_state === "candidate" || event.claim_level === "clustered_candidate" ? (
                <SourceBadge label="Automated candidate · unreviewed" />
              ) : null}
              <span className="px-1 text-xs leading-5 text-muted">{new Date(event.published_at).toLocaleString()}</span>
              {onEventSelect ? (
                <button
                  type="button"
                  className="secondary-action ml-auto min-h-11 px-3 py-1.5 text-xs"
                  aria-pressed={selected}
                  title={`Focus ${event.title}`}
                  onClick={() => onEventSelect(event.id)}
                >
                  <MapPinned className="h-4 w-4" />
                  Focus
                </button>
              ) : null}
            </div>
            <h3 className="mt-3 text-lg font-semibold">{event.title}</h3>
            <p className="mt-2 text-sm leading-6 text-muted">{event.summary}</p>
            <p className="mt-2 text-sm leading-6 text-muted">{event.why_it_matters}</p>
            <div className="mt-3 flex flex-wrap gap-2.5 text-xs leading-5 text-muted">
              <span>{event.country_region_keys.join(", ")}</span>
              <span>{event.sector_keys.join(", ")}</span>
              <span>{event.evidence_count} evidence items</span>
            </div>
            <div className="mt-3 flex flex-wrap gap-3 text-sm">
              {event.source_links.map((source) => {
                const sourceHref = safeExternalUrl(source.url);
                if (!sourceHref) return <SourceBadge key={`${event.id}-${source.source_key}`} label={source.label} />;
                return (
                  <a
                    key={`${event.id}-${source.source_key}`}
                    className="focus-ring inline-flex min-h-11 items-center gap-1 rounded-md px-2 text-accent hover:underline"
                    href={sourceHref}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {source.label}
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                );
              })}
            </div>
          </article>
        );
      })}
    </div>
  );
}
