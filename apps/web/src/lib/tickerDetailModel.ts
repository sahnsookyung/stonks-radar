export interface MarketHistoryResponse {
  status: string;
  provider: string;
  source_note: string;
  cache: "hit" | "miss" | "persistent_hit" | "quota_wait" | "stale_fallback" | "license_limited";
  display_mode?: "public" | "private";
  display_status?: "display_allowed" | "stored_public_allowed" | "internal_stored" | "license_limited" | "provider_limit_reached" | "unavailable";
  data_freshness?: DataFreshness;
  provider_budget_status?: ProviderLimitSnapshot[];
  symbols: string[];
  start: string;
  end: string;
  series: MarketSeries[];
  warnings: string[];
}

export interface DataFreshness {
  provider: string;
  provider_timestamp: string | null;
  fetched_at: string;
  source_observed_at?: string | null;
  market_session_date: string | null;
  complete_through?: string | null;
  hard_expires_at?: string | null;
  staleness_state?: string | null;
  calculation_eligible?: boolean;
  delayed_by_seconds?: number | null;
  exchange_timezone: string;
  delay_label: string;
  is_same_day_valid: boolean;
  is_public_display_allowed: boolean;
  staleness_reason: string;
  license_mode: string;
  source_url?: string;
}

export interface ProviderLimitSnapshot {
  provider_key: string;
  endpoint_key: string;
  refresh_interval?: string;
  source_checked_at: string;
  attribution_required: boolean;
  public_display_allowed: boolean;
}

export interface MarketSeries {
  symbol: string;
  points: MarketPoint[];
}

export interface MarketPoint {
  date: string;
  close: number;
  volume?: number | null;
}

export interface FreshnessMeta {
  providerLabel: string;
  delayLabel: string;
  stalenessReason: string;
  ageLabel: string;
  sameDayValid: boolean;
  isPublicDisplayAllowed: boolean;
  licenseMode: string;
  providerTimestamp: string | null;
  fetchedAt: string | null;
}

export interface IndicatorSet {
  latestPoint?: MarketPoint;
  latestClose: number;
  previousClose: number;
  change: number;
  changePct: number;
  latestVolume: number;
  volumeSma20: number;
  volumeRatio: number;
  sma50: number;
  sma200: number;
  ema20: number;
  rsi14: number;
  previousRsi14: number;
  stochRsi: number;
  macd: {
    line: number;
    signal: number;
    histogram: number;
  };
  previousMacdHistogram: number;
  bollinger: {
    lower: number;
    middle: number;
    upper: number;
    position: number;
  };
  rangeHigh: number;
  rangeLow: number;
  rangePosition: number;
  score: {
    total: number;
    parts: {
      trend: number;
      momentum: number;
      volume: number;
      volatility: number;
      relative: number;
    };
  };
}

export function buildFreshnessMeta(payload: MarketHistoryResponse | undefined, updatedAt: number, latestPoint?: MarketPoint): FreshnessMeta {
  if (payload?.data_freshness) {
    const sourceTime =
      payload.data_freshness.source_observed_at ??
      payload.data_freshness.market_session_date ??
      payload.data_freshness.provider_timestamp ??
      payload.data_freshness.fetched_at;
    const staleness = payload.data_freshness.staleness_state;
    return {
      providerLabel: `provider: ${payload.data_freshness.provider}`,
      delayLabel: staleness === "stale_fallback" ? "stale reference" : payload.data_freshness.delay_label,
      stalenessReason: payload.data_freshness.staleness_reason,
      ageLabel: relativeAge(new Date(sourceTime).getTime()),
      sameDayValid: payload.data_freshness.is_same_day_valid,
      isPublicDisplayAllowed: payload.data_freshness.is_public_display_allowed,
      licenseMode: payload.data_freshness.license_mode,
      providerTimestamp: payload.data_freshness.complete_through ?? payload.data_freshness.provider_timestamp,
      fetchedAt: payload.data_freshness.fetched_at
    };
  }
  const provider = payload?.provider ?? "provider unavailable";
  const latestDate = latestPoint?.date ?? "date unavailable";
  const today = isoDate(new Date());
  const sameDayValid = latestDate === today;
  return {
    providerLabel: `provider: ${provider}`,
    delayLabel: sameDayValid ? "current-day daily snapshot, not realtime" : "daily / previous-session snapshot",
    stalenessReason: payload?.source_note || `latest candle ${latestDate}; no intraday redistribution claimed`,
    ageLabel: updatedAt ? relativeAge(updatedAt) : "unavailable",
    sameDayValid,
    isPublicDisplayAllowed: true,
    licenseMode: "legacy",
    providerTimestamp: latestDate,
    fetchedAt: null
  };
}

export function computeIndicatorSet(points: MarketPoint[]): IndicatorSet {
  const clean = normalizePoints(points);
  const closes = clean.map((point) => point.close);
  const volumes = clean.map((point) => Number(point.volume ?? Number.NaN)).filter(Number.isFinite);
  const latestPoint = clean.at(-1);
  const latestClose = latestPoint?.close ?? Number.NaN;
  const previousClose = clean.at(-2)?.close ?? Number.NaN;
  const change = finite(latestClose - previousClose);
  const changePct = finite((change / previousClose) * 100);
  const latestVolume = Number(latestPoint?.volume ?? Number.NaN);
  const volumeSma20 = average(volumes.slice(-20));
  const volumeRatio = finite(latestVolume / volumeSma20);
  const sma50 = average(closes.slice(-50));
  const sma200 = average(closes.slice(-200));
  const ema20 = lastFinite(emaSeries(closes, 20));
  const rsiValues = rsiSeries(closes, 14);
  const rsi14 = lastFinite(rsiValues);
  const previousRsi14 = previousFinite(rsiValues);
  const rsiWindow = rsiValues.filter(Number.isFinite).slice(-14);
  const rsiMin = Math.min(...rsiWindow);
  const rsiMax = Math.max(...rsiWindow);
  const stochRsi = finite((rsi14 - rsiMin) / (rsiMax - rsiMin || 1));
  const macd = computeMacd(closes);
  const previousMacdHistogram = computePreviousMacdHistogram(closes);
  const bandWindow = closes.slice(-20);
  const bollingerMiddle = average(bandWindow);
  const bandStd = stdDev(bandWindow);
  const bollingerLower = bollingerMiddle - bandStd * 2;
  const bollingerUpper = bollingerMiddle + bandStd * 2;
  const bollingerPosition = finite((latestClose - bollingerLower) / (bollingerUpper - bollingerLower || 1));
  const rangeWindow = closes.slice(-252);
  const rangeHigh = Math.max(...rangeWindow);
  const rangeLow = Math.min(...rangeWindow);
  const rangePosition = finite((latestClose - rangeLow) / (rangeHigh - rangeLow || 1));
  const score = technicalScore({
    latestClose,
    previousClose,
    sma50,
    sma200,
    ema20,
    rsi14,
    stochRsi,
    macdHistogram: macd.histogram,
    volumeRatio,
    bollingerPosition,
    changePct,
    rangePosition
  });

  return {
    latestPoint,
    latestClose,
    previousClose,
    change,
    changePct,
    latestVolume,
    volumeSma20,
    volumeRatio,
    sma50,
    sma200,
    ema20,
    rsi14,
    previousRsi14,
    stochRsi,
    macd,
    previousMacdHistogram,
    bollinger: {
      lower: bollingerLower,
      middle: bollingerMiddle,
      upper: bollingerUpper,
      position: bollingerPosition
    },
    rangeHigh,
    rangeLow,
    rangePosition,
    score
  };
}

export function normalizePoints(points: MarketPoint[]) {
  return points
    .filter((point) => Number.isFinite(point.close))
    .slice()
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function tickerDateRange() {
  const endDate = new Date();
  const startDate = new Date(endDate);
  startDate.setFullYear(startDate.getFullYear() - 1);
  return {
    start: isoDate(startDate),
    end: isoDate(endDate)
  };
}

function technicalScore(input: { // NOSONAR - scoring thresholds are intentionally colocated for formula review.
  latestClose: number;
  previousClose: number;
  sma50: number;
  sma200: number;
  ema20: number;
  rsi14: number;
  stochRsi: number;
  macdHistogram: number;
  volumeRatio: number;
  bollingerPosition: number;
  changePct: number;
  rangePosition: number;
}) {
  const parts = {
    trend: 0,
    momentum: 0,
    volume: 0,
    volatility: 0,
    relative: 0
  };
  if (input.latestClose > input.sma50) parts.trend += 12;
  if (input.latestClose > input.sma200) parts.trend += 12;
  if (input.ema20 > input.sma50) parts.trend += 6;
  if (input.latestClose > input.previousClose) parts.trend += 5;
  if (input.rsi14 >= 45 && input.rsi14 <= 65) parts.momentum += 8;
  if (input.rsi14 > 55 && input.rsi14 < 75) parts.momentum += 7;
  if (input.macdHistogram > 0) parts.momentum += 7;
  if (input.stochRsi > 0.2 && input.stochRsi < 0.85) parts.momentum += 3;
  if (input.volumeRatio >= 0.8 && input.volumeRatio <= 1.8) parts.volume += 8;
  if (input.volumeRatio > 1 && input.latestClose > input.previousClose) parts.volume += 8;
  if (input.volumeRatio < 2.5) parts.volume += 4;
  if (input.bollingerPosition > 0.15 && input.bollingerPosition < 0.9) parts.volatility += 6;
  if (Math.abs(input.changePct) < 8) parts.volatility += 4;
  if (input.rangePosition > 0.45) parts.relative += 6;
  if (input.rangePosition < 0.92) parts.relative += 4;
  return {
    total: Object.values(parts).reduce((sum, value) => sum + value, 0),
    parts
  };
}

function rsiSeries(values: number[], period: number) {
  const result = new Array<number>(values.length).fill(Number.NaN);
  if (values.length <= period) return result;
  let gain = 0;
  let loss = 0;
  for (let index = 1; index <= period; index += 1) {
    const delta = values[index] - values[index - 1];
    if (delta >= 0) gain += delta;
    else loss += Math.abs(delta);
  }
  let averageGain = gain / period;
  let averageLoss = loss / period;
  result[period] = 100 - 100 / (1 + averageGain / (averageLoss || 1e-9));
  for (let index = period + 1; index < values.length; index += 1) {
    const delta = values[index] - values[index - 1];
    const currentGain = Math.max(delta, 0);
    const currentLoss = Math.max(-delta, 0);
    averageGain = (averageGain * (period - 1) + currentGain) / period;
    averageLoss = (averageLoss * (period - 1) + currentLoss) / period;
    result[index] = 100 - 100 / (1 + averageGain / (averageLoss || 1e-9));
  }
  return result;
}

function emaSeries(values: number[], period: number) {
  const result = new Array<number>(values.length).fill(Number.NaN);
  if (values.length < period) return result;
  const multiplier = 2 / (period + 1);
  let ema = average(values.slice(0, period));
  result[period - 1] = ema;
  for (let index = period; index < values.length; index += 1) {
    ema = (values[index] - ema) * multiplier + ema;
    result[index] = ema;
  }
  return result;
}

function computeMacd(values: number[]) {
  const ema12 = emaSeries(values, 12);
  const ema26 = emaSeries(values, 26);
  const lineValues = values.map((_, index) => finite(ema12[index] - ema26[index]));
  const compactLine = lineValues.filter(Number.isFinite);
  const signal = lastFinite(emaSeries(compactLine, 9));
  const line = lastFinite(lineValues);
  return {
    line,
    signal,
    histogram: finite(line - signal)
  };
}

function computePreviousMacdHistogram(values: number[]) {
  if (values.length < 35) return Number.NaN;
  return computeMacd(values.slice(0, -1)).histogram;
}

function average(values: number[]) {
  const clean = values.filter(Number.isFinite);
  if (!clean.length) return Number.NaN;
  return clean.reduce((sum, value) => sum + value, 0) / clean.length;
}

function stdDev(values: number[]) {
  const avg = average(values);
  if (!Number.isFinite(avg)) return Number.NaN;
  return Math.sqrt(average(values.map((value) => (value - avg) ** 2)));
}

function lastFinite(values: number[]) {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (Number.isFinite(values[index])) return values[index];
  }
  return Number.NaN;
}

function previousFinite(values: number[]) {
  let seenLast = false;
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (!Number.isFinite(values[index])) continue;
    if (seenLast) return values[index];
    seenLast = true;
  }
  return Number.NaN;
}

function finite(value: number) {
  return Number.isFinite(value) ? value : Number.NaN;
}

function isoDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

function relativeAge(timestampMs: number) {
  const minutes = Math.max(0, Math.round((Date.now() - timestampMs) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}
