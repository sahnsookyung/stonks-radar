import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { Building2, ExternalLink, Newspaper } from "lucide-react";
import { EntityLink } from "../components/EntityLink";
import { NewsEventCard, SourcePill } from "../components/NewsEventCard";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";
import { entityDisplayName, relatedTrackedEntities, resolveTrackedEntity } from "../lib/trackedTickers";

export function EntityPage() {
  const locale = useLocale();
  const isKo = locale === "ko";
  const params = useParams({ strict: false }) as { routeKey?: string };
  const entity = resolveTrackedEntity(params.routeKey);
  const routeKey = entity?.routeKey ?? params.routeKey ?? "";
  const query = useQuery({
    queryKey: ["snapshot", "reference-entity", routeKey, locale],
    queryFn: () => snapshotQueries.referenceEntity(routeKey, locale),
    enabled: Boolean(routeKey)
  });

  if (!entity) {
    return (
      <div className="grid gap-5">
        <section className="panel p-5">
          <div className="text-sm font-semibold text-warning">{isKo ? "추적하지 않는 객체" : "Entity not tracked"}</div>
          <h1 className="mt-3 text-3xl font-bold">{params.routeKey ?? "unknown"}</h1>
          <p className="mt-2 text-sm leading-6 text-muted">
            {isKo ? "승인된 추적 레지스트리에 없는 객체입니다." : "This entity is not present in the approved tracked-entity registry."}
          </p>
        </section>
      </div>
    );
  }

  if (query.isLoading) return <LoadingState />;
  if (query.isError || !query.data) return <FallbackEntity entity={entity} locale={locale} error={query.error} />;

  const data = query.data.data;
  return (
    <div className="grid min-w-0 gap-6">
      <SnapshotBanner snapshot={query.data} />
      <section className="panel p-5">
        <div className="flex items-center gap-2 text-sm font-semibold uppercase text-accent">
          <Building2 className="h-4 w-4" />
          {isKo ? "참조 객체" : "Reference entity"}
        </div>
        <h1 className="mt-3 text-3xl font-bold">{data.entity.name}</h1>
        <p className="mt-3 max-w-4xl text-sm leading-6 text-muted">{data.summary}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <span className="badge border-warning/40 bg-warning/10 text-warning">
            {isKo ? "시세 페이지 아님" : "not a quote page"}
          </span>
          <span className="badge border-line bg-panelAlt text-muted">{data.freshness}</span>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="grid gap-4">
          <section className="panel p-5">
            <h2 className="flex items-center gap-2 text-lg font-bold">
              <Newspaper className="h-5 w-5 text-accent" />
              {isKo ? "관련 뉴스" : "Latest news"}
            </h2>
            <div className="mt-4 grid gap-3">
              {data.latest_news.length ? (
                data.latest_news.map((event) => <NewsEventCard key={event.id} event={event} locale={locale} compact />)
              ) : (
                <EmptyState text={isKo ? "최근 승인 뉴스가 없습니다." : "No recent approved news."} />
              )}
            </div>
          </section>
          <section className="panel p-5">
            <h2 className="text-lg font-bold">{isKo ? "소스" : "Sources"}</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {data.source_links.map((source) => (
                <SourcePill key={`${source.source_key}-${source.url}`} source={{ ...source, title: source.label, published_at: query.data.generated_at, trust_tier: "T0_OFFICIAL", is_primary: true }} />
              ))}
            </div>
          </section>
        </div>
        <aside className="grid content-start gap-4">
          <section className="panel p-4">
            <h2 className="text-sm font-semibold">{isKo ? "관련 객체" : "Related entities"}</h2>
            <div className="mt-3 grid gap-2">
              {data.related_entities.map((item) => (
                <EntityLink key={item.entity_id} value={item.symbol} locale={locale} className="focus-ring grid min-h-14 rounded-md border border-line bg-panelAlt px-3 py-2 hover:border-accent">
                  <span className="font-semibold">{item.display_symbol}</span>
                  <span className="text-xs text-muted">{item.name}</span>
                </EntityLink>
              ))}
            </div>
          </section>
          <section className="signal-warning p-4 text-sm leading-6">
            {data.caveats.join(" ")}
          </section>
        </aside>
      </section>
    </div>
  );
}

function FallbackEntity({ entity, locale, error }: { entity: NonNullable<ReturnType<typeof resolveTrackedEntity>>; locale: "en" | "ko"; error: unknown }) {
  const isKo = locale === "ko";
  const related = relatedTrackedEntities(entity, 6).filter((item) => item.entityId !== entity.entityId);
  return (
    <div className="grid gap-5">
      <section className="panel p-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <Building2 className="h-4 w-4" />
          {isKo ? "참조 객체" : "Reference entity"}
        </div>
        <h1 className="mt-3 text-3xl font-bold">{entityDisplayName(entity, locale)}</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted">
          {isKo
            ? "스냅샷을 아직 생성하지 못했습니다. 이 객체는 시세 페이지가 아니라 소스/뉴스 참조 페이지입니다."
            : "The reference snapshot is not generated yet. This is a source/news entity, not a quote page."}
        </p>
        <p className="mt-2 text-xs leading-5 text-muted">{String(error ?? "")}</p>
      </section>
      <section className="panel p-4">
        <h2 className="text-sm font-semibold">{isKo ? "관련 추적 항목" : "Related tracked items"}</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {related.map((item) => <EntityLink key={item.entityId} value={item} locale={locale} />)}
        </div>
      </section>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-md border border-dashed border-line p-4 text-sm leading-6 text-muted">{text}</div>;
}
