export interface TrackedTicker {
  symbol: string;
  displaySymbol: string;
  tradingViewSymbol: string;
  exchange: string;
  assetType: "Equity" | "ETF" | "Reference";
  name: string;
  currency: string;
  country: string;
  sector: string;
  industry: string;
  tags: string[];
  secCik?: string;
  thesisBull: string;
  thesisBear: string;
  invalidation: string;
  related: string[];
}

export const trackedTickers: TrackedTicker[] = [
  {
    symbol: "DJT",
    displaySymbol: "DJT",
    tradingViewSymbol: "NASDAQ:DJT",
    exchange: "NASDAQ",
    assetType: "Equity",
    name: "Trump Media & Technology Group",
    currency: "USD",
    country: "USA",
    sector: "Media / political event risk",
    industry: "Social media",
    tags: ["trump-filings", "short-interest", "event-risk"],
    secCik: "1849635",
    thesisBull: "Event-driven attention, reflexive retail flow, and public filing catalysts can dominate fundamentals.",
    thesisBear: "High volatility, dilution/insider-sale risk, and weak operating fundamentals can overwhelm narrative demand.",
    invalidation: "Treat source-linked filings and liquidity breaks as primary risk triggers.",
    related: ["TSLA", "NVDA"]
  },
  {
    symbol: "TSLA",
    displaySymbol: "TSLA",
    tradingViewSymbol: "NASDAQ:TSLA",
    exchange: "NASDAQ",
    assetType: "Equity",
    name: "Tesla",
    currency: "USD",
    country: "USA",
    sector: "Big Tech / EV",
    industry: "Automobiles",
    tags: ["short-volume", "big-tech", "retail-flow"],
    thesisBull: "Autonomy, energy storage, and optionality can re-rate the business when delivery/price pressure eases.",
    thesisBear: "Margin compression, policy risk, and competition can keep valuation fragile.",
    invalidation: "Watch delivery trend breaks, margin revisions, and abnormal short-volume spikes.",
    related: ["NVDA", "AAPL", "DJT"]
  },
  {
    symbol: "NVDA",
    displaySymbol: "NVDA",
    tradingViewSymbol: "NASDAQ:NVDA",
    exchange: "NASDAQ",
    assetType: "Equity",
    name: "NVIDIA",
    currency: "USD",
    country: "USA",
    sector: "Semiconductors / AI infrastructure",
    industry: "Semiconductors",
    tags: ["semiconductors", "ai-infra", "short-interest"],
    thesisBull: "AI accelerator demand, software ecosystem leverage, and supply-chain control support premium growth.",
    thesisBear: "Export controls, hyperscaler capex digestion, and extreme expectations create downside convexity.",
    invalidation: "Track export-control events, datacenter order commentary, and volume-confirmed trend breaks.",
    related: ["AMD", "AVGO", "TSLA"]
  },
  {
    symbol: "RKLB",
    displaySymbol: "RKLB",
    tradingViewSymbol: "NASDAQ:RKLB",
    exchange: "NASDAQ",
    assetType: "Equity",
    name: "Rocket Lab",
    currency: "USD",
    country: "USA",
    sector: "Space",
    industry: "Aerospace and defense",
    tags: ["space", "launch-cadence", "tracked-news"],
    thesisBull: "Launch cadence, defense demand, and Neutron milestones can improve strategic scarcity value.",
    thesisBear: "Execution delays, capital intensity, and dilution risk can pressure small-cap space equities.",
    invalidation: "Watch launch delays, offering filings, and cash-runway language.",
    related: ["LUNR", "ASTS", "RDW"]
  },
  {
    symbol: "IONQ",
    displaySymbol: "IONQ",
    tradingViewSymbol: "NYSE:IONQ",
    exchange: "NYSE",
    assetType: "Equity",
    name: "IonQ",
    currency: "USD",
    country: "USA",
    sector: "Quantum",
    industry: "Quantum computing",
    tags: ["quantum", "government-funding", "high-volatility"],
    thesisBull: "Government funding and commercial quantum milestones can keep speculative scarcity bid alive.",
    thesisBear: "Revenue scale, valuation, and hype-cycle reversals can make drawdowns violent.",
    invalidation: "Watch 200D trend breaks, funding announcements, and dilution filings.",
    related: ["RGTI", "QBTS", "QUBT"]
  },
  {
    symbol: "RGTI",
    displaySymbol: "RGTI",
    tradingViewSymbol: "NASDAQ:RGTI",
    exchange: "NASDAQ",
    assetType: "Equity",
    name: "Rigetti Computing",
    currency: "USD",
    country: "USA",
    sector: "Quantum",
    industry: "Quantum computing",
    tags: ["quantum", "small-cap", "high-volatility"],
    thesisBull: "Quantum-sector momentum can produce sharp re-ratings around technical milestones.",
    thesisBear: "Funding needs and commercialization timing remain central risks.",
    invalidation: "Treat financing filings and failed milestone updates as key review points.",
    related: ["IONQ", "QBTS", "QUBT"]
  },
  {
    symbol: "QBTS",
    displaySymbol: "QBTS",
    tradingViewSymbol: "NYSE:QBTS",
    exchange: "NYSE",
    assetType: "Equity",
    name: "D-Wave Quantum",
    currency: "USD",
    country: "USA",
    sector: "Quantum",
    industry: "Quantum computing",
    tags: ["quantum", "small-cap", "high-volatility"],
    thesisBull: "Annealing use-cases and sector-wide quantum interest can support event-driven upside.",
    thesisBear: "Commercial traction and dilution remain the main constraints.",
    invalidation: "Watch liquidity, offering filings, and customer proof points.",
    related: ["IONQ", "RGTI", "QUBT"]
  },
  {
    symbol: "LUNR",
    displaySymbol: "LUNR",
    tradingViewSymbol: "NASDAQ:LUNR",
    exchange: "NASDAQ",
    assetType: "Equity",
    name: "Intuitive Machines",
    currency: "USD",
    country: "USA",
    sector: "Space",
    industry: "Aerospace and defense",
    tags: ["space", "lunar", "event-risk"],
    thesisBull: "NASA lunar-services awards and mission milestones can create high-impact catalysts.",
    thesisBear: "Mission execution risk and financing needs can dominate between catalysts.",
    invalidation: "Watch mission windows, contract modifications, and cash-runway updates.",
    related: ["RKLB", "ASTS", "RDW"]
  },
  {
    symbol: "ASTS",
    displaySymbol: "ASTS",
    tradingViewSymbol: "NASDAQ:ASTS",
    exchange: "NASDAQ",
    assetType: "Equity",
    name: "AST SpaceMobile",
    currency: "USD",
    country: "USA",
    sector: "Space",
    industry: "Satellite communications",
    tags: ["space", "satcom", "high-volatility"],
    thesisBull: "Satellite-to-phone milestones and carrier partnerships can expand the addressable narrative.",
    thesisBear: "Capex, launch timing, and commercial deployment risk are material.",
    invalidation: "Watch launch cadence, capital raises, and partner-conversion evidence.",
    related: ["RKLB", "LUNR", "RDW"]
  },
  {
    symbol: "RDW",
    displaySymbol: "RDW",
    tradingViewSymbol: "NYSE:RDW",
    exchange: "NYSE",
    assetType: "Equity",
    name: "Redwire",
    currency: "USD",
    country: "USA",
    sector: "Space",
    industry: "Space infrastructure",
    tags: ["space", "defense-demand", "small-cap"],
    thesisBull: "Space infrastructure and defense demand can support niche backlog growth.",
    thesisBear: "Small-cap liquidity, integration risk, and profitability timing matter.",
    invalidation: "Watch backlog quality, margin trend, and financing language.",
    related: ["RKLB", "LUNR", "ASTS"]
  },
  {
    symbol: "AMD",
    displaySymbol: "AMD",
    tradingViewSymbol: "NASDAQ:AMD",
    exchange: "NASDAQ",
    assetType: "Equity",
    name: "Advanced Micro Devices",
    currency: "USD",
    country: "USA",
    sector: "Semiconductors / AI infrastructure",
    industry: "Semiconductors",
    tags: ["semiconductors", "ai-infra", "datacenter"],
    thesisBull: "AI GPU share gains and datacenter CPU demand can narrow the gap versus leader expectations.",
    thesisBear: "Execution, margins, and ecosystem gaps versus NVIDIA can limit upside.",
    invalidation: "Watch datacenter guide-downs and failed accelerator ramp evidence.",
    related: ["NVDA", "INTC", "AVGO"]
  },
  {
    symbol: "AAPL",
    displaySymbol: "AAPL",
    tradingViewSymbol: "NASDAQ:AAPL",
    exchange: "NASDAQ",
    assetType: "Equity",
    name: "Apple",
    currency: "USD",
    country: "USA",
    sector: "Big Tech",
    industry: "Consumer electronics",
    tags: ["big-tech", "portfolio-lab", "mega-cap"],
    thesisBull: "Installed-base monetization, buybacks, and services durability can stabilize earnings.",
    thesisBear: "China demand, AI execution, and hardware-cycle saturation can weigh on multiples.",
    invalidation: "Watch revenue revisions, China exposure, and product-cycle response.",
    related: ["MSFT", "GOOGL", "AMZN"]
  },
  {
    symbol: "MSFT",
    displaySymbol: "MSFT",
    tradingViewSymbol: "NASDAQ:MSFT",
    exchange: "NASDAQ",
    assetType: "Equity",
    name: "Microsoft",
    currency: "USD",
    country: "USA",
    sector: "Big Tech / AI infrastructure",
    industry: "Software and cloud",
    tags: ["big-tech", "portfolio-lab", "ai-infra"],
    thesisBull: "Cloud, enterprise AI distribution, and software margins support high-quality compounding.",
    thesisBear: "AI capex intensity, antitrust risk, and cloud growth deceleration can pressure returns.",
    invalidation: "Watch Azure growth, capex commentary, and margin dilution.",
    related: ["AAPL", "GOOGL", "AMZN"]
  },
  {
    symbol: "TLT",
    displaySymbol: "TLT",
    tradingViewSymbol: "NASDAQ:TLT",
    exchange: "NASDAQ",
    assetType: "ETF",
    name: "iShares 20+ Year Treasury Bond ETF",
    currency: "USD",
    country: "USA",
    sector: "Rates",
    industry: "Long-duration Treasuries",
    tags: ["portfolio-lab", "rates", "macro-hedge"],
    thesisBull: "Duration can rally when growth expectations weaken or real yields fall.",
    thesisBear: "Sticky inflation, term-premium repricing, and heavy issuance can keep pressure on long bonds.",
    invalidation: "Watch 10Y/30Y yield breaks and FOMC repricing.",
    related: ["AAPL", "MSFT", "NVDA"]
  }
];

export function normalizeTickerSymbol(value: string | undefined): string {
  return (value ?? "").trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, "");
}

export function getTrackedTicker(symbol: string | undefined): TrackedTicker | undefined {
  const normalized = normalizeTickerSymbol(symbol);
  return trackedTickers.find((ticker) => ticker.symbol === normalized);
}

export const trackedTickerSymbols = trackedTickers.map((ticker) => ticker.symbol);
