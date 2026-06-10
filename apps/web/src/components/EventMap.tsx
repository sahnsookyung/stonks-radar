import type { NewsMapPoint, PublicEvent } from "@frw/shared-types";
import type { Feature, Geometry } from "geojson";
import type maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

type MutableRef<T> = { current: T };

interface EventMapProps extends Readonly<{
  events: PublicEvent[];
  mapPoints?: NewsMapPoint[];
  selectedMapPointId?: string | null;
  onMapPointSelect?: (eventId: string) => void;
  heightClass?: string;
  footer?: string;
  loadStrategy?: "visible" | "idle-visible" | "immediate";
}> {}

type EventMapDebugWindow = Window & { __stonksRadarMap?: maplibregl.Map };

function shouldExposeMapDebugHook() {
  return import.meta.env.DEV || (typeof navigator !== "undefined" && navigator.webdriver);
}

export function EventMap({
  events,
  mapPoints = [],
  selectedMapPointId = null,
  onMapPointSelect,
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
  const mapPointsRef = useRef(mapPoints);
  const onMapPointSelectRef = useRef(onMapPointSelect);
  const [shouldLoad, setShouldLoad] = useState(loadStrategy === "immediate");
  const [isReady, setIsReady] = useState(false);
  const [hoveredCountry, setHoveredCountry] = useState<HoveredCountry | null>(null);
  const center = useMemo<[number, number]>(() => [18, 24], []);

  useEffect(() => {
    eventsRef.current = events;
  }, [events]);

  useEffect(() => {
    mapPointsRef.current = mapPoints;
  }, [mapPoints]);

  useEffect(() => {
    onMapPointSelectRef.current = onMapPointSelect;
  }, [onMapPointSelect]);

  useEffect(() => {
    if (shouldLoad || !containerRef.current) return;
    const element = containerRef.current;
    let idleHandle: number | null = null;
    const load = () => {
      if (loadStrategy === "idle-visible" && "requestIdleCallback" in globalThis.window) {
        idleHandle = globalThis.window.requestIdleCallback(() => setShouldLoad(true), { timeout: 1200 });
        return;
      }
      if (loadStrategy === "idle-visible") {
        idleHandle = globalThis.window.setTimeout(() => setShouldLoad(true), 300);
        return;
      }
      setShouldLoad(true);
    };
    if (loadStrategy === "immediate" || !("IntersectionObserver" in globalThis.window)) {
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
      if (shouldExposeMapDebugHook()) {
        (globalThis.window as EventMapDebugWindow).__stonksRadarMap = mapRef.current;
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
        syncNewsMapPoints(maplibre, mapRef.current, mapPointsRef.current, onMapPointSelectRef);
        syncMarkers(maplibre, mapRef.current, markerRefs, mapPointsRef.current.length ? [] : eventsRef.current);
        setIsReady(true);
      });
    });
    return () => {
      disposed = true;
      if (shouldExposeMapDebugHook()) {
        delete (globalThis.window as EventMapDebugWindow).__stonksRadarMap;
      }
      mapRef.current?.remove();
      mapRef.current = null;
      setIsReady(false);
    };
  }, [center, shouldLoad]);

  useEffect(() => {
    if (!mapRef.current || !maplibreRef.current) return;
    syncMarkers(maplibreRef.current, mapRef.current, markerRefs, mapPoints.length ? [] : events);
  }, [events, mapPoints.length]);

  useEffect(() => {
    if (!mapRef.current || !maplibreRef.current) return;
    syncNewsMapPoints(maplibreRef.current, mapRef.current, mapPoints, onMapPointSelectRef);
    if (mapPoints.length) {
      syncMarkers(maplibreRef.current, mapRef.current, markerRefs, []);
    }
  }, [mapPoints]);

  useEffect(() => {
    if (!mapRef.current || !selectedMapPointId) return;
    const selected = mapPoints.find((point) => point.event_id === selectedMapPointId || point.point_id === selectedMapPointId);
    if (!selected || !isValidLngLat(selected.longitude, selected.latitude)) return;
    mapRef.current.easeTo({
      center: [selected.longitude, selected.latitude],
      duration: 350
    });
  }, [mapPoints, selectedMapPointId]);

  useEffect(() => {
    if (!shouldLoad || !containerRef.current) return;
    const element = containerRef.current;
    let frame = 0;
    const scheduleResize = () => {
      globalThis.window.cancelAnimationFrame(frame);
      frame = globalThis.window.requestAnimationFrame(() => mapRef.current?.resize());
    };
    const ResizeObserverCtor = globalThis.window.ResizeObserver;
    if (typeof ResizeObserverCtor === "function") {
      const observer = new ResizeObserverCtor(scheduleResize);
      observer.observe(element);
      scheduleResize();
      return () => {
        observer.disconnect();
        globalThis.window.cancelAnimationFrame(frame);
      };
    }
    globalThis.window.addEventListener("resize", scheduleResize);
    scheduleResize();
    return () => {
      globalThis.window.removeEventListener("resize", scheduleResize);
      globalThis.window.cancelAnimationFrame(frame);
    };
  }, [shouldLoad]);

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
      {!isReady && (
        <div className="absolute inset-0 grid place-items-center bg-panelAlt text-center text-xs font-semibold uppercase text-muted">
          <span>{shouldLoad ? "Loading map" : "Map loads on view"}</span>
        </div>
      )}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-panel/90 px-4 py-3 text-xs leading-5 text-muted sm:px-5">
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

const NEWS_SOURCE_ID = "breaking-news-points";
const NEWS_CLUSTER_LAYER_ID = "breaking-news-clusters";
const NEWS_CLUSTER_COUNT_LAYER_ID = "breaking-news-cluster-count";
const NEWS_POINT_LAYER_ID = "breaking-news-unclustered";
const wiredClusterMaps = new WeakSet<maplibregl.Map>();
const clusterPopupRefs = new WeakMap<maplibregl.Map, maplibregl.Popup>();
const clusterPopupModes = new WeakMap<maplibregl.Map, "hover" | "click">();

function cancelDeferredLoad(handle: number) {
  const cancelIdle = globalThis.window.cancelIdleCallback;
  if (typeof cancelIdle === "function") {
    cancelIdle(handle);
    return;
  }
  globalThis.clearTimeout(handle);
}

function wireCountryHover(
  map: maplibregl.Map | null,
  setHoveredCountry: (country: HoveredCountry | null) => void,
  hoveredCountryRef: MutableRef<string | null>
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
  eventTarget.addEventListener("mousemove", handleMove);
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
  markerRefs: MutableRef<maplibregl.Marker[]>,
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

function syncNewsMapPoints(
  maplibre: typeof maplibregl,
  map: maplibregl.Map | null,
  mapPoints: NewsMapPoint[],
  onMapPointSelectRef: MutableRef<((eventId: string) => void) | undefined>
) {
  if (!map || !map.isStyleLoaded()) return;
  ensureNewsPointLayers(maplibre, map, onMapPointSelectRef);
  const source = map.getSource(NEWS_SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
  source?.setData(createNewsFeatureCollection(mapPoints));
}

function ensureNewsPointLayers(
  maplibre: typeof maplibregl,
  map: maplibregl.Map,
  onMapPointSelectRef: MutableRef<((eventId: string) => void) | undefined>
) {
  if (!map.getSource(NEWS_SOURCE_ID)) {
    map.addSource(NEWS_SOURCE_ID, {
      type: "geojson",
      data: createNewsFeatureCollection([]),
      cluster: true,
      clusterRadius: 44,
      clusterMaxZoom: 6
    });
  }
  if (!map.getLayer(NEWS_CLUSTER_LAYER_ID)) {
    map.addLayer({
      id: NEWS_CLUSTER_LAYER_ID,
      type: "circle",
      source: NEWS_SOURCE_ID,
      filter: ["has", "point_count"],
      paint: {
        "circle-color": ["step", ["get", "point_count"], "#38bdf8", 5, "#22d3ee", 15, "#f59e0b"],
        "circle-radius": ["step", ["get", "point_count"], 19, 5, 24, 15, 30],
        "circle-stroke-color": "#07131f",
        "circle-stroke-width": 2,
        "circle-opacity": 0.95
      }
    });
  }
  if (!map.getLayer(NEWS_CLUSTER_COUNT_LAYER_ID)) {
    map.addLayer({
      id: NEWS_CLUSTER_COUNT_LAYER_ID,
      type: "symbol",
      source: NEWS_SOURCE_ID,
      filter: ["has", "point_count"],
      layout: {
        "text-field": ["get", "point_count_abbreviated"],
        "text-font": ["Open Sans Semibold"],
        "text-size": 12
      },
      paint: {
        "text-color": "#07131f"
      }
    });
  }
  if (!map.getLayer(NEWS_POINT_LAYER_ID)) {
    map.addLayer({
      id: NEWS_POINT_LAYER_ID,
      type: "circle",
      source: NEWS_SOURCE_ID,
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": [
          "match",
          ["get", "severity"],
          "critical",
          "#fb7185",
          "high",
          "#f59e0b",
          "medium",
          "#22d3ee",
          "#67e8f9"
        ],
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 6, 4, 10],
        "circle-stroke-color": "#07131f",
        "circle-stroke-width": 2,
        "circle-opacity": 0.96
      }
    });
    map.on("click", NEWS_POINT_LAYER_ID, (event) => {
      const feature = event.features?.[0];
      const eventId = typeof feature?.properties?.event_id === "string" ? feature.properties.event_id : "";
      if (!eventId || !feature) return;
      event.originalEvent.preventDefault();
      event.originalEvent.stopPropagation();
      onMapPointSelectRef.current?.(eventId);
      const coordinates = feature.geometry.type === "Point" ? feature.geometry.coordinates : null;
      if (!Array.isArray(coordinates) || coordinates.length < 2) return;
      new maplibre.Popup({
        closeButton: false,
        className: "stonks-map-popup",
        maxWidth: "320px"
      })
        .setLngLat([Number(coordinates[0]), Number(coordinates[1])])
        .setDOMContent(createNewsMapPointPopup(feature.properties))
        .addTo(map);
    });
    map.on("mouseenter", NEWS_POINT_LAYER_ID, () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", NEWS_POINT_LAYER_ID, () => {
      map.getCanvas().style.cursor = "";
    });
  }
  if (wiredClusterMaps.has(map)) return;
  wiredClusterMaps.add(map);
  map.on("click", NEWS_CLUSTER_LAYER_ID, (event) => {
    const feature = event.features?.[0];
    if (!feature) return;
    event.originalEvent.preventDefault();
    event.originalEvent.stopPropagation();
    void showNewsClusterPopup(maplibre, map, feature, "click");
  });
  map.on("mouseenter", NEWS_CLUSTER_LAYER_ID, (event) => {
    map.getCanvas().style.cursor = "pointer";
    const feature = event.features?.[0];
    if (!feature) return;
    void showNewsClusterPopup(maplibre, map, feature, "hover");
  });
  map.on("mouseleave", NEWS_CLUSTER_LAYER_ID, () => {
    map.getCanvas().style.cursor = "";
    if (clusterPopupModes.get(map) !== "click") {
      closeNewsClusterPopup(map);
    }
  });
}

function createNewsFeatureCollection(mapPoints: NewsMapPoint[]) {
  return {
    type: "FeatureCollection" as const,
    features: mapPoints
      .filter((point) => isValidLngLat(point.longitude, point.latitude))
      .map((point) => ({
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [point.longitude, point.latitude]
        },
        properties: {
          point_id: point.point_id,
          event_id: point.event_id,
          title: point.title,
          summary: point.summary,
          area_label: point.area_label,
          severity: point.severity,
          urgency_score: point.urgency_score,
          source_count: point.source_count,
          source_url: point.source_url ?? "",
          source_published_at: point.source_published_at
        }
      }))
  };
}

type ClusterLeafSource = maplibregl.GeoJSONSource & {
  getClusterLeaves: (
    clusterId: number,
    limit: number,
    offset: number
  ) => Promise<Array<maplibregl.MapGeoJSONFeature | Feature<Geometry>>>;
};

async function showNewsClusterPopup(
  maplibre: typeof maplibregl,
  map: maplibregl.Map,
  feature: maplibregl.MapGeoJSONFeature,
  mode: "hover" | "click"
) {
  const clusterId = feature.properties?.cluster_id;
  const coordinates = feature.geometry.type === "Point" ? feature.geometry.coordinates : null;
  const source = map.getSource(NEWS_SOURCE_ID) as ClusterLeafSource | undefined;
  if (typeof clusterId !== "number" || !source || !Array.isArray(coordinates) || coordinates.length < 2) return;
  const total = Number(feature.properties?.point_count ?? 0);
  let leaves: Array<maplibregl.MapGeoJSONFeature | Feature<Geometry>> = [];
  try {
    leaves = await source.getClusterLeaves(clusterId, 10, 0);
  } catch {
    leaves = [];
  }
  if (!leaves.length) return;
  closeNewsClusterPopup(map);
  const popup = new maplibre.Popup({
    closeButton: mode === "click",
    closeOnClick: mode === "click",
    className: "stonks-map-popup stonks-news-cluster-popup",
    maxWidth: "400px"
  })
    .setLngLat([Number(coordinates[0]), Number(coordinates[1])])
    .setDOMContent(createNewsClusterPopup(leaves, total))
    .addTo(map);
  clusterPopupRefs.set(map, popup);
  clusterPopupModes.set(map, mode);
  popup.on("close", () => {
    if (clusterPopupRefs.get(map) === popup) {
      clusterPopupRefs.delete(map);
      clusterPopupModes.delete(map);
    }
  });
}

function closeNewsClusterPopup(map: maplibregl.Map) {
  const popup = clusterPopupRefs.get(map);
  if (popup) popup.remove();
  clusterPopupRefs.delete(map);
  clusterPopupModes.delete(map);
}

function createNewsClusterPopup(
  leaves: Array<maplibregl.MapGeoJSONFeature | Feature<Geometry>>,
  total: number
) {
  const wrapper = document.createElement("div");
  wrapper.className = "grid max-h-[360px] gap-2 overflow-y-auto p-3 text-left";

  const title = document.createElement("div");
  title.className = "text-xs font-semibold uppercase tracking-wide text-accent";
  title.textContent = `${total || leaves.length} mapped news item${(total || leaves.length) === 1 ? "" : "s"}`;
  wrapper.appendChild(title);

  const list = document.createElement("ul");
  list.className = "grid gap-2";
  for (const leaf of leaves) {
    const item = document.createElement("li");
    item.className = "grid gap-1 rounded border border-line bg-panelAlt/80 p-2";
    const sourceUrl = safeHttpUrl(safeProperty(leaf.properties, "source_url", 2048));
    const headline = document.createElement(sourceUrl ? "a" : "div");
    headline.className = "text-xs font-semibold leading-5 text-ink hover:text-accent";
    headline.textContent = safeProperty(leaf.properties, "title") || "Mapped market event";
    if (sourceUrl && headline instanceof HTMLAnchorElement) {
      headline.href = sourceUrl;
      headline.target = "_blank";
      headline.rel = "noopener noreferrer";
    }
    item.appendChild(headline);

    const meta = document.createElement("div");
    meta.className = "text-[11px] leading-4 text-muted";
    meta.textContent = [
      safeProperty(leaf.properties, "area_label"),
      safeProperty(leaf.properties, "severity"),
      `urgency ${safeProperty(leaf.properties, "urgency_score")}`
    ]
      .filter(Boolean)
      .join(" · ");
    item.appendChild(meta);
    list.appendChild(item);
  }
  wrapper.appendChild(list);

  const hiddenCount = Math.max(0, total - leaves.length);
  if (hiddenCount) {
    const more = document.createElement("div");
    more.className = "text-[11px] font-semibold text-muted";
    more.textContent = `+${hiddenCount} more in this cluster`;
    wrapper.appendChild(more);
  }
  return wrapper;
}

function isValidLngLat(longitude: number, latitude: number) {
  return (
    Number.isFinite(longitude) &&
    Number.isFinite(latitude) &&
    longitude >= -180 &&
    longitude <= 180 &&
    latitude >= -90 &&
    latitude <= 90 &&
    (Math.abs(longitude) > 0.0001 || Math.abs(latitude) > 0.0001)
  );
}

function createNewsMapPointPopup(properties: maplibregl.MapGeoJSONFeature["properties"]) {
  const wrapper = document.createElement("div");
  wrapper.className = "grid gap-1.5 p-3 text-left";

  const area = document.createElement("div");
  area.className = "text-[11px] font-semibold uppercase leading-4 text-accent";
  area.textContent = safeProperty(properties, "area_label");
  wrapper.appendChild(area);

  const title = document.createElement("div");
  title.className = "text-sm font-semibold leading-5 text-ink";
  title.textContent = safeProperty(properties, "title");
  wrapper.appendChild(title);

  const summary = document.createElement("p");
  summary.className = "text-xs leading-5 text-muted";
  summary.textContent = safeProperty(properties, "summary");
  wrapper.appendChild(summary);

  const meta = document.createElement("div");
  meta.className = "text-[11px] font-semibold uppercase leading-4 text-warning";
  meta.textContent = `${safeProperty(properties, "severity")} · urgency ${safeProperty(properties, "urgency_score")}`;
  wrapper.appendChild(meta);

  const sourceUrl = safeHttpUrl(safeProperty(properties, "source_url", 2048));
  if (sourceUrl) {
    const source = document.createElement("a");
    source.className = "text-xs font-semibold text-accent hover:text-accentSoft";
    source.href = sourceUrl;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    source.textContent = "Source";
    wrapper.appendChild(source);
  }

  return wrapper;
}

function safeProperty(properties: Record<string, unknown> | null | undefined, key: string, maxLength = 320) {
  const value = properties?.[key];
  if (typeof value === "number") return String(value);
  if (typeof value !== "string") return "";
  return value.replace(/[\u0000-\u001F]+/g, " ").slice(0, maxLength);
}

function safeHttpUrl(value: string) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") return "";
    return url.toString();
  } catch {
    return "";
  }
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
