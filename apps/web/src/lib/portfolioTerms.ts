export interface PortfolioTerm {
  label: string;
  short: string;
  long?: string;
  category: "performance" | "risk" | "allocation" | "asset_class" | "fees" | "simulation" | "data";
}

export const portfolioTerms: Record<string, PortfolioTerm> = {
  portfolio_value: {
    label: "Portfolio value",
    short: "Total current value of all holdings and cash.",
    category: "performance"
  },
  net_invested_capital: {
    label: "Net invested capital",
    short: "Money contributed minus withdrawals.",
    category: "performance"
  },
  total_return: {
    label: "Total return",
    short: "Return including price changes and income.",
    category: "performance"
  },
  cagr: {
    label: "CAGR",
    short: "Smoothed annual growth rate over a period.",
    long: "CAGR compresses a full period into one annual growth rate. It hides bad years and volatility.",
    category: "performance"
  },
  time_weighted_return: {
    label: "Time-weighted return",
    short: "Portfolio return that removes the effect of deposits and withdrawals.",
    category: "performance"
  },
  money_weighted_return: {
    label: "Money-weighted return",
    short: "Return that reflects when and how much money was added or removed.",
    category: "performance"
  },
  xirr: {
    label: "XIRR",
    short: "Money-weighted return for irregular cash-flow dates.",
    category: "performance"
  },
  benchmark: {
    label: "Benchmark",
    short: "A reference portfolio or index used for comparison.",
    category: "performance"
  },
  alpha: {
    label: "Alpha",
    short: "Return not explained by benchmark exposure.",
    category: "performance"
  },
  beta: {
    label: "Beta",
    short: "Sensitivity to benchmark movement.",
    category: "performance"
  },
  tracking_error: {
    label: "Tracking error",
    short: "How much a portfolio's return differs from a benchmark.",
    category: "performance"
  },
  volatility: {
    label: "Volatility",
    short: "How much returns usually move up and down.",
    category: "risk"
  },
  annualized_volatility: {
    label: "Annualized volatility",
    short: "Volatility converted into a yearly number.",
    category: "risk"
  },
  max_drawdown: {
    label: "Maximum drawdown",
    short: "Worst fall from a previous high to a later low.",
    long: "This helps estimate how painful losses could feel during a bad period.",
    category: "risk"
  },
  downside_deviation: {
    label: "Downside deviation",
    short: "Volatility of negative returns only.",
    category: "risk"
  },
  sharpe_ratio: {
    label: "Sharpe ratio",
    short: "Return earned per unit of total volatility.",
    category: "risk"
  },
  sortino_ratio: {
    label: "Sortino ratio",
    short: "Return earned per unit of downside volatility.",
    category: "risk"
  },
  correlation: {
    label: "Correlation",
    short: "How closely assets move together.",
    category: "risk"
  },
  risk_contribution: {
    label: "Risk contribution",
    short: "How much a holding adds to total portfolio risk.",
    category: "risk"
  },
  sequence_risk: {
    label: "Sequence risk",
    short: "Risk that bad returns happen at the wrong time, especially near withdrawals.",
    category: "risk"
  },
  asset_allocation: {
    label: "Asset allocation",
    short: "How money is split across asset classes.",
    category: "allocation"
  },
  target_allocation: {
    label: "Target allocation",
    short: "The intended portfolio mix.",
    category: "allocation"
  },
  allocation_drift: {
    label: "Allocation drift",
    short: "How far the current portfolio has moved from target.",
    category: "allocation"
  },
  rebalancing: {
    label: "Rebalancing",
    short: "Adjusting a portfolio back toward its target mix.",
    category: "allocation"
  },
  rebalancing_band: {
    label: "Rebalancing band",
    short: "Allowed drift before rebalancing is considered.",
    category: "allocation"
  },
  geographic_exposure: {
    label: "Geographic exposure",
    short: "Countries or regions the portfolio depends on.",
    category: "allocation"
  },
  currency_exposure: {
    label: "Currency exposure",
    short: "Currencies the portfolio depends on.",
    category: "allocation"
  },
  sector_exposure: {
    label: "Sector exposure",
    short: "Industry-sector mix of the portfolio.",
    category: "allocation"
  },
  theme_exposure: {
    label: "Theme exposure",
    short: "Exposure to app-defined investment themes.",
    category: "allocation"
  },
  look_through: {
    label: "Look-through",
    short: "Breaking a fund into the holdings it owns underneath.",
    category: "allocation"
  },
  fund_overlap: {
    label: "Fund overlap",
    short: "When multiple funds own the same underlying securities.",
    category: "allocation"
  },
  concentration: {
    label: "Concentration",
    short: "Too much exposure to one holding, sector, country, or theme.",
    category: "allocation"
  },
  hhi: {
    label: "HHI",
    short: "Concentration score calculated from squared portfolio weights.",
    category: "allocation"
  },
  cash: {
    label: "Cash",
    short: "Money or near-money holdings.",
    category: "asset_class"
  },
  bond: {
    label: "Bond",
    short: "A loan made to a government or company.",
    category: "asset_class"
  },
  government_bond: {
    label: "Government bond",
    short: "Bond issued by a government.",
    category: "asset_class"
  },
  corporate_bond: {
    label: "Corporate bond",
    short: "Bond issued by a company.",
    category: "asset_class"
  },
  equity: {
    label: "Equity",
    short: "Ownership stake in a company.",
    category: "asset_class"
  },
  etf: {
    label: "ETF",
    short: "Exchange-traded fund that holds a basket of assets.",
    category: "asset_class"
  },
  reit: {
    label: "REIT",
    short: "Real estate investment trust.",
    category: "asset_class"
  },
  commodity: {
    label: "Commodity",
    short: "Raw material exposure such as gold, oil, or copper.",
    category: "asset_class"
  },
  cryptoasset: {
    label: "Cryptoasset",
    short: "Digital asset such as Bitcoin or Ethereum.",
    category: "asset_class"
  },
  leveraged_etf: {
    label: "Leveraged ETF",
    short: "Fund designed to multiply daily returns of an index.",
    category: "asset_class"
  },
  expense_ratio: {
    label: "Expense ratio",
    short: "Yearly fund fee shown as a percentage of assets.",
    category: "fees"
  },
  platform_fee: {
    label: "Platform fee",
    short: "Fee charged by a broker or investment platform.",
    category: "fees"
  },
  fx_fee: {
    label: "FX fee",
    short: "The cost of converting one currency into another.",
    category: "fees"
  },
  transaction_fee: {
    label: "Transaction fee",
    short: "Fee paid to buy or sell.",
    category: "fees"
  },
  spread: {
    label: "Spread",
    short: "Difference between buy and sell price.",
    category: "fees"
  },
  tax_lot: {
    label: "Tax lot",
    short: "A purchase batch with its own date, quantity, and cost.",
    category: "fees"
  },
  cost_basis: {
    label: "Cost basis",
    short: "Original purchase cost used to estimate gain or loss.",
    category: "fees"
  },
  tax_drag: {
    label: "Tax drag",
    short: "Reduction in return caused by taxes.",
    category: "fees"
  },
  unrealized_gain: {
    label: "Unrealized gain",
    short: "Gain that exists on paper before selling.",
    category: "fees"
  },
  realized_gain: {
    label: "Realized gain",
    short: "Gain created by selling.",
    category: "fees"
  },
  fifo: {
    label: "FIFO",
    short: "First-in, first-out tax-lot method.",
    category: "fees"
  },
  specific_lot: {
    label: "Specific lot",
    short: "Choosing exactly which purchase lot to sell.",
    category: "fees"
  },
  fee_drag: {
    label: "Fee drag",
    short: "The amount fees reduce return over time.",
    category: "fees"
  },
  backtest: {
    label: "Backtest",
    short: "Testing how a portfolio would have performed in the past.",
    category: "simulation"
  },
  historical_return: {
    label: "Historical return",
    short: "Return observed in past data.",
    category: "simulation"
  },
  proxy: {
    label: "Proxy",
    short: "Substitute data used when exact data is unavailable.",
    category: "simulation"
  },
  survivorship_bias: {
    label: "Survivorship bias",
    short: "Error from excluding failed or delisted securities.",
    category: "simulation"
  },
  monte_carlo: {
    label: "Monte Carlo simulation",
    short: "Many simulated future paths based on assumptions.",
    long: "It is a range of possible outcomes, not a prediction.",
    category: "simulation"
  },
  percentile: {
    label: "Percentile",
    short: "A point in a range of possible outcomes.",
    category: "simulation"
  },
  success_probability: {
    label: "Success probability",
    short: "Percentage of simulated paths that reach the target.",
    category: "simulation"
  },
  data_quality: {
    label: "Data quality",
    short: "How complete, current, and reliable the inputs are.",
    category: "data"
  },
  complete_data: {
    label: "Complete data",
    short: "Enough data exists to calculate the metric reliably.",
    category: "data"
  },
  partial_data: {
    label: "Partial data",
    short: "Some required data is missing or estimated.",
    category: "data"
  },
  stale_data: {
    label: "Stale data",
    short: "Data is older than the allowed freshness threshold.",
    category: "data"
  },
  estimated_data: {
    label: "Estimated data",
    short: "Data inferred by the app.",
    category: "data"
  },
  unavailable_data: {
    label: "Unavailable data",
    short: "Data cannot currently be calculated.",
    category: "data"
  },
  data_freshness: {
    label: "Data freshness",
    short: "Whether inputs are fresh, stale, partial, or missing.",
    category: "data"
  },
  base_currency: {
    label: "Base currency",
    short: "Currency used to show portfolio totals and planning results.",
    category: "data"
  },
  risk_free_rate: {
    label: "Risk-free rate",
    short: "Reference return used when calculating risk-adjusted metrics.",
    category: "risk"
  },
  price_return: {
    label: "Price return",
    short: "Return from price movement only.",
    category: "performance"
  },
  income_return: {
    label: "Income return",
    short: "Return from dividends, interest, or distributions.",
    category: "performance"
  },
  information_ratio: {
    label: "Information ratio",
    short: "Active return compared with tracking error.",
    category: "performance"
  },
  calmar_ratio: {
    label: "Calmar ratio",
    short: "Return compared with maximum drawdown.",
    category: "risk"
  },
  covariance: {
    label: "Covariance",
    short: "How two assets move together in size and direction.",
    category: "risk"
  },
  var: {
    label: "VaR",
    short: "Estimated loss threshold at a chosen confidence level.",
    category: "risk"
  },
  expected_shortfall: {
    label: "Expected shortfall",
    short: "Average loss beyond the VaR threshold.",
    category: "risk"
  },
  money_market_fund: {
    label: "Money market fund",
    short: "Fund that invests in short-term cash-like instruments.",
    category: "asset_class"
  },
  t_bill: {
    label: "T-bill",
    short: "Short-term government debt.",
    category: "asset_class"
  },
  investment_grade_bond: {
    label: "Investment-grade bond",
    short: "Bond considered lower default risk by rating agencies.",
    category: "asset_class"
  },
  high_yield_bond: {
    label: "High-yield bond",
    short: "Bond with higher credit risk and usually higher yield.",
    category: "asset_class"
  },
  mutual_fund: {
    label: "Mutual fund",
    short: "Pooled fund usually traded once per day.",
    category: "asset_class"
  },
  alternative_asset: {
    label: "Alternative asset",
    short: "Asset outside traditional stocks, bonds, and cash.",
    category: "asset_class"
  },
  inverse_etf: {
    label: "Inverse ETF",
    short: "Fund designed to move opposite an index, usually daily.",
    category: "asset_class"
  },
  rebalance_frequency: {
    label: "Rebalance frequency",
    short: "How often the portfolio is reset to target weights.",
    category: "simulation"
  },
  bootstrap: {
    label: "Bootstrap",
    short: "Simulation method that resamples historical returns.",
    category: "simulation"
  },
  fat_tail_assumption: {
    label: "Fat-tail assumption",
    short: "Assumption that extreme events happen more often than normal models suggest.",
    category: "simulation"
  },
  user_provided_data: {
    label: "User-provided data",
    short: "Data entered by the user and not externally verified.",
    category: "data"
  },
  symbol: {
    label: "Symbol",
    short: "The ticker-like identifier used for instrument selection.",
    category: "data"
  },
  ticker: {
    label: "Ticker",
    short: "A commonly used, abbreviated market identifier.",
    category: "data"
  },
  exchange: {
    label: "Exchange",
    short: "Primary market where shares or units are listed.",
    category: "data"
  },
  country: {
    label: "Country",
    short: "The country associated with the instrument and issuer.",
    category: "data"
  },
  currency: {
    label: "Currency",
    short: "Trading and reporting currency for the instrument data.",
    category: "data"
  },
  asset_class: {
    label: "Asset class",
    short: "High-level investment category like equity, fixed income, or real assets.",
    category: "asset_class"
  },
  instrument_type: {
    label: "Instrument type",
    short: "The security type used for analysis assumptions (stock, ETF, bond, etc.).",
    category: "asset_class"
  },
  manual_holding: {
    label: "Manual holding",
    short: "An instrument added directly without matching sample catalog metadata.",
    category: "data"
  },
  listing_id: {
    label: "Listing ID",
    short: "Identifier for the specific exchange listing used for this holding.",
    category: "data"
  },
  listing: {
    label: "Listing",
    short: "An exchange-specific tradable form of an instrument, usually with its own symbol or local code.",
    category: "data"
  },
  instrument: {
    label: "Instrument",
    short: "The underlying security or fund that a holding references across multiple listings.",
    category: "data"
  },
  security: {
    label: "Security",
    short: "A financial asset that can be bought or sold in a market.",
    category: "asset_class"
  },
  common_stock: {
    label: "Common stock",
    short: "Standard equity ownership shares that usually carry voting rights.",
    category: "asset_class"
  },
  preferred_share: {
    label: "Preferred share",
    short: "Stock class with priority income and usually no voting rights.",
    category: "asset_class"
  },
  adr: {
    label: "ADR",
    short: "Deposit receipt for a foreign company’s shares on a domestic exchange.",
    category: "asset_class"
  },
  gdr: {
    label: "GDR",
    short: "Global depository receipt for a foreign issuer, often traded outside home market.",
    category: "asset_class"
  },
  warrant: {
    label: "Warrant",
    short: "Derivative giving the right to buy or sell shares in the future at set terms.",
    category: "asset_class"
  },
  right: {
    label: "Right",
    short: "Corporate entitlement allowing purchase of stock at a predefined price.",
    category: "asset_class"
  },
  unit: {
    label: "Unit",
    short: "A listed security bundle traded together, often in funds or special structures.",
    category: "asset_class"
  },
  inactive_security: {
    label: "Inactive security",
    short: "A listing currently inactive in this catalog but still recognized.",
    category: "data"
  },
  delisted_security: {
    label: "Delisted security",
    short: "A security removed from active listing, often with limited trading or data.",
    category: "data"
  },
  sector: {
    label: "Sector",
    short: "High-level grouping of companies by shared business focus.",
    category: "asset_class"
  },
  theme: {
    label: "Theme",
    short: "Higher-level investment narrative that groups instruments by idea or strategy.",
    category: "allocation"
  },
  trading_currency: {
    label: "Trading currency",
    short: "Currency used for transactions and quoted market prices.",
    category: "data"
  },
  issuer_domicile: {
    label: "Issuer domicile",
    short: "The legal country where the issuer is based.",
    category: "data"
  },
  listing_country: {
    label: "Listing country",
    short: "The country whose exchange hosts the trading listing.",
    category: "data"
  },
  industry: {
    label: "Industry",
    short: "Narrower business segment within a sector.",
    category: "asset_class"
  },
  gics_sector: {
    label: "GICS sector",
    short: "A standardized sector taxonomy used across global equity classification.",
    category: "asset_class"
  },
  isin: {
    label: "ISIN",
    short: "International Securities Identification Number used to identify traded securities.",
    category: "data"
  },
  figi: {
    label: "FIGI",
    short: "Open standard identifier for trading instruments across venues.",
    category: "data"
  },
  cusip: {
    label: "CUSIP",
    short: "Identifier used mainly for US and Canadian securities.",
    category: "data"
  },
  sedol: {
    label: "SEDOL",
    short: "UK/European identifier for equity and fund instruments.",
    category: "data"
  },
  local_code: {
    label: "Local code",
    short: "Exchange-native code used by brokers and regional markets.",
    category: "data"
  },
  canonical_identifier: {
    label: "Canonical identifier",
    short: "A stable internal identifier for the underlying instrument.",
    category: "data"
  },
  liquidity: {
    label: "Liquidity",
    short: "How easily an instrument can be bought or sold without large price impact.",
    category: "risk"
  },
  leveraged_product: {
    label: "Leveraged product",
    short: "Instrument that seeks magnified exposure to an underlying asset.",
    category: "asset_class"
  },
  inverse_product: {
    label: "Inverse product",
    short: "Instrument designed to move opposite to an underlying index or asset.",
    category: "asset_class"
  },
  fund_look_through: {
    label: "Fund look-through",
    short: "Method of exposing a fund’s underlying holdings for attribution analysis.",
    category: "allocation"
  },
  advanced_instrument: {
    label: "Advanced instrument",
    short: "Nonstandard or lower-liquidity instrument types that may require manual review.",
    category: "asset_class"
  }
};
