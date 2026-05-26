import i18n from "i18next";
import { initReactI18next } from "react-i18next";

const resources = {
  en: {
    translation: {
      appName: "Stonks Radar | 스톡스 레이더",
      dashboard: "Dashboard",
      map: "Map",
      calendar: "Calendar",
      centralBanks: "Central Banks",
      portfolio: "Portfolio",
      tickers: "Tickers",
      shorts: "Shorts",
      trumpFilings: "Trump Filings",
      sources: "Sources",
      methodology: "Methodology",
      status: "Status",
      corrections: "Corrections",
      sectors: "Sectors",
      countries: "Countries",
      scenarioBaskets: "Scenario Baskets",
      freshness: "Freshness",
      sourceStrength: "Source strength",
      delay: "Delay",
      evidence: "Evidence",
      noAdvice: "Research only. Not personalized financial advice.",
      stale: "Snapshot may be stale",
      generated: "Generated",
      source: "Source",
      expectationType: "Expectation type",
      surprise: "Surprise",
      admin: "Admin",
      login: "Login",
      publicSnapshot: "Public snapshot",
      snapshotFirst: "snapshot-first",
      approvedPublicData: "static approved public data",
      eventGeography: "Event geography",
      eventMapFooter: "Approved event geography. Boundaries are vendored locally; markers use reviewed public snapshot events.",
      marketPulse: "Market pulse",
      marketPulseSummary: "Delayed/reference values. Cards link to source pages; update times show the snapshot age.",
      scrollLeft: "Scroll left",
      scrollRight: "Scroll right",
      breakingNewsRadar: "Breaking market watch",
      breakingNewsRadarSummary: "Geopolitical and tracked-ticker headlines are pulled into the dashboard so users can scan the result before opening source evidence.",
      sourceLinksOnCards: "source links on cards",
      priorityEvent: "Priority event",
      evidenceItems: "{{count}} evidence items",
      shortsEventRadar: "Shorts & event radar",
      shortsEventRadarSummary: "FINRA short interest, daily short-volume flow, breaking-news metadata, public short research, weak OSINT, and SEC filing digests are rendered here so source links are supporting evidence, not the primary workflow.",
      approvedEvents: "Approved Events",
      freshnessStates: {
        fresh: "fresh",
        watch: "watch",
        stale: "stale",
        unsupported: "unsupported"
      },
      severityStates: {
        low: "low",
        medium: "medium",
        high: "high",
        critical: "critical"
      },
      legal: {
        terms: "Terms",
        privacy: "Privacy",
        "financial-disclaimer": "Financial Disclaimer",
        "source-policy": "Source Policy",
        contact: "Contact"
      }
    }
  },
  ko: {
    translation: {
      appName: "Stonks Radar | 스톡스 레이더",
      dashboard: "대시보드",
      map: "지도",
      calendar: "캘린더",
      centralBanks: "중앙은행",
      portfolio: "포트폴리오",
      tickers: "티커",
      shorts: "공매도",
      trumpFilings: "트럼프 공시",
      sources: "출처",
      methodology: "방법론",
      status: "상태",
      corrections: "정정 내역",
      sectors: "섹터",
      countries: "국가",
      scenarioBaskets: "시나리오 바스켓",
      freshness: "신선도",
      sourceStrength: "출처 강도",
      delay: "지연",
      evidence: "근거",
      noAdvice: "리서치 및 교육 목적이며 개인화된 금융 조언이 아닙니다.",
      stale: "스냅샷이 오래되었을 수 있습니다",
      generated: "생성 시각",
      source: "출처",
      expectationType: "예상치 유형",
      surprise: "서프라이즈",
      admin: "관리자",
      login: "로그인",
      publicSnapshot: "공개 스냅샷",
      snapshotFirst: "스냅샷 우선",
      approvedPublicData: "승인된 공개 데이터",
      eventGeography: "이벤트 지리",
      eventMapFooter: "승인된 이벤트 지리입니다. 경계 데이터는 로컬에 포함되어 있으며 마커는 검토된 공개 스냅샷 이벤트를 사용합니다.",
      marketPulse: "시장 펄스",
      marketPulseSummary: "지연/참조 값입니다. 카드는 출처 페이지로 연결되며 갱신 시각은 스냅샷 기준 경과 시간을 표시합니다.",
      scrollLeft: "왼쪽으로 스크롤",
      scrollRight: "오른쪽으로 스크롤",
      breakingNewsRadar: "시장 속보 워치",
      breakingNewsRadarSummary: "지정학 및 추적 티커 헤드라인을 대시보드에 직접 표시해 원문을 열기 전에 핵심 결과를 훑어볼 수 있게 합니다.",
      sourceLinksOnCards: "출처 링크는 카드에 표시",
      priorityEvent: "우선 이벤트",
      evidenceItems: "근거 {{count}}개",
      shortsEventRadar: "공매도 및 이벤트 레이더",
      shortsEventRadarSummary: "FINRA 공매도 잔고, 일별 공매도 거래량, 속보 메타데이터, 공개 숏 리서치, 약한 OSINT, SEC 공시 요약을 직접 표시해 출처 링크가 보조 근거로만 쓰이도록 합니다.",
      approvedEvents: "승인된 이벤트",
      freshnessStates: {
        fresh: "갱신됨",
        watch: "감시",
        stale: "오래됨",
        unsupported: "미지원"
      },
      severityStates: {
        low: "낮음",
        medium: "중간",
        high: "높음",
        critical: "위험"
      },
      legal: {
        terms: "이용약관",
        privacy: "개인정보 처리방침",
        "financial-disclaimer": "금융 고지",
        "source-policy": "출처 정책",
        contact: "문의"
      }
    }
  }
};

void i18n.use(initReactI18next).init({
  resources,
  fallbackLng: "en",
  interpolation: {
    escapeValue: false
  }
});

export default i18n;
