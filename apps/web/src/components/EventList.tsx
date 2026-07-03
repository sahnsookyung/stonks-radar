import type { PublicEvent } from "@frw/shared-types";
import { ExternalLink } from "lucide-react";
import { FreshnessBadge, SeverityBadge, SourceBadge } from "./Badge";
import { safeExternalUrl } from "../lib/safeExternalUrl";

export function EventList({ events }: Readonly<{ events: PublicEvent[] }>) {
  return (
    <div className="grid gap-3">
      {events.map((event) => (
        <article key={event.id} className="panel p-5">
          <div className="flex flex-wrap items-center gap-2.5">
            <SeverityBadge value={event.severity} />
            <FreshnessBadge value={event.freshness} />
            <SourceBadge label={event.source_strength} />
            <span className="px-1 text-xs leading-5 text-muted">{new Date(event.published_at).toLocaleString()}</span>
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
      ))}
    </div>
  );
}
