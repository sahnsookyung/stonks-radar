import { BookOpenCheck } from "lucide-react";
import { useLocale } from "../lib/locale";

export function MethodologyPage() {
  const locale = useLocale();
  const isKo = locale === "ko";

  return (
    <article className="grid gap-6">
      <section>
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <BookOpenCheck className="h-4 w-4" />
          {isKo ? "방법론" : "Methodology"}
        </div>
        <h1 className="mt-2 text-4xl font-bold">
          {isKo ? "출처, 검토, 공개 스냅샷 방법론" : "Source, Review, And Snapshot Methodology"}
        </h1>
        <p className="mt-3 max-w-4xl text-base leading-7 text-muted">
          {isKo
            ? "공개 정보는 승인된 구조화 사실과 검토된 이벤트에서만 생성됩니다. 후보 데이터는 정본 데이터가 아니며, 출처 정책과 번역 상태가 공개 게이트를 통과해야 합니다."
            : "Public information is generated only from approved structured facts and reviewed events. Candidate data is not canonical data, and source policy plus translation freshness must pass publication gates."}
        </p>
      </section>
      <section className="grid gap-4 md:grid-cols-3">
        <MethodCard
          title={isKo ? "후보와 정본 분리" : "Candidates Stay Separate"}
          body={
            isKo
              ? "수집 값, 출처 문서, 증거, 사실, 추론은 별도 테이블에 저장됩니다."
              : "Ingested values, source documents, evidence, facts, and inference are stored separately."
          }
        />
        <MethodCard
          title={isKo ? "정책 기반 공개" : "Policy-Gated Publication"}
          body={
            isKo
              ? "스냅샷에는 사용된 활성 출처 정책 버전이 기록되며 제한 원문은 공개되지 않습니다."
              : "Snapshots record active source-policy versions and never expose restricted raw prose."
          }
        />
        <MethodCard
          title={isKo ? "지연/참조 시장 데이터" : "Delayed Reference Market Data"}
          body={
            isKo
              ? "실시간 재배포 권한이 명시되지 않은 시장 데이터는 지연 또는 참조로 표시됩니다."
              : "Market data is labeled delayed/reference unless the source explicitly permits realtime redistribution."
          }
        />
      </section>
    </article>
  );
}

function MethodCard({ title, body }: { title: string; body: string }) {
  return (
    <div className="panel p-4">
      <h2 className="font-semibold">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-muted">{body}</p>
    </div>
  );
}
