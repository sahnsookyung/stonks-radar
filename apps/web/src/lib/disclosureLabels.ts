export interface DisclosureLike {
  source?: string | null;
  form_type?: string | null;
  transaction_code?: string | null;
  transaction_type?: string | null;
}

type Locale = "en" | "ko";

const form4CodeLabels: Record<string, { en: string; ko: string; bucket: "market" | "admin" | "intent" | "other" }> = {
  P: { en: "Market purchase", ko: "시장 매수", bucket: "market" },
  S: { en: "Market sale", ko: "시장 매도", bucket: "market" },
  A: { en: "Award / grant", ko: "보상 / 부여", bucket: "admin" },
  D: { en: "Issuer disposition", ko: "발행자 관련 처분", bucket: "admin" },
  M: { en: "Option exercise / conversion", ko: "옵션 행사 / 전환", bucket: "admin" },
  F: { en: "Tax withholding", ko: "세금 원천징수", bucket: "admin" },
  G: { en: "Gift", ko: "증여", bucket: "admin" },
  J: { en: "Other reported change", ko: "기타 신고 변동", bucket: "other" },
  V: { en: "Voluntary early report", ko: "자발적 조기 신고", bucket: "other" },
};

const bucketLabels = {
  market: { en: "market trade", ko: "시장 거래" },
  admin: { en: "administrative", ko: "행정/보상" },
  intent: { en: "sale intent", ko: "매도 의향" },
  other: { en: "reported", ko: "신고" },
};

export function disclosureTransactionLabel(transaction: DisclosureLike, locale: Locale) {
  const code = (transaction.transaction_code ?? "").trim().toUpperCase();
  const formType = (transaction.form_type ?? "").trim().toUpperCase();
  if (transaction.source === "SEC" && formType === "144") {
    return locale === "ko" ? "Form 144 매도 의향" : "Form 144 sale intent";
  }
  const codeLabel = form4CodeLabels[code];
  if (codeLabel) {
    return codeLabel[locale];
  }
  return transaction.transaction_type || transaction.transaction_code || (locale === "ko" ? "신고됨" : "reported");
}

export function disclosureTransactionBucket(transaction: DisclosureLike, locale: Locale) {
  const code = (transaction.transaction_code ?? "").trim().toUpperCase();
  const formType = (transaction.form_type ?? "").trim().toUpperCase();
  if (transaction.source === "SEC" && formType === "144") {
    return bucketLabels.intent[locale];
  }
  const bucket = form4CodeLabels[code]?.bucket ?? "other";
  return bucketLabels[bucket][locale];
}

export function disclosureTransactionCaveat(transaction: DisclosureLike, locale: Locale) {
  const code = (transaction.transaction_code ?? "").trim().toUpperCase();
  const formType = (transaction.form_type ?? "").trim().toUpperCase();
  if (transaction.source === "SEC" && formType === "144") {
    return locale === "ko" ? "체결 증거가 아닌 제안 매도 통지입니다." : "Proposed sale notice, not proof of execution.";
  }
  if (code === "F") {
    return locale === "ko" ? "세금 원천징수이며 일반 시장 매도와 구분합니다." : "Tax withholding, not a normal open-market sale.";
  }
  if (code && !["P", "S"].includes(code)) {
    return locale === "ko" ? "단순 매수/매도 신호로 해석하지 않습니다." : "Do not read as a simple buy/sell signal.";
  }
  return "";
}
