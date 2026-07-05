defmodule StonksBackend.MarketData.PublicPayloads do
  @moduledoc "Public-display payloads and cache policy for market history responses."

  @us_market_timezone "America/New_York"
  @license_limited_reason "No source-policy-approved stored daily bars are available for public display. Public routes do not spend provider quota or fetch live licensed market data on demand; use the TradingView widget for public visual market display until scheduled stored data is approved."

  def cache_headers(%{status: "ok"} = payload) do
    digest =
      payload
      |> Map.take([
        :status,
        :symbols,
        :start,
        :end,
        :market_data_version,
        :market_data_snapshot_id,
        :provider
      ])
      |> Jason.encode!()
      |> then(&:crypto.hash(:sha256, &1))
      |> Base.encode16(case: :lower)
      |> String.slice(0, 24)

    [
      {"cache-control", "public, max-age=300, s-maxage=900, stale-while-revalidate=300"},
      {"etag", ~s("market-history-#{digest}")},
      {"vary", "Accept-Encoding"},
      {"x-market-data-source", "stored-snapshot"}
    ]
  end

  def cache_headers(%{status: "license_limited"}) do
    [{"cache-control", "no-store"}, {"x-market-data-source", "license-limited"}]
  end

  def cache_headers(_), do: [{"cache-control", "no-store"}]

  def license_limited_payload(symbols, start_date, end_date, reason \\ @license_limited_reason) do
    fetched_at = DateTime.utc_now() |> DateTime.to_iso8601()

    %{
      status: "license_limited",
      provider: "tradingview_widget_only",
      source_note: reason,
      cache: "miss",
      display_mode: "public",
      display_status: "license_limited",
      data_freshness: %{
        provider: "tradingview_widget_only",
        provider_timestamp: nil,
        fetched_at: fetched_at,
        source_observed_at: nil,
        market_session_date: nil,
        complete_through: nil,
        hard_expires_at: nil,
        staleness_state: "license_limited",
        calculation_eligible: false,
        delayed_by_seconds: nil,
        exchange_timezone: @us_market_timezone,
        delay_label: "license-limited",
        is_same_day_valid: false,
        is_public_display_allowed: false,
        staleness_reason: reason,
        license_mode: "public_display_not_allowed",
        source_url: "https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/"
      },
      provider_budget_status: [],
      symbols: symbols,
      start: Date.to_iso8601(start_date),
      end: Date.to_iso8601(end_date),
      series: Enum.map(symbols, &%{symbol: &1, points: []}),
      warnings: [reason]
    }
  end
end
