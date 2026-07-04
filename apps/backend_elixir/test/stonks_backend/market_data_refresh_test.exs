defmodule StonksBackend.MarketDataRefreshTest do
  use ExUnit.Case, async: false

  alias StonksBackend.MarketData

  setup do
    original = Application.get_env(:stonks_backend, :settings)

    on_exit(fn ->
      if is_nil(original) do
        Application.delete_env(:stonks_backend, :settings)
      else
        Application.put_env(:stonks_backend, :settings, original)
      end
    end)
  end

  test "refresh_history reports configured providers with missing keys instead of fake queueing" do
    Application.put_env(:stonks_backend, :settings,
      market_data_provider_order: "twelve_data,alpha_vantage",
      market_data_snapshot_window_days: "5",
      source_fetch_timeout_seconds: "1"
    )

    assert {:error, result} =
             MarketData.refresh_history(%{
               "symbol" => "NVDA",
               "market_session_date" => "2026-06-30"
             })

    assert result.status == "provider_unavailable"
    assert result.symbol == "NVDA"
    assert result.start == "2026-06-25"
    assert result.end == "2026-06-30"
    assert Enum.map(result.attempts, & &1.status) == ["missing_api_key", "missing_api_key"]
  end

  test "refresh_history honors the runtime kill switch before provider work" do
    Application.put_env(:stonks_backend, :settings,
      market_data_scheduled_refresh_enabled: "false",
      market_data_api_key: "would-not-be-used"
    )

    assert {:ok, result} =
             MarketData.refresh_history(%{
               "symbol" => "NVDA",
               "market_session_date" => "2026-06-30"
             })

    assert result.status == "disabled"
    assert result.reason == "market_data_scheduled_refresh_enabled_false"
  end

  test "refresh_history validates symbols before provider work" do
    assert {:error, :invalid_symbol} =
             MarketData.refresh_history(%{
               "symbol" => "../NVDA",
               "start" => "2026-06-01",
               "end" => "2026-06-30"
             })
  end

  test "provider-specific keys fall back to MARKET_DATA_API_KEY when absent" do
    Application.put_env(:stonks_backend, :settings,
      market_data_api_key: "generic-token",
      twelve_data_api_key: nil,
      alpha_vantage_api_key: "",
      fmp_api_key: "fmp-token"
    )

    assert {:ok, "generic-token"} = MarketData.configured_provider_api_key("twelve_data")
    assert {:ok, "generic-token"} = MarketData.configured_provider_api_key("alpha_vantage")
    assert {:ok, "fmp-token"} = MarketData.configured_provider_api_key("fmp")
  end
end
