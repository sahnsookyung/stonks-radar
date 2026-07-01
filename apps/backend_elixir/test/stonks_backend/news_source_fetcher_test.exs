defmodule StonksBackend.News.SourceFetcherTest do
  use ExUnit.Case, async: true

  alias StonksBackend.News.SourceFetcher

  test "RSS feeds are parsed into metadata-only source documents" do
    xml = """
    <?xml version="1.0" encoding="UTF-8"?>
    <rss><channel>
      <item>
        <title>Fed announces rate decision</title>
        <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20260701a.htm</link>
        <pubDate>Wed, 01 Jul 2026 10:00:00 GMT</pubDate>
        <description>Official monetary policy release.</description>
      </item>
    </channel></rss>
    """

    profile = SourceFetcher.profile_for("federal_reserve")
    [document] = SourceFetcher.parse_feed_xml(profile, xml, 10)

    assert document["title"] == "Fed announces rate decision"
    assert document["published_at"] == "2026-07-01T10:00:00Z"
    assert document["trust_tier"] == "T0_OFFICIAL"
    assert document["copyright_mode"] == "official_public_metadata"
    assert document["metadata"]["raw_body_retained"] == false
  end

  test "SEC submissions parser keeps only market-relevant disclosure forms" do
    profile =
      SourceFetcher.profile_for("sec_nvda_filings", %{"symbol" => "NVDA", "cik" => "1045810"})

    payload = %{
      "cik" => "1045810",
      "name" => "NVIDIA CORP",
      "filings" => %{
        "recent" => %{
          "accessionNumber" => ["0001045810-26-000001", "0001045810-26-000002"],
          "form" => ["4", "UPLOAD"],
          "filingDate" => ["2026-06-30", "2026-06-29"],
          "reportDate" => ["2026-06-28", "2026-06-28"],
          "primaryDocument" => ["xslF345X05/wk-form4.xml", "upload.htm"],
          "primaryDocDescription" => ["Statement of changes in beneficial ownership", "Upload"]
        }
      }
    }

    [document] = SourceFetcher.parse_sec_submissions(payload, profile, 10)

    assert document["title"] =~ "NVDA 4"
    assert document["url"] =~ "https://www.sec.gov/Archives/edgar/data/1045810/"
    assert document["published_at"] == "2026-06-30T00:00:00Z"
    assert document["trust_tier"] == "T1_REGULATED_FILING"
    assert document["metadata"]["raw_body_retained"] == false
  end

  test "generated watchlist sources are available to the Elixir runtime" do
    sec_profile = SourceFetcher.profile_for("sec_nvda_filings")
    google_profile = SourceFetcher.profile_for("google_news_NVDA")

    assert sec_profile.feed_url == "https://data.sec.gov/submissions/CIK0001045810.json"
    assert sec_profile.rate_limit_provider_key == "sec_edgar"
    assert google_profile.default_query =~ "NVIDIA Corporation"
    assert google_profile.rate_limit_provider_key == "google_news_rss"
  end

  test "Google News RSS fetch uses bounded query metadata and injected request function" do
    request_fun = fn url, opts ->
      assert url == "https://news.google.com/rss/search"
      assert opts[:params]["q"] == "semiconductor export controls"

      {:ok,
       %{
         status: 200,
         headers: [{"content-type", "application/rss+xml"}],
         body: """
         <rss><channel>
           <item>
             <title>Chip export control update</title>
             <link>https://news.google.com/rss/articles/example</link>
             <pubDate>Wed, 01 Jul 2026 12:00:00 GMT</pubDate>
           </item>
         </channel></rss>
         """
       }}
    end

    assert {:ok, [document], details} =
             SourceFetcher.fetch_documents(
               "google_news_rss",
               %{"query" => "semiconductor export controls", "max_documents" => 5},
               request_fun: request_fun
             )

    assert details.fetch_kind == "google_news_search"
    assert document["title"] == "Chip export control update"
    assert document["discovery_only"] == true
  end
end
