import { useParams } from "@tanstack/react-router";
import { FileText } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocale } from "../lib/locale";

const allowedSlugs = new Set([
  "terms",
  "privacy",
  "financial-disclaimer",
  "source-policy",
  "corrections",
  "contact"
]);

export function LegalPage() {
  const locale = useLocale();
  const { t } = useTranslation();
  const params = useParams({ strict: false }) as { legalSlug?: string };
  const slug = allowedSlugs.has(params.legalSlug ?? "") ? params.legalSlug! : "terms";
  const isKo = locale === "ko";

  if (slug === "corrections") {
    return <Corrections />;
  }

  const title = String(t(`legal.${slug}`, slug));
  const content = legalContent[locale][slug] ?? legalContent[locale].terms;

  return (
    <article className="grid min-w-0 gap-6">
      <section className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-accent">
          <FileText className="h-4 w-4" />
          {isKo ? "공개 신뢰 문서" : "Public trust page"}
        </div>
        <h1 className="safe-text mt-2 text-3xl font-bold sm:text-4xl">{title}</h1>
      </section>
      <section className="panel max-w-4xl p-5">
        {content.map((paragraph) => (
          <p key={paragraph} className="safe-text mb-4 text-sm leading-7 text-muted last:mb-0">
            {paragraph}
          </p>
        ))}
      </section>
    </article>
  );
}

function Corrections() {
  const locale = useLocale();
  const isKo = locale === "ko";
  return (
    <article className="grid min-w-0 gap-6">
      <section className="min-w-0">
        <h1 className="safe-text text-3xl font-bold sm:text-4xl">{isKo ? "정정 및 철회 로그" : "Correction And Retraction Log"}</h1>
        <p className="safe-text mt-3 max-w-3xl text-sm leading-6 text-muted">
          {isKo
            ? "정정은 공개 스냅샷과 함께 배포되며 이전 주장을 조용히 덮어쓰지 않습니다."
            : "Corrections are distributed with public snapshots and do not silently overwrite prior claims."}
        </p>
      </section>
      <div className="panel p-5 text-sm text-muted">
        {isKo ? "현재 공개 정정 또는 철회 항목이 없습니다." : "There are no public corrections or retractions in the current public snapshot."}
      </div>
    </article>
  );
}

const legalContent: Record<string, Record<string, string[]>> = {
  en: {
    terms: [
      "This application provides research and educational information only. It is not a brokerage, exchange, adviser, or trade execution service.",
      "Public pages are generated from approved snapshots and may be delayed, stale, incomplete, or unavailable for unsupported coverage."
    ],
    privacy: [
      "Anonymous public visitors do not receive public user accounts, comments, uploads, or community features in this build.",
      "Admin activity is audited. Operational identifiers such as IP addresses should be hashed or retained only as needed for security."
    ],
    "financial-disclaimer": [
      "Nothing here is personalized financial, investment, legal, tax, or accounting advice. Scenario baskets and model watchlists are research objects.",
      "Market indicators are delayed or reference data unless a source policy explicitly permits realtime public redistribution."
    ],
    "source-policy": [
      "Official APIs, official pages, filings, company IR, and permissive geodata are preferred. Aggregators and noisy discovery sources cannot publish high-confidence events alone.",
      "Restricted raw prose and private clips are not exposed in public snapshots."
    ],
    contact: [
      "For corrections, source-policy concerns, or operational questions, contact the site operator using the address configured in deployment.",
      "A correction request should include the page URL, claim, source, and requested correction."
    ]
  },
  ko: {
    terms: [
      "이 애플리케이션은 리서치와 교육 목적의 정보만 제공합니다. 증권사, 거래소, 투자자문사 또는 주문 실행 서비스가 아닙니다.",
      "공개 페이지는 승인된 스냅샷에서 생성되며 지연, 오래됨, 불완전함 또는 미지원 범위가 있을 수 있습니다."
    ],
    privacy: [
      "이 빌드에서는 익명 공개 방문자에게 계정, 댓글, 업로드, 커뮤니티 기능을 제공하지 않습니다.",
      "관리자 활동은 감사 로그에 기록됩니다. IP 같은 운영 식별자는 보안상 필요한 범위에서 해시 또는 제한 보관되어야 합니다."
    ],
    "financial-disclaimer": [
      "여기의 어떤 내용도 개인화된 금융, 투자, 법률, 세무 또는 회계 조언이 아닙니다. 시나리오 바스켓과 모델 워치리스트는 리서치 객체입니다.",
      "출처 정책이 실시간 공개 재배포를 명시적으로 허용하지 않는 한 시장 지표는 지연 또는 참조 데이터입니다."
    ],
    "source-policy": [
      "공식 API, 공식 페이지, 공시, 기업 IR, 허용된 지리 데이터가 우선됩니다. 집계/노이즈 발견 출처만으로는 고신뢰 이벤트를 공개할 수 없습니다.",
      "제한 원문과 개인 클립은 공개 스냅샷에 노출되지 않습니다."
    ],
    contact: [
      "정정, 출처 정책, 운영 문의는 배포 시 설정된 운영자 연락처로 보내십시오.",
      "정정 요청에는 페이지 URL, 주장, 출처, 요청 내용을 포함해야 합니다."
    ]
  }
};
