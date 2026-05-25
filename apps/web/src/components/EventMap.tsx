import type { PublicEvent } from "@frw/shared-types";
import type maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";

interface EventMapProps {
  events: PublicEvent[];
  heightClass?: string;
  footer?: string;
  loadStrategy?: "visible" | "idle-visible" | "immediate";
}

export function EventMap({
  events,
  heightClass = "h-[540px] md:h-[680px]",
  footer = "Static approved events only. Base boundaries: Natural Earth Admin 0, 1:110m, vendored as local GeoJSON.",
  loadStrategy = "visible"
}: EventMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const maplibreRef = useRef<typeof maplibregl | null>(null);
  const markerRefs = useRef<maplibregl.Marker[]>([]);
  const hoveredCountryRef = useRef<string | null>(null);
  const eventsRef = useRef(events);
  const [shouldLoad, setShouldLoad] = useState(loadStrategy === "immediate");
  const [isReady, setIsReady] = useState(false);
  const [hoveredCountry, setHoveredCountry] = useState<HoveredCountry | null>(null);
  const center = useMemo<[number, number]>(() => [18, 24], []);

  useEffect(() => {
    eventsRef.current = events;
  }, [events]);

  useEffect(() => {
    if (shouldLoad || !containerRef.current) return;
    const element = containerRef.current;
    let idleHandle: number | null = null;
    const load = () => {
      if (loadStrategy === "idle-visible" && "requestIdleCallback" in window) {
        idleHandle = window.requestIdleCallback(() => setShouldLoad(true), { timeout: 1200 });
        return;
      }
      if (loadStrategy === "idle-visible") {
        idleHandle = window.setTimeout(() => setShouldLoad(true), 300);
        return;
      }
      setShouldLoad(true);
    };
    if (loadStrategy === "immediate" || !("IntersectionObserver" in window)) {
      load();
      return () => {
        if (idleHandle !== null) cancelDeferredLoad(idleHandle);
      };
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        observer.disconnect();
        load();
      },
      { rootMargin: "160px" }
    );
    observer.observe(element);
    return () => {
      observer.disconnect();
      if (idleHandle !== null) cancelDeferredLoad(idleHandle);
    };
  }, [loadStrategy, shouldLoad]);

  useEffect(() => {
    if (!shouldLoad || !containerRef.current || mapRef.current) return;
    let disposed = false;
    void Promise.all([import("maplibre-gl"), import("maplibre-gl/dist/maplibre-gl.css")]).then(([module]) => {
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
              filter: antimeridianSafeCountryFilter(),
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
              filter: antimeridianSafeCountryFilter(),
              paint: {
                "line-color": "#496a82",
                "line-width": ["interpolate", ["linear"], ["zoom"], 1, 0.65, 3, 1.1],
                "line-opacity": 0.9
              }
            },
            {
              id: "country-hover-fill",
              type: "fill",
              source: "countries",
              filter: countryHoverFilter(""),
              paint: {
                "fill-color": "#74d8f3",
                "fill-opacity": 0.24
              }
            },
            {
              id: "country-hover-outline",
              type: "line",
              source: "countries",
              filter: countryHoverFilter(""),
              paint: {
                "line-color": "#9be7ff",
                "line-width": 1.8,
                "line-opacity": 0.95
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
      if (import.meta.env.DEV) {
        (window as Window & { __stonksRadarMap?: maplibregl.Map }).__stonksRadarMap = mapRef.current;
      }
      mapRef.current.on("load", () => {
        mapRef.current?.fitBounds(
          [
            [-180, -58],
            [180, 78]
          ],
          { padding: 24, duration: 0 }
        );
        mapRef.current?.resize();
        wireCountryHover(mapRef.current, setHoveredCountry, hoveredCountryRef);
        syncMarkers(maplibre, mapRef.current, markerRefs, eventsRef.current);
        setIsReady(true);
      });
    });
    return () => {
      disposed = true;
      if (import.meta.env.DEV) {
        delete (window as Window & { __stonksRadarMap?: maplibregl.Map }).__stonksRadarMap;
      }
      mapRef.current?.remove();
      mapRef.current = null;
      setIsReady(false);
    };
  }, [center, shouldLoad]);

  useEffect(() => {
    if (!mapRef.current || !maplibreRef.current) return;
    syncMarkers(maplibreRef.current, mapRef.current, markerRefs, events);
  }, [events]);

  return (
    <div className={`relative overflow-hidden rounded-md border border-line bg-panel contain-layout ${heightClass}`}>
      <div ref={containerRef} className="h-full w-full" data-testid="event-map-container" />
      {hoveredCountry ? (
        <div
          className="pointer-events-none absolute z-10 rounded border border-line bg-panel/95 px-3 py-2 text-xs font-semibold text-text shadow-panel"
          data-testid="country-hover-tooltip"
          style={{
            left: hoveredCountry.x,
            top: hoveredCountry.y,
            transform: "translateY(-50%)"
          }}
        >
          {hoveredCountry.name}
        </div>
      ) : null}
      {!isReady ? (
        <div className="absolute inset-0 grid place-items-center bg-panelAlt text-center text-xs font-semibold uppercase text-muted">
          <span>{shouldLoad ? "Loading map" : "Map loads on view"}</span>
        </div>
      ) : null}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-panel/90 px-5 py-3 text-xs leading-5 text-muted">
        {footer}
      </div>
    </div>
  );
}

type HoveredCountry = {
  name: string;
  x: number;
  y: number;
};

function cancelDeferredLoad(handle: number) {
  const cancelIdle = window.cancelIdleCallback;
  if (typeof cancelIdle === "function") {
    cancelIdle(handle);
    return;
  }
  globalThis.clearTimeout(handle);
}

function wireCountryHover(
  map: maplibregl.Map | null,
  setHoveredCountry: (country: HoveredCountry | null) => void,
  hoveredCountryRef: MutableRefObject<string | null>
) {
  if (!map) return;

  const clearHover = () => {
    if (hoveredCountryRef.current !== null) {
      map.setFilter("country-hover-fill", countryHoverFilter(""));
      map.setFilter("country-hover-outline", countryHoverFilter(""));
      hoveredCountryRef.current = null;
    }
    map.getCanvas().style.cursor = "";
    setHoveredCountry(null);
  };

  const canvas = map.getCanvas();
  const eventTarget = map.getContainer().parentElement ?? map.getContainer();
  const handleMove = (event: MouseEvent) => {
    const rect = canvas.getBoundingClientRect();
    const point: [number, number] = [event.clientX - rect.left, event.clientY - rect.top];
    const country = map.queryRenderedFeatures(point, {
      layers: ["monitored-country-fill", "countries-fill"]
    })[0];
    if (!country) {
      clearHover();
      return;
    }

    const countryName = typeof country.properties?.name === "string" ? country.properties.name : "";
    if (!countryName) {
      clearHover();
      return;
    }

    if (hoveredCountryRef.current !== countryName) {
      hoveredCountryRef.current = countryName;
      map.setFilter("country-hover-fill", countryHoverFilter(countryName));
      map.setFilter("country-hover-outline", countryHoverFilter(countryName));
    }
    map.getCanvas().style.cursor = "pointer";
    setHoveredCountry({
      name: countryName,
      x: Math.min(point[0] + 12, Math.max(12, canvas.clientWidth - 180)),
      y: Math.min(Math.max(point[1], 22), Math.max(22, canvas.clientHeight - 22))
    });
  };

  eventTarget.addEventListener("pointermove", handleMove);
  eventTarget.addEventListener("click", handleMove);
  eventTarget.addEventListener("mouseleave", clearHover);
}

function countryHoverFilter(countryName: string) {
  return [
    "all",
    ["==", ["get", "name"], countryName],
    ["!=", ["get", "crossesAntimeridian"], true],
    ["!=", ["get", "antimeridianRepaired"], true],
    ["!=", ["get", "antimeridianHoverUnsafe"], true]
  ] as maplibregl.FilterSpecification;
}

function antimeridianSafeCountryFilter() {
  return ["!=", ["get", "crossesAntimeridian"], true] as maplibregl.FilterSpecification;
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
    el.className = "grid h-11 w-11 place-items-center rounded-full bg-transparent focus:outline-none focus:ring-2 focus:ring-accent";
    el.setAttribute("aria-label", event.title);
    el.title = event.title;
    const dot = document.createElement("span");
    dot.className = "h-4 w-4 rounded-full border-2 border-panel bg-accent shadow-panel";
    el.appendChild(dot);
    return new maplibre.Marker({ element: el })
      .setLngLat([event.longitude, event.latitude])
      .setPopup(
        new maplibre.Popup({
          closeButton: false,
          className: "stonks-map-popup",
          maxWidth: "300px"
        }).setDOMContent(createEventPopup(event))
      )
      .addTo(map);
  });
}

function createEventPopup(event: PublicEvent) {
  const wrapper = document.createElement("div");
  wrapper.className = "grid gap-1.5 p-3 text-left";

  const title = document.createElement("div");
  title.className = "text-sm font-semibold leading-5 text-ink";
  title.textContent = event.title;
  wrapper.appendChild(title);

  const summary = document.createElement("p");
  summary.className = "text-xs leading-5 text-muted";
  summary.textContent = event.summary || event.why_it_matters;
  wrapper.appendChild(summary);

  const meta = document.createElement("div");
  meta.className = "text-[11px] font-semibold uppercase leading-4 text-accent";
  meta.textContent = `${event.severity} · ${event.evidence_count} evidence`;
  wrapper.appendChild(meta);

  return wrapper;
}
