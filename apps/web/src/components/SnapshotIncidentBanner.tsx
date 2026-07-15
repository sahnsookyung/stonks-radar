import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { useEffect, useRef } from "react";
import { getSnapshotReadiness } from "../lib/snapshots";
import { useLocale } from "../lib/locale";

export function SnapshotIncidentBanner() {
  const locale = useLocale();
  const queryClient = useQueryClient();
  const previousStatus = useRef<string | undefined>(undefined);
  const readiness = useQuery({
    queryKey: ["snapshot-readiness"],
    queryFn: getSnapshotReadiness,
    staleTime: 0,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true
  });

  useEffect(() => {
    const current = readiness.data?.status;
    if (previousStatus.current && previousStatus.current !== "ready" && current === "ready") {
      void queryClient.invalidateQueries({ queryKey: ["snapshot"] });
    }
    previousStatus.current = current;
  }, [queryClient, readiness.data?.status]);

  const status = readiness.data?.status;
  if (!status || status === "ready") return null;

  const isUnavailable = status === "unavailable";
  const contentUnavailable = readiness.data?.reason === "content_unavailable";
  const checkedAt = readiness.dataUpdatedAt ? new Date(readiness.dataUpdatedAt).toLocaleTimeString() : "—";
  const copy =
    locale === "ko"
      ? isUnavailable
        ? "공개 시장 데이터 발행이 중단되어 오래된 수치를 숨기고 있습니다. 복구 여부를 매분 확인합니다."
        : contentUnavailable
          ? "하나 이상의 실시간 데이터 소스를 사용할 수 없습니다. 정적 예시 값은 숨겨져 있으며 영향을 받는 화면에 경고가 표시됩니다."
          : "공개 시장 데이터가 평소보다 늦게 갱신되고 있습니다. 표시된 생성 시각을 확인하세요."
      : isUnavailable
        ? "Public market-data publication is interrupted, so expired figures are hidden. Recovery is checked every minute."
        : contentUnavailable
          ? "One or more live data sources are unavailable. Static example values are hidden and affected views are marked."
          : "Public market data is updating later than usual. Check the displayed generation times.";

  return (
    <aside
      className={`border-b px-3 py-3 text-sm sm:px-4 lg:px-6 2xl:px-8 ${isUnavailable ? "border-danger/40 bg-danger/10 text-danger" : "border-warning/40 bg-warning/10 text-warning"}`}
      role={isUnavailable ? "alert" : "status"}
    >
      <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2 sm:flex sm:flex-wrap sm:items-center sm:gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 sm:mt-0" aria-hidden="true" />
        <p className="min-w-0 flex-1 font-medium">{copy}</p>
        <div className="col-start-2 flex flex-wrap items-center justify-between gap-3 sm:contents">
          <span className="text-xs opacity-80">
            {locale === "ko" ? "마지막 확인" : "Last checked"}: {checkedAt}
          </span>
          <button
            type="button"
            className="focus-ring inline-flex min-h-11 items-center gap-2 rounded-md border border-current px-3 font-semibold"
            onClick={() => void readiness.refetch()}
            disabled={readiness.isFetching}
          >
            <RefreshCw className={`h-4 w-4 ${readiness.isFetching ? "animate-spin" : ""}`} aria-hidden="true" />
            {locale === "ko" ? "다시 시도" : "Try again"}
          </button>
        </div>
      </div>
    </aside>
  );
}
