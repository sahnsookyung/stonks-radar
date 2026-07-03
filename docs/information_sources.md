# Information Sources

This is the operator-facing source map for Stonks Radar. Source and provider
operations are admin-only; this file records why each source class exists.

## Provider Order

- Market history for portfolio analytics: `Twelve Data` primary, `Alpha Vantage`
  secondary, `Financial Modeling Prep` tertiary. Keys stay server-side and the
  browser calls `/api/public/market/history`.
- Short pressure: FINRA short interest for open positions, FINRA Reg SHO daily
  short sale volume for monitored ticker flow. Authenticated FINRA access uses
  server-side configured credentials when available, and these signals must
  never be conflated.
- Filings: SEC EDGAR submissions/companyfacts for issuer, insider, and
  beneficial-ownership monitoring. The production user agent must include a
  working contact.
- Public fund portfolios: SEC EDGAR 13F XML information tables for source-linked
  quarterly holdings. HedgeFollow-style pages may be useful for comparison, but
  production ingestion uses SEC filings because vendor HTML can be protected,
  delayed, or policy-ambiguous.
- Public short research: Muddy Waters, Viceroy,
  Spruce Point, Kerrisdale, Culper, Blue Orca, and Grizzly public report pages.
- Weak OSINT: Pentagon.Pizza, NASA FIRMS, port/customs/logistics, and ADS-B
  candidates are discovery context only. They cannot publish high-confidence
  events without stronger corroboration.
- Overlooked official demand signals: defense contract announcements,
  USAspending/FPDS/SAM.gov candidates, Treasury TIC, and agency release feeds.

## Safety Rules

- Official sources outrank vendors; vendors outrank aggregators; weak OSINT never
  stands alone.
- Raw restricted text is not published. Store structured facts, metadata, hashes,
  and short policy-allowed excerpts only.
- Realtime-like polling is bounded by provider budgets, rate limits, cache TTLs,
  and publication review gates.
- Public pages remain snapshot-first. User-triggered tools may call the API, but
  dashboard rendering must not depend on live provider reads.
