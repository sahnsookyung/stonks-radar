import type { CalendarItem } from "@frw/shared-types";
import { FreshnessBadge, SourceBadge } from "./Badge";

export function CalendarTable({ items }: { items: CalendarItem[] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-line bg-panel">
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
                <div className="text-xs text-muted">
                  {item.time_precision === "date_only"
                    ? "date only"
                    : item.scheduled_at
                      ? new Date(item.scheduled_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit"
                        })
                      : "estimated"}
                  {" "}
                  {item.timezone}
                </div>
              </td>
              <td className="px-3 py-3">
                <div className="font-semibold">{item.title}</div>
                <div className="mt-1 flex flex-wrap gap-1">
                  <FreshnessBadge value={item.freshness} />
                  <span className="badge border border-line bg-panel text-muted">{item.country_region_key}</span>
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
                <SourceBadge label={item.source} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
