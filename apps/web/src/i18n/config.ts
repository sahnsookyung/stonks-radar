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
