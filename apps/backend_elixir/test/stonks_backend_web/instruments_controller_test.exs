defmodule StonksBackendWeb.InstrumentsControllerTest do
  use ExUnit.Case, async: false
  import Plug.Conn
  import Plug.Test

  alias StonksBackend.Instruments

  @opts StonksBackendWeb.Router.init([])

  setup do
    original = Application.get_env(:stonks_backend, :settings)
    clear_provider_cache()
    Application.put_env(:stonks_backend, :settings, test_settings(original))

    on_exit(fn ->
      if is_nil(original) do
        Application.delete_env(:stonks_backend, :settings)
      else
        Application.put_env(:stonks_backend, :settings, original)
      end

      clear_provider_cache()
    end)
  end

  test "instrument search preserves legacy autocomplete result shape" do
    conn =
      :get
      |> conn("/api/instruments/search?q=005930&limit=5")
      |> dispatch()

    assert conn.status == 200
    body = Jason.decode!(conn.resp_body)
    assert body["dataFreshness"]["source"] == "local_scheduled_index"
    assert [first | _] = body["results"]
    assert first["instrumentId"] == "005930.KS"
    assert first["listingId"] == "KRX:005930"
    assert first["currency"] == "KRW"
    assert "IDENTIFIER_EXACT" in first["matchedOn"]
  end

  test "instrument search includes shared tracked ticker watchlist entries" do
    conn =
      :get
      |> conn("/api/instruments/search?q=RKLB&limit=5")
      |> dispatch()

    assert conn.status == 200
    body = Jason.decode!(conn.resp_body)
    assert [first | _] = body["results"]
    assert first["instrumentId"] == "RKLB"
    assert first["listingId"] == "NASDAQ:RKLB"
    assert first["name"] =~ "Rocket Lab"
    assert first["priceCoverage"] == "unavailable"

    assert Enum.any?(
             body["dataFreshness"]["providerStatuses"],
             &(&1["source"] == "ticker_watchlist" and &1["instrument_count"] > 0)
           )
  end

  test "instrument search uses configured provider lookup and quote fallback for unknown symbols" do
    Application.put_env(:stonks_backend, :settings,
      instrument_provider_search_enabled: "true",
      fmp_api_key: "fmp-token",
      instrument_provider_search_cache_seconds: "60",
      instrument_provider_request_fun: fn url, opts ->
        params = Keyword.fetch!(opts, :params)

        cond do
          String.ends_with?(url, "/search-symbol") ->
            assert params["query"] == "ZZZZ"
            assert params["apikey"] == "fmp-token"

            {:ok,
             %{
               status: 200,
               body: [
                 %{
                   "symbol" => "ZZZZ",
                   "name" => "Zeta Space Holdings",
                   "exchangeShortName" => "NASDAQ",
                   "currency" => "USD"
                 }
               ]
             }}

          String.ends_with?(url, "/quote-short") ->
            assert params["symbol"] == "ZZZZ"
            {:ok, %{status: 200, body: [%{"symbol" => "ZZZZ", "price" => 12.34}]}}

          true ->
            flunk("unexpected provider URL #{url}")
        end
      end
    )

    conn =
      :get
      |> conn("/api/instruments/search?q=ZZZZ&limit=5&context=BUILDER")
      |> dispatch()

    assert conn.status == 200
    body = Jason.decode!(conn.resp_body)
    assert [first | _] = body["results"]
    assert first["instrumentId"] == "ZZZZ"
    assert first["listingId"] == "NASDAQ:ZZZZ"
    assert first["priceCoverage"] == "available"
    assert first["calculationEligible"] == true
    assert first["requiresUserPrice"] == false
    assert first["currentPrice"] == 12.34
    assert "fmp_quote_short" in first["sourceProviders"]
  end

  test "instrument search enriches exact local ticker matches when quote provider is configured" do
    Application.put_env(:stonks_backend, :settings,
      instrument_provider_search_enabled: "true",
      instrument_public_symbol_lookup_enabled: "false",
      fmp_api_key: "fmp-token",
      instrument_provider_search_cache_seconds: "60",
      instrument_provider_request_fun: fn url, opts ->
        params = Keyword.fetch!(opts, :params)

        cond do
          String.ends_with?(url, "/search-symbol") ->
            assert params["query"] == "RKLB"
            assert params["apikey"] == "fmp-token"

            {:ok,
             %{
               status: 200,
               body: [
                 %{
                   "symbol" => "RKLB",
                   "name" => "Rocket Lab USA, Inc.",
                   "exchangeShortName" => "NASDAQ",
                   "currency" => "USD"
                 }
               ]
             }}

          String.ends_with?(url, "/quote-short") ->
            assert params["symbol"] == "RKLB"
            {:ok, %{status: 200, body: [%{"symbol" => "RKLB", "price" => 27.42}]}}

          true ->
            flunk("unexpected provider URL #{url}")
        end
      end
    )

    conn =
      :get
      |> conn("/api/instruments/search?q=RKLB&limit=5&context=BUILDER")
      |> dispatch()

    assert conn.status == 200
    body = Jason.decode!(conn.resp_body)
    assert [first | _] = body["results"]
    assert first["instrumentId"] == "RKLB"
    assert first["listingId"] == "NASDAQ:RKLB"
    assert first["priceCoverage"] == "available"
    assert first["calculationEligible"] == true
    assert first["requiresUserPrice"] == false
    assert first["currentPrice"] == 27.42
    assert "fmp_quote_short" in first["sourceProviders"]
  end

  test "instrument search falls back to public symbol directory without provider keys" do
    Application.put_env(:stonks_backend, :settings,
      instrument_provider_search_enabled: "true",
      instrument_public_symbol_lookup_enabled: "true",
      instrument_public_symbol_directory_cache_seconds: "60",
      instrument_provider_request_fun: fn url, _opts ->
        cond do
          String.ends_with?(url, "/nasdaqlisted.txt") ->
            {:ok,
             %{
               status: 200,
               body:
                 "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\nFREE|Free Range Robotics, Inc. Common Stock|Q|N|N|100|N|N\nTEST|Ignored Test Issue|Q|Y|N|100|N|N\nFile Creation Time:0701202618:00"
             }}

          String.ends_with?(url, "/otherlisted.txt") ->
            {:ok,
             %{
               status: 200,
               body:
                 "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\nBOND|Bond Ladder ETF|P|BOND|Y|100|N|BOND\nFile Creation Time:0701202618:00"
             }}

          true ->
            flunk("unexpected provider URL #{url}")
        end
      end
    )

    conn =
      :get
      |> conn("/api/instruments/search?q=FREE&limit=5&context=BUILDER")
      |> dispatch()

    assert conn.status == 200
    body = Jason.decode!(conn.resp_body)
    assert [first | _] = body["results"]
    assert first["instrumentId"] == "FREE"
    assert first["listingId"] == "NASDAQ:FREE"
    assert first["name"] == "Free Range Robotics, Inc. Common Stock"
    assert first["priceCoverage"] == "unavailable"
    assert first["calculationEligible"] == false
    assert first["requiresUserPrice"] == true
    assert "nasdaq_trader_symbol_directory" in first["sourceProviders"]

    assert Enum.any?(
             body["dataFreshness"]["providerStatuses"],
             &(&1["source"] == "nasdaq_trader_symbol_directory" and
                 &1["status"] == "configured")
           )
  end

  test "instrument search hides advanced instruments unless requested" do
    hidden = Instruments.search("Apple")
    visible = Instruments.search("Apple warrant", include_advanced: true)

    refute Enum.any?(hidden.results, &(&1["instrumentId"] == "AAPL.WS"))
    assert List.first(visible.results)["instrumentId"] == "AAPL.WS"
  end

  test "instrument search validates missing query with legacy-compatible shape" do
    conn =
      :get
      |> conn("/api/instruments/search")
      |> dispatch()

    assert conn.status == 422
    assert %{"detail" => [%{"loc" => ["query", "q"]}]} = Jason.decode!(conn.resp_body)
  end

  test "instrument search rejects whitespace-only query before index work" do
    conn =
      :get
      |> conn("/api/instruments/search?q=%20%20")
      |> dispatch()

    assert conn.status == 422
    assert get_resp_header(conn, "cache-control") == ["no-store"]
    assert %{"detail" => [%{"loc" => ["query", "q"]}]} = Jason.decode!(conn.resp_body)
  end

  test "instrument search rejects malformed limit and boolean params before index work" do
    invalid_limit =
      :get
      |> conn("/api/instruments/search?q=AAPL&limit=100")
      |> dispatch()

    assert invalid_limit.status == 422

    assert %{"detail" => [%{"loc" => ["query", "limit"]}]} =
             Jason.decode!(invalid_limit.resp_body)

    invalid_bool =
      :get
      |> conn("/api/instruments/search?q=AAPL&include_advanced=maybe")
      |> dispatch()

    assert invalid_bool.status == 422

    assert %{"detail" => [%{"loc" => ["query", "include_advanced"]}]} =
             Jason.decode!(invalid_bool.resp_body)
  end

  test "resolve preserves match status, confidence, and listing metadata" do
    payload =
      Instruments.resolve(%{
        "symbol" => "005930",
        "exchange" => "KRX",
        "currency" => "KRW"
      })

    assert payload.status == "MATCHED"
    assert payload.confidence == "HIGH"
    assert [match] = payload.matches
    assert match["listingId"] == "KRX:005930"
  end

  test "resolve accepts known atom-key payloads without creating atoms dynamically" do
    payload =
      Instruments.resolve(%{
        symbol: "005930",
        exchange: "KRX",
        currency: "KRW"
      })

    assert payload.status == "MATCHED"
    assert [match] = payload.matches
    assert match["listingId"] == "KRX:005930"
  end

  test "detail honors listing_id filter" do
    matched =
      :get
      |> conn("/api/instruments/AAPL?listing_id=NASDAQ:AAPL")
      |> dispatch()

    assert matched.status == 200
    assert %{"listings" => [%{"listingId" => "NASDAQ:AAPL"}]} = Jason.decode!(matched.resp_body)

    missing =
      :get
      |> conn("/api/instruments/AAPL?listing_id=NYSE:AAPL")
      |> dispatch()

    assert missing.status == 404
    assert Jason.decode!(missing.resp_body) == %{"detail" => "Instrument not found"}
  end

  test "resolve returns no-match envelope instead of nil result" do
    payload = Instruments.resolve(%{"symbol" => "NOT_A_REAL_SYMBOL"})

    assert payload == %{status: "NO_MATCH", confidence: "LOW", matches: []}
  end

  test "resolve rejects blank and malformed symbols before matching" do
    blank = json_dispatch(:post, "/api/instruments/resolve", %{"symbol" => "   "})

    assert blank.status == 422
    assert %{"detail" => [%{"loc" => ["body", "symbol"]}]} = Jason.decode!(blank.resp_body)

    malformed = json_dispatch(:post, "/api/instruments/resolve", %{"symbol" => "AAPL$"})

    assert malformed.status == 422
    assert %{"detail" => [%{"loc" => ["body", "symbol"]}]} = Jason.decode!(malformed.resp_body)
  end

  test "detail rejects malformed instrument and listing ids without fallback matches" do
    bad_id =
      :get
      |> conn("/api/instruments/%21%21%21")
      |> dispatch()

    assert bad_id.status == 422

    assert %{"detail" => [%{"loc" => ["path", "instrument_id"]}]} =
             Jason.decode!(bad_id.resp_body)

    bad_listing =
      :get
      |> conn("/api/instruments/AAPL?listing_id=%21%21%21")
      |> dispatch()

    assert bad_listing.status == 422

    assert %{"detail" => [%{"loc" => ["query", "listing_id"]}]} =
             Jason.decode!(bad_listing.resp_body)

    assert Instruments.detail("!!!") == nil
    assert Instruments.detail("AAPL", "!!!") == nil
  end

  test "review request normalization trims fields and rejects invalid context" do
    assert {:ok, request} =
             Instruments.normalize_review_request(%{
               "query" => "  QBTS  ",
               "context_screen" => "BUILDER",
               "optional_notes" => "  verify listing  "
             })

    assert request == %{
             query: "QBTS",
             context_screen: "BUILDER",
             optional_notes: "verify listing"
           }

    assert {:error, message} =
             Instruments.normalize_review_request(%{
               "query" => "QBTS",
               "context_screen" => "UNKNOWN"
             })

    assert message =~ "context_screen must be one of"
  end

  test "review request creation returns shaped storage-unavailable error without db" do
    assert {:error, 503, %{detail: "Instrument review request storage unavailable"}} =
             Instruments.create_review_request(
               %{"query" => "QBTS"},
               Instruments.client_identity_hash("127.0.0.1")
             )
  end

  defp dispatch(conn) do
    conn
    |> fetch_query_params()
    |> StonksBackendWeb.Router.call(@opts)
  end

  defp json_dispatch(method, path, body) do
    method
    |> conn(path, Jason.encode!(body))
    |> put_req_header("content-type", "application/json")
    |> StonksBackendWeb.Endpoint.call([])
  end

  defp clear_provider_cache do
    case :ets.whereis(:stonks_backend_instrument_provider_cache) do
      :undefined -> :ok
      table -> :ets.delete_all_objects(table)
    end
  end

  defp test_settings(nil), do: [instrument_public_symbol_lookup_enabled: "false"]

  defp test_settings(settings) when is_list(settings) do
    Keyword.put(settings, :instrument_public_symbol_lookup_enabled, "false")
  end

  defp test_settings(settings) when is_map(settings) do
    settings
    |> Map.to_list()
    |> Keyword.put(:instrument_public_symbol_lookup_enabled, "false")
  end
end
