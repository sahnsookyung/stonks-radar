import type {
  CalendarSnapshotData,
  CountryRegionSnapshotData,
  FundPortfolioSnapshotData,
  HomeSnapshotData,
  Locale,
  MapEventsData,
  NewsEventSnapshotData,
  NewsIndexSnapshotData,
  NewsRegionSnapshotData,
  NewsTickerSnapshotData,
  NewsTopicSnapshotData,
  ReferenceEntitySnapshotData,
  ScenarioBasketSnapshotData,
  SectorSnapshotData,
  SnapshotEnvelope,
  SnapshotManifest,
  SourceStatusSnapshotData
} from "@frw/shared-types";

const manifestUrl = "/public/latest/manifest.json";

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url, {
    headers: {
      Accept: "application/json"
    }
  });
  if (!response.ok) {
    throw new Error(`Failed to load ${url}: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function getManifest(): Promise<SnapshotManifest> {
  return fetchJson<SnapshotManifest>(manifestUrl);
}

export async function getSnapshot<T>(
  objectKey: string,
  locale: Locale
): Promise<SnapshotEnvelope<T>> {
  const manifest = await getManifest();
  const path = manifest.objects[objectKey]?.[locale];
  if (!path) {
    throw new Error(`Snapshot object ${objectKey}/${locale} is not in the manifest`);
  }
  return fetchJson<SnapshotEnvelope<T>>(`/${path}`);
}

export const snapshotQueries = {
  home: (locale: Locale) => getSnapshot<HomeSnapshotData>("home", locale),
  map: (locale: Locale) => getSnapshot<MapEventsData>("map_events", locale),
  calendar: (locale: Locale) => getSnapshot<CalendarSnapshotData>("calendar_upcoming", locale),
  country: (key: string, locale: Locale) =>
    getSnapshot<CountryRegionSnapshotData>(`country_${key}`, locale),
  region: (key: string, locale: Locale) =>
    getSnapshot<CountryRegionSnapshotData>(`region_${key}`, locale),
  sector: (key: string, locale: Locale) =>
    getSnapshot<SectorSnapshotData>(`sector_${key}`, locale),
  scenarioBasket: (key: string, locale: Locale) =>
    getSnapshot<ScenarioBasketSnapshotData>(`scenario_basket_${key}`, locale),
  status: (locale: Locale) => getSnapshot<SourceStatusSnapshotData>("source_status", locale),
  corrections: (locale: Locale) => getSnapshot<{ entries: unknown[] }>("correction_log", locale),
  newsIndex: (locale: Locale) => getSnapshot<NewsIndexSnapshotData>("news_index", locale),
  newsEvent: (eventId: string, locale: Locale) =>
    getSnapshot<NewsEventSnapshotData>(`news_event_${eventId}`, locale),
  newsTicker: (symbolKey: string, locale: Locale) =>
    getSnapshot<NewsTickerSnapshotData>(`news_ticker_${symbolKey}`, locale),
  referenceEntity: (routeKey: string, locale: Locale) =>
    getSnapshot<ReferenceEntitySnapshotData>(`entity_${routeKey}`, locale),
  newsRegion: (regionKey: string, locale: Locale) =>
    getSnapshot<NewsRegionSnapshotData>(`news_region_${regionKey}`, locale),
  newsTopic: (topicKey: string, locale: Locale) =>
    getSnapshot<NewsTopicSnapshotData>(`news_topic_${topicKey}`, locale),
  fundPortfolio: (fundKey: string, locale: Locale) =>
    getSnapshot<FundPortfolioSnapshotData>(`fund_portfolio_${fundKey}`, locale)
};

export function isStale(staleAfter: string): boolean {
  return Date.now() > new Date(staleAfter).getTime();
}
