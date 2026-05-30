import { generatedTrackedEntities, type GeneratedTrackedEntity, type TrackedEntityRouteKind } from "../generated/trackedEntities";

export interface TrackedEntity extends GeneratedTrackedEntity {
  routeKind: TrackedEntityRouteKind;
}

export interface TrackedTicker extends TrackedEntity {
  routeKind: "ticker";
  tradingViewSymbol: string;
}

export const trackedEntities: TrackedEntity[] = generatedTrackedEntities.map((entity) => ({ ...entity }));

export const trackedTickers: TrackedTicker[] = trackedEntities.filter(isTickerEntity);

export const trackedTickerSymbols = trackedTickers.map((ticker) => ticker.symbol);

export function normalizeTickerSymbol(value: string | undefined): string {
  return (value ?? "").trim().toUpperCase().replace(/[^A-Z0-9.\-_]/g, "");
}

export function routeKeyForSymbol(value: string | undefined): string {
  return normalizeTickerSymbol(value).replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "");
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
