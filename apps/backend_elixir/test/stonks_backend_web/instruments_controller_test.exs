defmodule StonksBackendWeb.InstrumentsControllerTest do
  use ExUnit.Case, async: true
  import Plug.Conn
  import Plug.Test

  alias StonksBackend.Instruments

  @opts StonksBackendWeb.Router.init([])

  test "instrument search preserves FastAPI autocomplete result shape" do
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

  test "instrument search hides advanced instruments unless requested" do
    hidden = Instruments.search("Apple")
    visible = Instruments.search("Apple warrant", include_advanced: true)

    refute Enum.any?(hidden.results, &(&1["instrumentId"] == "AAPL.WS"))
    assert List.first(visible.results)["instrumentId"] == "AAPL.WS"
  end

  test "instrument search validates missing query like FastAPI" do
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
end
