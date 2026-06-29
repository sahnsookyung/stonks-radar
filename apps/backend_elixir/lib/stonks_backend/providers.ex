defmodule StonksBackend.Providers do
  @moduledoc "Provider budget and public status compatibility."

  alias StonksBackend.Sql

  @market_data_provider_keys ["twelve_data", "alpha_vantage", "fmp", "finnhub", "marketdata_app"]
  @quota_factor 0.7

  def public_status do
    %{status: "ok", market_data_providers: public_provider_rows()}
  end

  def public_provider_rows(rows \\ nil) do
    rows = rows || provider_capability_rows()

    rows
    |> Enum.filter(&(Map.get(&1, "provider_key") in @market_data_provider_keys))
    |> Enum.map(&public_provider_status/1)
    |> Enum.sort_by(&{&1.provider_key, &1.endpoint_key})
  end

  def public_provider_status(item) do
    %{
      provider_key: item["provider_key"],
      endpoint_key: item["endpoint_key"] || "*",
      public_display_allowed: truthy?(item["public_display_allowed"]),
      attribution_required: truthy?(item["attribution_required"]),
      refresh_interval: refresh_interval(item),
      source_checked_at: item["source_checked_at"]
    }
  end

  defp provider_capability_rows do
    providers =
      Sql.all("""
      select
        cap.provider_key,
        cap.endpoint_key,
        cap.max_requests_per_minute,
        cap.max_requests_per_day,
        cap.source_checked_at,
        coalesce(policy.raw_public_allowed, false) as public_display_allowed,
        coalesce(policy.attribution_required, false) as attribution_required
      from market_data_provider_capability cap
      left join market_data_source_policy policy
        on policy.provider_key = cap.provider_key
       and policy.endpoint_key = cap.endpoint_key
      where cap.active = true
      order by cap.provider_key, cap.endpoint_key
      """)

    if providers == [] do
      fallback_provider_rows()
    else
      providers
    end
  end

  def budgets do
    Sql.all("""
    select id, provider_key, provider_type, routing_mode, kill_switch_enabled,
           current_period_usage, hard_limit
    from provider_budget
    order by provider_key
    """)
  end

  def set_kill_switch(id, enabled) do
    Sql.execute("update provider_budget set kill_switch_enabled = $1 where id = $2", [enabled, id])
  end

  defp fallback_provider_rows do
    [
      %{
        "provider_key" => "twelve_data",
        "endpoint_key" => "daily_prices",
        "max_requests_per_minute" => 6,
        "max_requests_per_day" => 700,
        "public_display_allowed" => false,
        "attribution_required" => true,
        "source_checked_at" => "2026-05-25"
      },
      %{
        "provider_key" => "alpha_vantage",
        "endpoint_key" => "daily_prices",
        "max_requests_per_day" => 20,
        "public_display_allowed" => false,
        "attribution_required" => false,
        "source_checked_at" => "2026-05-25"
      },
      %{
        "provider_key" => "fmp",
        "endpoint_key" => "daily_prices",
        "max_requests_per_day" => 200,
        "public_display_allowed" => false,
        "attribution_required" => false,
        "source_checked_at" => "2026-05-25"
      },
      %{
        "provider_key" => "finnhub",
        "endpoint_key" => "*",
        "max_requests_per_minute" => 30,
        "public_display_allowed" => false,
        "attribution_required" => false,
        "source_checked_at" => "2026-05-25"
      }
    ]
  end

  defp refresh_interval(%{"rules" => rules}) when is_list(rules) do
    rules
    |> Enum.filter(&(Map.get(&1, "unit") == "request" && present?(Map.get(&1, "window_seconds"))))
    |> Enum.max_by(&to_number(Map.get(&1, "window_seconds")), fn -> nil end)
    |> interval_from_rule()
  end

  defp refresh_interval(item) do
    minute_cap = to_number(item["max_requests_per_minute"])
    day_cap = to_number(item["max_requests_per_day"])

    rules =
      []
      |> maybe_rule(60, minute_cap)
      |> maybe_rule(86_400, day_cap)

    rules
    |> Enum.max_by(&Map.fetch!(&1, "window_seconds"), fn -> nil end)
    |> interval_from_rule()
  end

  defp maybe_rule(rules, _window, nil), do: rules
  defp maybe_rule(rules, _window, cap) when cap <= 0, do: rules

  defp maybe_rule(rules, window, cap) do
    [
      %{"unit" => "request", "window_seconds" => window, "limit" => max(1.0, cap * @quota_factor)}
      | rules
    ]
  end

  defp interval_from_rule(nil), do: "policy-defined"

  defp interval_from_rule(rule) do
    window_seconds = to_number(rule["window_seconds"]) || 0
    limit = to_number(rule["limit"]) || 0

    if window_seconds <= 0 or limit <= 0 do
      "policy-defined"
    else
      seconds_per_request = max(1, round(window_seconds / limit))

      cond do
        seconds_per_request < 60 -> "at most every #{seconds_per_request}s"
        seconds_per_request < 3_600 -> "at most every #{round(seconds_per_request / 60)}m"
        true -> "at most every #{round(seconds_per_request / 3_600)}h"
      end
    end
  end

  defp truthy?(value) when value in [true, "true", "t", "1", 1], do: true
  defp truthy?(_value), do: false

  defp present?(nil), do: false
  defp present?(""), do: false
  defp present?(_value), do: true

  defp to_number(nil), do: nil
  defp to_number(value) when is_integer(value), do: value * 1.0
  defp to_number(value) when is_float(value), do: value

  defp to_number(value) do
    case Float.parse(to_string(value)) do
      {parsed, _rest} -> parsed
      :error -> nil
    end
  end
end
