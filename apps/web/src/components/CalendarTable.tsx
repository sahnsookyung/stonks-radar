import type { CalendarItem } from "@frw/shared-types";
import { ExternalLink } from "lucide-react";
import { FreshnessBadge, SourceBadge } from "./Badge";

export function CalendarTable({ items }: Readonly<{ items: CalendarItem[] }>) {
  return (
    <>
      <div className="grid gap-3 md:hidden">
        {items.map((item) => (
          <article key={item.id} className="panel min-w-0 p-4">
            <div className="flex min-w-0 items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="safe-text text-sm font-semibold leading-5">{item.title}</div>
                <div className="mt-1 text-xs leading-5 text-muted">
                  {item.scheduled_local_date} · {calendarTimeLabel(item)}
                </div>
              </div>
              <FreshnessBadge value={item.freshness} />
            </div>
            <dl className="mt-4 grid gap-2 text-xs leading-5 text-muted">
              <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-2">
                <dt className="font-semibold uppercase text-muted">Expectation</dt>
                <dd className="safe-text text-ink">{item.expectation_value ?? item.expectation_type}</dd>
              </div>
              <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-2">
                <dt className="font-semibold uppercase text-muted">Actual</dt>
                <dd className="safe-text">{item.actual_value ?? "pending"}</dd>
              </div>
              <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-2">
                <dt className="font-semibold uppercase text-muted">Previous</dt>
                <dd className="safe-text">{item.previous_value ?? "n/a"}</dd>
              </div>
              <div className="grid grid-cols-[112px_minmax(0,1fr)] gap-2">
                <dt className="font-semibold uppercase text-muted">Surprise</dt>
                <dd className="safe-text">{item.surprise ?? "not computed"}</dd>
              </div>
            </dl>
            <div className="mt-3 flex flex-wrap gap-2">
              <span className="badge whitespace-nowrap border border-line bg-panel text-muted">{item.country_region_key}</span>
              <CalendarSourceLink item={item} />
            </div>
          </article>
        ))}
      </div>
      <div className="table-surface hidden md:block" data-allow-horizontal-scroll aria-label="Calendar table">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-panelAlt text-xs uppercase text-muted">
            <tr>
              <th className="px-3 py-3">Date</th>
              <th className="px-3 py-3">Event</th>
              <th className="px-3 py-3">Expectation</th>
              <th className="px-3 py-3">Actual</th>
              <th className="px-3 py-3">Previous</th>
              <th className="px-3 py-3">Surprise</th>
              <th className="px-3 py-3">Source</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((item) => (
              <tr key={item.id} className="align-top">
                <td className="px-3 py-3">
                  <div className="font-medium">{item.scheduled_local_date}</div>
                  <div className="text-xs text-muted">{calendarTimeLabel(item)}</div>
                </td>
                <td className="px-3 py-3">
                  <div className="font-semibold">{item.title}</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    <FreshnessBadge value={item.freshness} />
                    <span className="badge whitespace-nowrap border border-line bg-panel text-muted">{item.country_region_key}</span>
                  </div>
                </td>
                <td className="px-3 py-3">
                  <div className="font-medium">{item.expectation_type}</div>
                  <div className="text-muted">{item.expectation_value ?? "n/a"}</div>
                </td>
                <td className="px-3 py-3">{item.actual_value ?? "pending"}</td>
                <td className="px-3 py-3">{item.previous_value ?? "n/a"}</td>
                <td className="px-3 py-3">{item.surprise ?? "not computed"}</td>
                <td className="px-3 py-3">
                  <CalendarSourceLink item={item} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function CalendarSourceLink({ item }: Readonly<{ item: CalendarItem }>) {
  if (!item.source_url) return <SourceBadge label={item.source} />;
  return (
    <a
      href={item.source_url}
      target={item.source_url.startsWith("http") ? "_blank" : undefined}
      rel="noreferrer"
      className="focus-ring inline-flex min-h-8 items-center gap-1 rounded text-xs font-semibold text-accent hover:text-accentSoft"
    >
      {item.source}
      <ExternalLink className="h-3.5 w-3.5" />
    </a>
  );
}

function calendarTimeLabel(item: CalendarItem) {
  if (item.time_precision === "date_only") return `date only ${item.timezone}`;
  if (!item.scheduled_at) return `estimated ${item.timezone}`;
  return `${new Date(item.scheduled_at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit"
  })} ${item.timezone}`;
}
