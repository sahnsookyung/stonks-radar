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
    assert Enum.any?(second_window, &String.contains?(&1, "semiconductor"))
    assert Enum.any?(second_window, &String.contains?(&1, "AI infrastructure"))
  end

  test "request params cap provider records and preserve metadata-only Doc API shape" do
    [query | _] = Gdelt.doc_queries(1)
    params = Gdelt.doc_request_params(query, 999)
    encoded_url = "https://api.gdeltproject.org/api/v2/doc/doc?" <> URI.encode_query(params)

    assert params["mode"] == "ArtList"
    assert params["format"] == "json"
    assert params["sort"] == "DateDesc"
    assert params["maxrecords"] == "250"
    assert byte_size(encoded_url) < 1_200
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
    assert discovery.published_or_projected == 1
  end
end
