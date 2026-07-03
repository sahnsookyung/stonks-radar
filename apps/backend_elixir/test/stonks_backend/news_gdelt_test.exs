defmodule StonksBackend.News.GdeltTest do
  use ExUnit.Case, async: true

  alias StonksBackend.News.Gdelt

  test "tracked country terms include the top GDP coverage set and requested additions" do
    terms = Gdelt.tracked_country_terms()

    for country <- [
          ~s("United States"),
          "China",
          "Germany",
          "Japan",
          "India",
          ~s("United Kingdom"),
          "France",
          "Italy",
          "Canada",
          "Brazil",
          "Russia",
          ~s("South Korea"),
          "Mexico",
          "Australia",
          "Norway",
          ~s("South Africa")
        ] do
      assert country in terms
    end
  end

  test "market-watch query packs rotate through bounded windows" do
    first_window = Gdelt.doc_queries("market_watch", 6, cycle_index: 0)
    second_window = Gdelt.doc_queries("market_watch", 6, cycle_index: 1)

    assert length(first_window) == 6
    assert length(second_window) == 6
    refute first_window == second_window
    assert Enum.any?(first_window, &String.contains?(&1, "United States"))

    sampled_windows =
      first_window ++ second_window ++ Gdelt.doc_queries("market_watch", 24, cycle_index: 2)

    assert Enum.any?(sampled_windows, &String.contains?(&1, "semiconductor"))
    assert Enum.any?(sampled_windows, &String.contains?(&1, "AI infrastructure"))
    assert Enum.any?(sampled_windows, &String.contains?(&1, "RKLB"))
    assert Enum.any?(sampled_windows, &String.contains?(&1, "Rocket Lab"))
  end

  test "tracked ticker terms come from shared watchlist config" do
    terms = Gdelt.tracked_ticker_terms()

    assert "RKLB" in terms
    assert ~s|"Rocket Lab"| in terms
    assert "NVDA" in terms
  end

  test "request params cap provider records and preserve metadata-only Doc API shape" do
    [query | _] = Gdelt.doc_queries(1)
    params = Gdelt.doc_request_params(query, 999)
    encoded_url = "https://api.gdeltproject.org/api/v2/doc/doc?" <> URI.encode_query(params)

    assert params["mode"] == "ArtList"
    assert params["format"] == "json"
    assert params["sort"] == "DateDesc"
    assert params["maxrecords"] == "250"
    assert params["timespan"] == "36h"
    assert Gdelt.doc_request_params(query, 10, timespan: "7d")["timespan"] == "7d"
    assert byte_size(encoded_url) < 1_200

    assert Gdelt.doc_queries("market_watch", 500)
           |> Enum.map(&Gdelt.doc_request_params(&1, 250))
           |> Enum.all?(fn request ->
             byte_size(
               "https://api.gdeltproject.org/api/v2/doc/doc?" <> URI.encode_query(request)
             ) <
               1_200
           end)
  end

  test "query summaries diversify per-query caps under source run limits" do
    summary =
      Gdelt.query_pack_summary(
        max_documents: 3,
        cycle_budget: 3,
        cycle_index: 0,
        provider_cap: 10
      )

    assert summary.query_pack == "market_watch"
    assert summary.query_count == 3
    assert summary.candidate_records_per_query == 10
    assert length(summary.queries) == 3
    assert length(summary.requests) == 3
  end

  test "Doc API parser uses real titles and URL slug fallback, never synthetic GDELT titles" do
    documents =
      Gdelt.parse_doc_payload(
        %{
          "articles" => [
            %{
              "title" => "GDELT event 190: IRAN / ISRAEL near LE",
              "url" => "https://www.arabnews.com/node/2648994/middle-east",
              "seendate" => "20260629T152531Z",
              "domain" => "arabnews.com",
              "sourcecountry" => "Iran",
              "language" => "English"
            },
            %{
              "title" => "Oil Prices Rise Again After US, Iran Exchange Strikes",
              "url" => "https://www.rferl.org/a/oil-prices-rise-us-iran-strikes/334.html",
              "seendate" => "20260629T162531Z",
              "domain" => "rferl.org",
              "sourcecountry" => "Iran",
              "language" => "English"
            },
            %{
              "title" => "French title",
              "url" => "https://example.com/story",
              "language" => "French"
            }
          ]
        },
        10
      )

    titles = Enum.map(documents, & &1["title"])

    assert "Arab News source report: Iran" in titles
    assert "Oil Prices Rise Again After US, Iran Exchange Strikes" in titles
    refute Enum.any?(titles, &String.starts_with?(&1, "GDELT event"))
    assert Enum.all?(documents, & &1["discovery_only"])
    assert Enum.all?(documents, &(&1["trust_tier"] == "T4_WEAK_SIGNAL"))
  end

  test "Doc API fetch dedupes candidates across query packs" do
    summary = %{
      query_pack: "market_watch",
      requests: [
        %{"query" => "energy", "mode" => "ArtList"},
        %{"query" => "semis", "mode" => "ArtList"}
      ]
    }

    request_fun = fn _endpoint, opts ->
      assert opts[:headers] == [{"accept", "application/json"}]

      {:ok,
       %{
         status: 200,
         body: %{
           "articles" => [
             %{
               "title" => "Export Controls Hit Advanced Chips",
               "url" => "https://example.com/export-controls-hit-advanced-chips",
               "seendate" => "20260629T152531Z",
               "domain" => "example.com",
               "sourcecountry" => "United States",
               "language" => "English"
             },
             %{
               "title" => "No geography survives parsing",
               "url" => "https://example.com/no-geo",
               "seendate" => "20260629T152531Z",
               "domain" => "example.com",
               "sourcecountry" => "",
               "language" => "English"
             },
             %{
               "title" => "French title",
               "url" => "https://example.com/french",
               "sourcecountry" => "France",
               "language" => "French"
             }
           ]
         }
       }}
    end

    {documents, discovery} =
      Gdelt.fetch_doc_documents(summary,
        endpoint: "https://gdelt.example/doc",
        max_documents: 10,
        request_fun: request_fun
      )

    assert length(documents) == 1
    assert discovery.fetched == 2
    assert discovery.parsed == 2
    assert discovery.deduped == 1
    assert discovery.no_geo_dropped == 2
    assert discovery.irrelevant_dropped == 2
    assert discovery.published_or_projected == 1
  end

  test "Doc API fetch can enrich fallback titles with metadata-only SafeFetch" do
    summary = %{
      query_pack: "market_watch",
      requests: [%{"query" => "energy", "mode" => "ArtList"}]
    }

    request_fun = fn _endpoint, _opts ->
      {:ok,
       %{
         status: 200,
         body: %{
           "articles" => [
             %{
               "title" => "GDELT event 190: IRAN / ISRAEL near LE",
               "url" => "https://www.arabnews.com/node/2648994/middle-east",
               "seendate" => "20260629T152531Z",
               "domain" => "arabnews.com",
               "sourcecountry" => "Iran",
               "language" => "English"
             }
           ]
         }
       }}
    end

    title_fetch_fun = fn url, opts ->
      assert url == "https://www.arabnews.com/node/2648994/middle-east"
      assert opts[:max_bytes] == 8192
      {:ok, %{"title" => "Arab News real headline from metadata", "final_url" => url}}
    end

    {documents, discovery} =
      Gdelt.fetch_doc_documents(summary,
        endpoint: "https://gdelt.example/doc",
        max_documents: 10,
        request_fun: request_fun,
        title_fetch_fun: title_fetch_fun,
        title_fetch_limit: 1,
        title_fetch_max_bytes: 8192
      )

    assert [%{"title" => "Arab News real headline from metadata"}] = documents
    assert discovery.title_enriched == 1
    refute Enum.any?(documents, &String.starts_with?(&1["title"], "GDELT event"))
  end

  test "Doc API title enrichment uses persistent cache before fetching metadata" do
    summary = %{
      query_pack: "market_watch",
      requests: [%{"query" => "energy", "mode" => "ArtList"}]
    }

    request_fun = fn _endpoint, _opts ->
      {:ok,
       %{
         status: 200,
         body: %{
           "articles" => [
             %{
               "title" => "GDELT event 190: IRAN / ISRAEL near LE",
               "url" => "https://www.arabnews.com/node/2648994/middle-east",
               "seendate" => "20260629T152531Z",
               "domain" => "arabnews.com",
               "sourcecountry" => "Iran",
               "language" => "English"
             }
           ]
         }
       }}
    end

    title_fetch_fun = fn _url, _opts -> flunk("cache hit should avoid SafeFetch") end

    title_cache_get_fun = fn "gdelt:doc:" <> _hash ->
      %{
        "title" => "Arab News cached metadata headline",
        "canonical_url" => "https://www.arabnews.com/node/2648994/middle-east",
        "source_domain" => "arabnews.com",
        "published_at" => "2026-06-29T15:25:31Z"
      }
    end

    {documents, discovery} =
      Gdelt.fetch_doc_documents(summary,
        endpoint: "https://gdelt.example/doc",
        max_documents: 10,
        request_fun: request_fun,
        title_fetch_fun: title_fetch_fun,
        title_cache_get_fun: title_cache_get_fun,
        title_fetch_limit: 1
      )

    assert [
             %{
               "title" => "Arab News cached metadata headline",
               "published_at" => "2026-06-29T15:25:31Z",
               "metadata" => %{
                 "gdelt_title_source" => "persistent_title_cache",
                 "gdelt_title_cache" => %{"source_domain" => "arabnews.com"}
               }
             }
           ] = documents

    assert discovery.title_enriched == 1
  end
end
