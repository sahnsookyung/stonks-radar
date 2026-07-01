defmodule StonksBackendWeb.PublicControllerTest do
  use ExUnit.Case, async: true
  import Plug.Conn
  import Plug.Test

  alias StonksBackend.{MarketData, Sources}

  @opts StonksBackendWeb.Router.init([])

  test "public health preserves snapshot-first service identity" do
    conn =
      :get
      |> conn("/api/public/health")
      |> dispatch()

    assert conn.status == 200
    body = Jason.decode!(conn.resp_body)
    assert body["status"] == "ok"
    assert body["service"] == "stonks-radar-api"
    assert body["public_read_path"] == "snapshot-first"
    assert get_resp_header(conn, "cache-control") == ["no-store"]
  end

  test "snapshot manifest proxy preserves static public URL" do
    conn =
      :get
      |> conn("/api/public/snapshot-manifest-proxy")
      |> dispatch()

    assert conn.status == 200
    assert get_resp_header(conn, "cache-control") == ["no-store"]

    assert Jason.decode!(conn.resp_body) == %{
             "manifest_url" => "/public/latest/manifest.json",
             "mode" => "local_oci"
           }
  end

  test "public status preserves shape and no-store security headers without a live db" do
    conn =
      :get
      |> conn("/api/public/status")
      |> dispatch()

    assert conn.status == 200
    assert get_resp_header(conn, "cache-control") == ["no-store"]

    assert get_resp_header(conn, "strict-transport-security") == [
             "max-age=31536000; includeSubDomains; preload"
           ]

    assert get_resp_header(conn, "x-content-type-options") == ["nosniff"]

    body = Jason.decode!(conn.resp_body)
    assert body["status"] == "ok"
    assert body["public_pages_depend_on_backend"] == false
    assert body["snapshot_storage"] == "local_oci"
    assert is_map(body["metrics"])
    assert Map.has_key?(body["metrics"], "dead_letter_jobs")
  end

  test "provider status keeps public provider keys and route security headers" do
    conn =
      :get
      |> conn("/api/public/provider-status")
      |> dispatch()

    assert conn.status == 200
    assert get_resp_header(conn, "cache-control") == ["no-store"]

    body = Jason.decode!(conn.resp_body)
    assert body["status"] == "ok"
    assert [%{} = first | _] = body["market_data_providers"]

    assert Map.keys(first) |> Enum.sort() == [
             "attribution_required",
             "endpoint_key",
             "provider_key",
             "public_display_allowed",
             "refresh_interval",
             "source_checked_at"
           ]
  end

  test "public search rejects missing or short queries and keeps stable result envelope" do
    missing =
      :get
      |> conn("/api/public/search")
      |> dispatch()

    assert missing.status == 422

    short =
      :get
      |> conn("/api/public/search?q=A")
      |> dispatch()

    assert short.status == 422

    ok =
      :get
      |> conn("/api/public/search?q=NV")
      |> dispatch()

    assert ok.status == 200
    assert %{"results" => results} = Jason.decode!(ok.resp_body)
    assert is_list(results)

    invalid_limit =
      :get
      |> conn("/api/public/search?q=NV&limit=oops")
      |> dispatch()

    assert invalid_limit.status == 422

    assert %{"detail" => [%{"loc" => ["query", "limit"]}]} =
             Jason.decode!(invalid_limit.resp_body)
  end

  test "public search rejects blank normalized queries before SQL" do
    conn =
      :get
      |> conn("/api/public/search?q=%20%20")
      |> dispatch()

    assert conn.status == 422
    assert %{"detail" => [%{"loc" => ["query", "q"]}]} = Jason.decode!(conn.resp_body)
  end

  test "public disclosure routes reject malformed filters before querying" do
    invalid_source =
      :get
      |> conn("/api/public/filings?source=BAD")
      |> dispatch()

    assert invalid_source.status == 422

    assert %{"detail" => [%{"loc" => ["query", "source"]}]} =
             Jason.decode!(invalid_source.resp_body)

    invalid_limit =
      :get
      |> conn("/api/public/transactions?limit=9999")
      |> dispatch()

    assert invalid_limit.status == 422

    assert %{"detail" => [%{"loc" => ["query", "limit"]}]} =
             Jason.decode!(invalid_limit.resp_body)

    invalid_ticker =
      :get
      |> conn("/api/public/filings?ticker=BAD$")
      |> dispatch()

    assert invalid_ticker.status == 422

    assert %{"detail" => [%{"loc" => ["query", "ticker"]}]} =
             Jason.decode!(invalid_ticker.resp_body)
  end

  test "public entity insiders rejects invalid ticker path segments" do
    conn =
      :get
      |> conn("/api/public/entities/BAD$/insiders")
      |> dispatch()

    assert conn.status == 422
    assert %{"detail" => [%{"loc" => ["path", "ticker"]}]} = Jason.decode!(conn.resp_body)
  end

  test "market history returns public license-limited shape and cache headers when db rows are unavailable" do
    conn =
      :get
      |> conn("/api/public/market/history?symbols=AAPL&start=2026-01-01&end=2026-01-03")
      |> dispatch()

    assert conn.status == 200
    assert get_resp_header(conn, "cache-control") == ["no-store"]
    assert get_resp_header(conn, "x-market-data-source") == ["license-limited"]

    body = Jason.decode!(conn.resp_body)
    assert body["status"] == "license_limited"
    assert body["display_mode"] == "public"
    assert body["series"] == [%{"symbol" => "AAPL", "points" => []}]
    assert body["data_freshness"]["license_mode"] == "public_display_not_allowed"
  end

  test "market history rejects inverted windows with legacy-compatible message" do
    conn =
      :get
      |> conn("/api/public/market/history?symbols=AAPL&start=2026-01-03&end=2026-01-01")
      |> dispatch()

    assert conn.status == 400
    assert Jason.decode!(conn.resp_body) == %{"detail" => "start date must be before end date"}
  end

  test "market history rejects malformed and oversized symbol parameters" do
    malformed =
      :get
      |> conn("/api/public/market/history?symbols=AAPL$&start=2026-01-01&end=2026-01-03")
      |> dispatch()

    assert malformed.status == 400
    assert Jason.decode!(malformed.resp_body) == %{"detail" => "unsupported symbol format: AAPL$"}

    oversized_symbols = String.duplicate("A", 257)

    oversized =
      :get
      |> conn(
        "/api/public/market/history?symbols=#{oversized_symbols}&start=2026-01-01&end=2026-01-03"
      )
      |> dispatch()

    assert oversized.status == 400
    assert Jason.decode!(oversized.resp_body) == %{"detail" => "symbols query is too long"}
  end

  test "market history pure row normalizer emits stored public series shape" do
    payload =
      MarketData.stored_payload_from_rows(
        ["AAPL"],
        ~D[2026-01-01],
        ~D[2026-01-02],
        [
          %{
            "symbol" => "AAPL",
            "price_date" => ~D[2026-01-02],
            "provider_key" => "twelve_data",
            "close" => "101.25",
            "adjusted_close" => "101.00",
            "volume" => "12345",
            "currency_code" => "USD",
            "exchange" => "NASDAQ",
            "timezone" => "America/New_York",
            "provider_price_timestamp" => nil,
            "ingested_at" => "2026-01-02T23:00:00Z",
            "source_hash" => "hash",
            "source_revision" => "rev",
            "quality_state" => "valid",
            "market_data_snapshot_id" => "00000000-0000-0000-0000-000000000001",
            "source_policy_json" => %{"raw_public_allowed" => true}
          }
        ]
      )

    assert payload.status == "ok"
    assert payload.display_status == "stored_public_allowed"
    assert payload.series |> hd() |> Map.fetch!(:points) |> hd() |> Map.get(:close) == 101.25

    assert {"etag", _value} =
             Enum.find(MarketData.cache_headers(payload), &(elem(&1, 0) == "etag"))
  end

  test "disclosure helpers preserve empty legacy envelopes without a live db" do
    filings = Sources.filings(%{})
    assert filings.filings == []
    assert is_list(filings.limitations)

    transactions = Sources.transactions(%{})
    assert transactions.transactions == []
    assert transactions.min_confidence == 0.9

    insiders = Sources.insiders("DJT", "10")
    assert insiders.ticker == "DJT"
    assert insiders.insiders == []
  end

  defp dispatch(conn) do
    conn
    |> fetch_query_params()
    |> StonksBackendWeb.Router.call(@opts)
  end
end
