import type { PublicEvent } from "@frw/shared-types";
import type maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, type MutableRefObject } from "react";

interface EventMapProps {
  events: PublicEvent[];
  heightClass?: string;
  footer?: string;
}

export function EventMap({
  events,
  heightClass = "h-[420px]",
  footer = "Static approved events only. Base boundaries: Natural Earth Admin 0, 1:110m, vendored as local GeoJSON."
}: EventMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const maplibreRef = useRef<typeof maplibregl | null>(null);
  const markerRefs = useRef<maplibregl.Marker[]>([]);
  const eventsRef = useRef(events);
  const center = useMemo<[number, number]>(() => [18, 24], []);

  useEffect(() => {
    eventsRef.current = events;
  }, [events]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    let disposed = false;
    void import("maplibre-gl").then((module) => {
      if (disposed || !containerRef.current) return;
      const maplibre = module.default;
      maplibreRef.current = maplibre;
      mapRef.current = new maplibre.Map({
        container: containerRef.current,
        style: {
          version: 8,
          sources: {
            countries: {
              type: "geojson",
              data: "/map/natural-earth/countries-110m.geojson"
            }
          },
          layers: [
            {
              id: "ocean",
              type: "background",
              paint: { "background-color": "#07131f" }
            },
            {
              id: "countries-fill",
              type: "fill",
              source: "countries",
              paint: {
                "fill-color": "#152130",
                "fill-opacity": 0.92
              }
            },
            {
              id: "monitored-country-fill",
              type: "fill",
              source: "countries",
              filter: [
                "in",
                ["get", "name"],
                [
                  "literal",
                  [
                    "United States of America",
                    "Brazil",
                    "South Korea",
                    "United Kingdom",
                    "Germany",
                    "China",
                    "Taiwan",
                    "Japan"
                  ]
                ]
              ],
              paint: {
                "fill-color": "#1f3d4a",
                "fill-opacity": 0.95
              }
            },
            {
              id: "countries-outline",
              type: "line",
              source: "countries",
              paint: {
                "line-color": "#345267",
                "line-width": 0.7,
                "line-opacity": 0.85
              }
            }
          ]
        },
        center,
        zoom: 1.05,
        renderWorldCopies: false,
        attributionControl: false,
        interactive: true
      });
      mapRef.current.on("load", () => {
        mapRef.current?.fitBounds(
          [
            [-180, -58],
            [180, 78]
          ],
          { padding: 24, duration: 0 }
        );
        mapRef.current?.resize();
        syncMarkers(maplibre, mapRef.current, markerRefs, eventsRef.current);
      });
    });
    return () => {
      disposed = true;
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [center]);

  useEffect(() => {
    if (!mapRef.current || !maplibreRef.current) return;
    syncMarkers(maplibreRef.current, mapRef.current, markerRefs, events);
  }, [events]);

  return (
    <div className={`relative overflow-hidden rounded-md border border-line bg-panel ${heightClass}`}>
      <div ref={containerRef} className="absolute inset-0" />
      <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-panel/90 px-5 py-3 text-xs leading-5 text-muted">
        {footer}
      </div>
    </div>
  );
}

function syncMarkers(
  maplibre: typeof maplibregl,
  map: maplibregl.Map | null,
  markerRefs: MutableRefObject<maplibregl.Marker[]>,
  events: PublicEvent[]
) {
  if (!map) return;
  markerRefs.current.forEach((marker) => marker.remove());
  markerRefs.current = events.map((event) => {
    const el = document.createElement("button");
    el.type = "button";
    el.className =
      "h-4 w-4 rounded-full border-2 border-panel bg-accent shadow-panel focus:outline-none focus:ring-2 focus:ring-accent";
    el.title = event.title;
    return new maplibre.Marker({ element: el })
      .setLngLat([event.longitude, event.latitude])
      .setPopup(new maplibre.Popup({ closeButton: false }).setText(event.title))
      .addTo(map);
  });
}
