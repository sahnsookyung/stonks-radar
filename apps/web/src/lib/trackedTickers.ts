import { generatedTrackedEntities, type GeneratedTrackedEntity, type TrackedEntityRouteKind } from "../generated/trackedEntities";

export interface TrackedEntity extends GeneratedTrackedEntity {
  routeKind: TrackedEntityRouteKind;
}

export interface TrackedTicker extends TrackedEntity {
  routeKind: "ticker";
  tradingViewSymbol: string;
}

export interface TickerFilterOption {
  key: string;
  label: string;
  count: number;
}

export const trackedEntities: TrackedEntity[] = generatedTrackedEntities.map((entity) => ({ ...entity }));

export const trackedTickers: TrackedTicker[] = trackedEntities.filter(isTickerEntity);

export const trackedTickerSymbols = trackedTickers.map((ticker) => ticker.symbol);

export function normalizeTickerSymbol(value: string | undefined): string {
  return (value ?? "").trim().toUpperCase().replace(/[^A-Z0-9.\-_]/g, "");
}

export function routeKeyForSymbol(value: string | undefined): string {
  return asciiRouteKey(normalizeTickerSymbol(value));
}

function asciiRouteKey(value: string): string {
  let routeKey = "";
  for (const char of value) {
    if (isUpperAsciiAlphaNumeric(char)) {
      routeKey += char;
    } else if (routeKey.length > 0 && !routeKey.endsWith("_")) {
      routeKey += "_";
    }
  }
  return routeKey.endsWith("_") ? routeKey.slice(0, -1) : routeKey;
}

function isUpperAsciiAlphaNumeric(char: string): boolean {
  const code = char.codePointAt(0) ?? 0;
  return (code >= 48 && code <= 57) || (code >= 65 && code <= 90);
}

export function resolveTrackedEntity(value: string | undefined): TrackedEntity | undefined {
  const normalized = normalizeTickerSymbol(value);
  const routeKey = routeKeyForSymbol(value);
  return trackedEntities.find((entity) =>
    entity.symbol.toUpperCase() === normalized ||
    entity.routeKey.toUpperCase() === routeKey ||
    entity.entityId.toUpperCase() === normalized
  );
}

export function getTrackedTicker(symbol: string | undefined): TrackedTicker | undefined {
  const entity = resolveTrackedEntity(symbol);
  return entity && isTickerEntity(entity) ? entity : undefined;
}

export function trackedTickerFilterOptions(options: TickerFilterOption[] = []): TickerFilterOption[] {
  const snapshotOptions = new Map(options.map((option) => [normalizeTickerSymbol(option.key), option]));
  const merged = trackedTickers.map((ticker) => {
    const existing = snapshotOptions.get(normalizeTickerSymbol(ticker.symbol));
    return {
      key: ticker.symbol,
      label: existing?.label || ticker.name,
      count: existing?.count ?? 0
    };
  });
  return merged.sort((left, right) => {
    const countDelta = right.count - left.count;
    return countDelta || left.key.localeCompare(right.key);
  });
}

export function tickerMatchesFilterValue(symbol: string | undefined, value: string | undefined): boolean {
  const ticker = getTrackedTicker(value);
  const normalizedSymbol = normalizeTickerSymbol(symbol);
  const normalizedValue = normalizeTickerSymbol(value);
  if (!normalizedValue) return true;
  if (!ticker) return normalizedSymbol === normalizedValue;
  return normalizedSymbol === normalizeTickerSymbol(ticker.symbol) || normalizedSymbol === normalizeTickerSymbol(ticker.routeKey);
}

export function searchTrackedTickers(query: string, limit = trackedTickers.length): TrackedTicker[] {
  const normalizedQuery = query.trim().toLowerCase();
  const matches = normalizedQuery
    ? trackedTickers.filter((ticker) => tickerSearchText(ticker).includes(normalizedQuery))
    : trackedTickers;
  return matches.slice(0, Math.max(0, limit));
}

export function relatedTrackedEntities(entity: TrackedEntity, limit = 10): TrackedEntity[] {
  const symbols = new Set<string>(entity.related);
  for (const item of trackedEntities) {
    if (item.entityId !== entity.entityId && item.tags.some((tag) => entity.tags.includes(tag))) {
      symbols.add(item.symbol);
    }
  }
  const resolved = [...symbols]
    .map((symbol) => resolveTrackedEntity(symbol))
    .filter((item): item is TrackedEntity => Boolean(item));
  const seen = new Set<string>();
  return resolved.filter((item) => {
    if (item.entityId === entity.entityId) return false;
    if (seen.has(item.entityId)) return false;
    seen.add(item.entityId);
    return true;
  }).slice(0, limit);
}

export function entityDisplayName(entity: TrackedEntity, locale: "en" | "ko") {
  return locale === "ko" ? entity.nameKo : entity.name;
}

function isTickerEntity(entity: TrackedEntity): entity is TrackedTicker {
  return entity.routeKind === "ticker" && Boolean(entity.tradingViewSymbol);
}

function tickerSearchText(ticker: TrackedTicker): string {
  return [
    ticker.symbol,
    ticker.displaySymbol,
    ticker.routeKey,
    ticker.name,
    ticker.nameKo,
    ticker.exchange,
    ticker.sector,
    ticker.industry,
    ...ticker.aliases,
    ...ticker.tags
  ].join(" ").toLowerCase();
}
