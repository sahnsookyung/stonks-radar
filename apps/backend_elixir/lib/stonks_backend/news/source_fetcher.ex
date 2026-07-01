defmodule StonksBackend.News.SourceFetcher do
  @moduledoc "Metadata-only news source fetcher for configured, bounded source profiles."

  import SweetXml

  alias StonksBackend.Settings

  @sec_news_forms ~w(8-K 6-K 10-K 10-Q DEF 14A SC 13D SC 13G SCHEDULE 13D SCHEDULE 13G 4)

  @profiles %{
    "federal_reserve" => %{
      source_name: "Federal Reserve",
      source_type: "official",
      base_url: "https://www.federalreserve.gov",
      trust_tier: "T0_OFFICIAL",
      region: "USA",
      topics: ["central_banks", "rates", "macro"],
      rate_limit_provider_key: "federal_reserve",
      rate_limit_endpoint_key: "public_pages",
      copyright_mode: "official_public_metadata",
      feed_url: "https://www.federalreserve.gov/feeds/press_monetary.xml",
      fetch_kind: "feed",
      scheduled_fetch: true,
      discovery_only: false
    },
    "who" => %{
      source_name: "World Health Organization",
      source_type: "official",
      base_url: "https://www.who.int",
      trust_tier: "T0_OFFICIAL",
      region: "GLOBAL",
      topics: ["public_health", "pandemic"],
      rate_limit_provider_key: "who",
      rate_limit_endpoint_key: "rss",
      copyright_mode: "official_public_metadata",
      feed_url: "https://www.who.int/rss-feeds/news-english.xml",
      fetch_kind: "feed",
      scheduled_fetch: true,
      discovery_only: false
    },
    "gdelt" => %{
      source_name: "GDELT Doc API",
      source_type: "aggregator",
      base_url: "https://api.gdeltproject.org/api/v2/doc/doc",
      trust_tier: "T4_WEAK_SIGNAL",
      region: "GLOBAL",
      topics: ["stocks", "geopolitics", "energy", "public_health", "supply_chain"],
      rate_limit_provider_key: "gdelt",
      rate_limit_endpoint_key: "doc",
      copyright_mode: "metadata_only",
      fetch_kind: "gdelt_doc",
      default_query:
        "(semiconductor OR central bank OR rates OR sanctions OR outbreak OR energy)",
      scheduled_fetch: true,
      discovery_only: true
    },
    "gdelt_events" => %{
      source_name: "GDELT Event Files",
      source_type: "aggregator",
      base_url: "http://data.gdeltproject.org/gdeltv2/lastupdate.txt",
      trust_tier: "T4_WEAK_SIGNAL",
      region: "GLOBAL",
      topics: ["geopolitics", "energy", "supply_chain", "public_health"],
      rate_limit_provider_key: "gdelt",
      rate_limit_endpoint_key: "bulk_files",
      copyright_mode: "metadata_only",
      fetch_kind: "gdelt_event_file",
      scheduled_fetch: true,
      discovery_only: true
    },
    "gdelt_gkg" => %{
      source_name: "GDELT Global Knowledge Graph Files",
      source_type: "aggregator",
      base_url: "http://data.gdeltproject.org/gdeltv2/lastupdate.txt",
      trust_tier: "T4_WEAK_SIGNAL",
      region: "GLOBAL",
      topics: ["geopolitics", "energy", "supply_chain", "public_health"],
      rate_limit_provider_key: "gdelt",
      rate_limit_endpoint_key: "bulk_files",
      copyright_mode: "metadata_only",
      fetch_kind: "gdelt_gkg_file",
      scheduled_fetch: true,
      discovery_only: true
    },
    "google_news_rss" => %{
      source_name: "Google News RSS",
      source_type: "rss_discovery",
      base_url: "https://news.google.com/rss",
      trust_tier: "T4_WEAK_SIGNAL",
      region: "GLOBAL",
      topics: ["stocks", "geopolitics", "energy", "public_health"],
      rate_limit_provider_key: "google_news_rss",
      rate_limit_endpoint_key: "search",
      copyright_mode: "metadata_only",
      feed_url: "https://news.google.com/rss/search",
      fetch_kind: "google_news_search",
      default_query: "(semiconductor OR central bank OR sanctions OR outbreak OR oil supply)",
      scheduled_fetch: true,
      discovery_only: true
    },
    "sec_edgar" => %{
      source_name: "SEC EDGAR",
      source_type: "regulated_filing",
      base_url: "https://data.sec.gov",
      trust_tier: "T1_REGULATED_FILING",
      region: "USA",
      topics: ["filings", "stocks"],
      rate_limit_provider_key: "sec_edgar",
      rate_limit_endpoint_key: "submissions",
      copyright_mode: "public_filing_metadata",
      fetch_kind: "sec_submissions",
      scheduled_fetch: false,
      discovery_only: false
    }
  }

  def all_profiles do
    Map.merge(watchlist_profiles(), base_profiles())
  end

  def scheduled_profiles do
    all_profiles()
    |> Map.values()
    |> Enum.filter(&Map.get(&1, :scheduled_fetch, false))
    |> Enum.sort_by(& &1.source_key)
  end

  def profile_for(source_key, payload \\ %{}) do
    source_key = normalize_source_key(source_key)
    profiles = all_profiles()

    cond do
      Map.has_key?(profiles, source_key) ->
        profiles[source_key]
        |> Map.put(:source_key, source_key)
        |> merge_payload_profile(payload)

      String.starts_with?(source_key, "sec_") ->
        profiles["sec_edgar"]
        |> Map.merge(%{source_key: source_key, source_name: source_display_name(source_key)})
        |> merge_payload_profile(payload)

      true ->
        nil
    end
  end

  def fetch_documents(source_key, payload, opts \\ []) do
    max_documents = payload |> Map.get("max_documents") |> normalize_int(100) |> max(1)

    with profile when is_map(profile) <- profile_for(source_key, payload),
         {:ok, request} <- build_request(profile, payload, max_documents) do
      request_fun = Keyword.get(opts, :request_fun, &Req.get/2)

      request_opts = [
        params: request.params,
        headers: request.headers,
        receive_timeout: source_timeout_ms()
      ]

      case request_fun.(request.url, request_opts) do
        {:ok, %{status: status, body: body, headers: headers}} when status in 200..299 ->
          documents =
            parse_response(profile, body, headers, request.url, max_documents)
            |> Enum.take(max_documents)

          {:ok, documents, %{status: status, fetch_kind: profile.fetch_kind}}

        {:ok, %{status: status}} ->
          {:error, {:http_status, status}}

        {:error, reason} ->
          {:error, reason}
      end
    else
      nil -> {:error, :unsupported_source}
      {:error, reason} -> {:error, reason}
    end
  end

  defp base_profiles do
    Map.new(@profiles, fn {source_key, profile} ->
      {source_key, Map.put(profile, :source_key, source_key)}
    end)
  end

  defp watchlist_profiles do
    case watchlist_payload() do
      {:ok, %{"entities" => entities}} when is_list(entities) ->
        entities
        |> Enum.flat_map(&watchlist_entity_sources/1)
        |> Enum.reduce(%{}, fn profile, acc ->
          Map.put_new(acc, profile.source_key, profile)
        end)

      _ ->
        %{}
    end
  end

  defp watchlist_payload do
    watchlist_path_candidates()
    |> Enum.find_value(fn
      nil ->
        nil

      path ->
        if File.regular?(path) do
          case File.read(path) do
            {:ok, content} ->
              case Jason.decode(content) do
                {:ok, %{"entities" => entities} = payload} when is_list(entities) ->
                  {:ok, payload}

                _ ->
                  nil
              end

            _ ->
              nil
          end
        end
    end)
    |> case do
      nil -> {:error, :watchlist_missing}
      result -> result
    end
  end

  defp watchlist_path_candidates do
    [
      Settings.get(:news_ticker_watchlist_path),
      app_priv_path("ticker_watchlist.generated.json"),
      app_priv_path("tracked_entities.json"),
      Path.expand(
        "../api/src/frw_api/services/news/ticker_watchlist.generated.json",
        File.cwd!()
      ),
      Path.expand(
        "../../apps/api/src/frw_api/services/news/ticker_watchlist.generated.json",
        File.cwd!()
      ),
      Path.expand("../config/tracked_entities.json", File.cwd!()),
      Path.expand("../../config/tracked_entities.json", File.cwd!())
    ]
    |> Enum.reject(&blank?/1)
  end

  defp app_priv_path(filename) do
    Application.app_dir(:stonks_backend, Path.join(["priv", "news_sources", filename]))
  rescue
    _ -> nil
  end

  defp watchlist_entity_sources(entity) when is_map(entity) do
    explicit_sources =
      Enum.flat_map(Map.get(entity, "sources", []), &source_profile_from_map(&1, entity))

    explicit_keys =
      explicit_sources
      |> Enum.map(& &1.source_key)
      |> MapSet.new()

    default_sec_sources(entity, explicit_keys) ++
      explicit_sources ++
      default_discovery_sources(entity, explicit_keys)
  end

  defp watchlist_entity_sources(_), do: []

  defp source_profile_from_map(source, entity) when is_map(source) do
    with source_key when source_key != "" <- string_value(source["source_key"]),
         source_name when source_name != "" <- string_value(source["source_name"]),
         base_url when base_url != "" <- string_value(source["base_url"]) do
      [
        %{
          source_key: source_key,
          source_name: source_name,
          source_type: string_value(source["source_type"], "rss_discovery"),
          base_url: base_url,
          trust_tier: string_value(source["trust_tier"], "T4_WEAK_SIGNAL"),
          region:
            first_string(source["region_coverage"], string_value(entity["country"], "GLOBAL")),
          topics: string_list(source["topic_coverage"]),
          rate_limit_provider_key: string_value(source["rate_limit_provider_key"], "company_ir"),
          rate_limit_endpoint_key: string_value(source["rate_limit_endpoint_key"], "rss"),
          copyright_mode: string_value(source["copyright_mode"], "metadata_only"),
          feed_url: blank_to_nil(source["feed_url"]),
          fetch_kind: string_value(source["fetch_kind"], "feed"),
          default_query: blank_to_nil(source["default_query"]),
          scheduled_fetch: truthy_value?(Map.get(source, "scheduled_fetch", true)),
          discovery_only: truthy_value?(Map.get(source, "discovery_only", false)),
          symbol: blank_to_nil(entity["symbol"]),
          cik: blank_to_nil(entity["sec_cik"])
        }
      ]
    else
      _ -> []
    end
  end

  defp source_profile_from_map(_, _), do: []

  defp default_sec_sources(entity, explicit_keys) do
    symbol = string_value(entity["symbol"])
    cik = entity["sec_cik"] |> to_string() |> String.replace(~r/\D/, "")
    source_key = "sec_#{source_symbol_key(symbol) |> String.downcase()}_filings"

    cond do
      symbol == "" or cik == "" or MapSet.member?(explicit_keys, source_key) ->
        []

      true ->
        [
          %{
            source_key: source_key,
            source_name: "SEC EDGAR - #{symbol}",
            source_type: "regulated_filing",
            base_url: "https://data.sec.gov",
            trust_tier: "T1_REGULATED_FILING",
            region: "USA",
            topics: ["filings", "stocks"],
            rate_limit_provider_key: "sec_edgar",
            rate_limit_endpoint_key: "submissions",
            copyright_mode: "public_filing_metadata",
            feed_url: sec_feed_url(cik),
            fetch_kind: "sec_submissions",
            scheduled_fetch: true,
            discovery_only: false,
            symbol: symbol,
            cik: cik
          }
        ]
    end
  end

  defp default_discovery_sources(entity, explicit_keys) do
    if Map.get(entity, "default_discovery_sources") == false do
      []
    else
      symbol = string_value(entity["symbol"])
      legal_name = string_value(entity["legal_name"], symbol)
      symbol_key = source_symbol_key(symbol)
      aliases = string_list(entity["aliases"])
      query_terms = [symbol, ~s("#{legal_name}") | Enum.map(aliases, &~s("#{&1}"))]
      query = "(#{Enum.join(Enum.reject(query_terms, &(&1 == "")), " OR ")}) stock news when:7d"

      [
        google_news_profile(symbol, symbol_key, query),
        yahoo_finance_profile(
          symbol,
          symbol_key,
          Map.get(entity, "yahoo_discovery_enabled") != false
        )
      ]
      |> Enum.reject(&is_nil/1)
      |> Enum.reject(&MapSet.member?(explicit_keys, &1.source_key))
    end
  end

  defp google_news_profile("", _symbol_key, _query), do: nil

  defp google_news_profile(symbol, symbol_key, query) do
    %{
      source_key: "google_news_#{symbol_key}",
      source_name: "Google News RSS - #{symbol}",
      source_type: "rss_discovery",
      base_url: "https://news.google.com/rss",
      trust_tier: "T4_WEAK_SIGNAL",
      region: "GLOBAL",
      topics: ["stocks", "filings", "geopolitics"],
      rate_limit_provider_key: "google_news_rss",
      rate_limit_endpoint_key: "search",
      copyright_mode: "metadata_only",
      feed_url: "https://news.google.com/rss/search",
      fetch_kind: "google_news_search",
      default_query: query,
      scheduled_fetch: true,
      discovery_only: true,
      symbol: symbol
    }
  end

  defp yahoo_finance_profile(_symbol, _symbol_key, false), do: nil
  defp yahoo_finance_profile("", _symbol_key, true), do: nil

  defp yahoo_finance_profile(symbol, symbol_key, true) do
    %{
      source_key: "yahoo_finance_#{symbol_key}",
      source_name: "Yahoo Finance RSS - #{symbol}",
      source_type: "rss_discovery",
      base_url: "https://feeds.finance.yahoo.com",
      trust_tier: "T4_WEAK_SIGNAL",
      region: "GLOBAL",
      topics: ["stocks"],
      rate_limit_provider_key: "yahoo_finance_rss",
      rate_limit_endpoint_key: "rss",
      copyright_mode: "metadata_only",
      feed_url:
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=#{URI.encode(symbol)}&region=US&lang=en-US",
      fetch_kind: "feed",
      scheduled_fetch: true,
      discovery_only: true,
      symbol: symbol
    }
  end

  def build_request(%{fetch_kind: "google_news_search"} = profile, payload, _max_documents) do
    query =
      payload
      |> Map.get("query", profile[:default_query] || "financial markets")
      |> to_string()

    {:ok,
     %{
       url: profile.feed_url,
       params: %{"q" => query, "hl" => "en-US", "gl" => "US", "ceid" => "US:en"},
       headers: [{"accept", "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.2"}]
     }}
  end

  def build_request(%{fetch_kind: "sec_submissions"} = profile, payload, _max_documents) do
    feed_url = payload["feed_url"] || profile[:feed_url] || sec_feed_url(payload["cik"])

    if blank?(feed_url) do
      {:error, :sec_cik_or_feed_url_required}
    else
      {:ok,
       %{
         url: feed_url,
         params: %{},
         headers: [
           {"accept", "application/json"},
           {"user-agent",
            Settings.get(:sec_user_agent, "StonksRadar/1.0 research contact=admin@example.com")}
         ]
       }}
    end
  end

  def build_request(profile, _payload, _max_documents) do
    if blank?(profile[:feed_url]) do
      {:error, :feed_url_required}
    else
      {:ok,
       %{
         url: profile.feed_url,
         params: %{},
         headers: [
           {"accept", "application/rss+xml,application/xml,text/xml,text/html;q=0.5,*/*;q=0.2"}
         ]
       }}
    end
  end

  def parse_response(
        %{fetch_kind: "sec_submissions"} = profile,
        body,
        _headers,
        _url,
        max_documents
      ) do
    body
    |> decode_json_body()
    |> parse_sec_submissions(profile, max_documents)
  end

  def parse_response(profile, body, headers, url, max_documents) do
    content_type = header_value(headers, "content-type")
    text = body_to_text(body)

    cond do
      String.contains?(String.downcase(content_type), "html") or
          String.contains?(String.downcase(to_string(profile[:fetch_kind])), "html") ->
        parse_html_index(profile, text, url, max_documents)

      true ->
        parse_feed_xml(profile, text, max_documents)
    end
  end

  def parse_feed_xml(profile, xml, max_documents) do
    rss_items =
      xml
      |> xpath(
        ~x"//item"l,
        title: ~x"./title/text()"s,
        link: ~x"./link/text()"s,
        description: ~x"./description/text()"s,
        published_at: ~x"./pubDate/text()"s,
        guid: ~x"./guid/text()"s
      )

    atom_entries =
      xml
      |> xpath(
        ~x"//*[local-name()='entry']"l,
        title: ~x"./*[local-name()='title']/text()"s,
        link: ~x"./*[local-name()='link'][@rel='alternate']/@href"s,
        fallback_link: ~x"./*[local-name()='link']/@href"s,
        description: ~x"./*[local-name()='summary']/text()"s,
        published_at: ~x"./*[local-name()='published']/text()"s,
        updated_at: ~x"./*[local-name()='updated']/text()"s
      )

    (rss_items ++ atom_entries)
    |> Enum.flat_map(fn row ->
      link = clean_text(row[:link] || row[:fallback_link] || row[:guid])

      build_document(profile, %{
        title: clean_title(row[:title]),
        url: link,
        snippet: clean_text(row[:description]),
        published_at: parse_datetime(row[:published_at] || row[:updated_at])
      })
    end)
    |> Enum.uniq_by(& &1["dedupe_key"])
    |> Enum.take(max_documents)
  rescue
    _ -> []
  end

  def parse_html_index(profile, html, base_url, max_documents) do
    with {:ok, document} <- Floki.parse_document(html) do
      document
      |> Floki.find("a[href]")
      |> Enum.flat_map(fn node ->
        title = node |> Floki.text(sep: " ") |> clean_title()
        href = node |> Floki.attribute("href") |> List.first()

        build_document(profile, %{
          title: title,
          url: absolute_url(href, base_url),
          snippet: "",
          published_at: nil
        })
      end)
      |> Enum.uniq_by(& &1["dedupe_key"])
      |> Enum.take(max_documents)
    else
      _ -> []
    end
  end

  def parse_sec_submissions(payload, profile, max_documents) when is_map(payload) do
    recent = get_in(payload, ["filings", "recent"])

    if is_map(recent) do
      accessions = Map.get(recent, "accessionNumber", [])
      forms = Map.get(recent, "form", [])
      filing_dates = Map.get(recent, "filingDate", [])
      report_dates = Map.get(recent, "reportDate", [])
      primary_documents = Map.get(recent, "primaryDocument", [])
      descriptions = Map.get(recent, "primaryDocDescription", [])
      cik = payload |> Map.get("cik", profile[:cik]) |> to_string()
      entity_name = payload |> Map.get("name", profile[:source_name]) |> to_string()
      symbol = profile[:symbol] || entity_name

      accessions
      |> Enum.with_index()
      |> Enum.flat_map(fn {accession, index} ->
        form = sec_value(forms, index) |> String.upcase()
        primary_document = sec_value(primary_documents, index)
        url = sec_filing_url(cik, accession, primary_document)

        cond do
          form not in @sec_news_forms ->
            []

          blank?(url) ->
            []

          true ->
            filing_date = sec_value(filing_dates, index)
            report_date = sec_value(report_dates, index)
            description = sec_value(descriptions, index) || primary_document

            build_document(profile, %{
              title: clean_title("#{symbol} #{form}: #{description}"),
              url: url,
              snippet:
                Enum.reject(
                  [
                    "SEC #{form} filing",
                    if(blank?(filing_date), do: nil, else: "filed #{filing_date}"),
                    if(blank?(report_date), do: nil, else: "report date #{report_date}"),
                    entity_name
                  ],
                  &blank?/1
                )
                |> Enum.join("; "),
              published_at: parse_datetime(filing_date)
            })
        end
      end)
      |> Enum.take(max_documents)
    else
      []
    end
  end

  def parse_sec_submissions(_payload, _profile, _max_documents), do: []

  defp build_document(_profile, %{title: title, url: url})
       when title in [nil, ""] or url in [nil, ""],
       do: []

  defp build_document(profile, attrs) do
    url = attrs.url |> to_string() |> String.trim()

    if public_http_url?(url) do
      canonical_url = attrs[:canonical_url] || url
      dedupe_key = "#{profile.source_key}:#{sha256(String.downcase(canonical_url))}"

      [
        %{
          "title" => attrs.title,
          "url" => url,
          "canonical_url" => canonical_url,
          "snippet" => attrs[:snippet] || "",
          "published_at" => attrs[:published_at],
          "source_region" => profile[:region],
          "language" => "en",
          "source_key" => profile.source_key,
          "trust_tier" => profile[:trust_tier],
          "copyright_mode" => profile[:copyright_mode],
          "discovery_only" => profile[:discovery_only],
          "dedupe_key" => dedupe_key,
          "metadata" => %{
            "source_name" => profile[:source_name],
            "source_type" => profile[:source_type],
            "topics" => profile[:topics],
            "fetch_kind" => profile[:fetch_kind],
            "raw_body_retained" => false
          }
        }
      ]
    else
      []
    end
  end

  defp merge_payload_profile(profile, payload) do
    profile
    |> put_if_present(:feed_url, payload["feed_url"])
    |> put_if_present(:symbol, payload["symbol"])
    |> put_if_present(:cik, payload["cik"])
  end

  defp put_if_present(profile, _key, value) when value in [nil, ""], do: profile
  defp put_if_present(profile, key, value), do: Map.put(profile, key, to_string(value))

  defp sec_feed_url(value) do
    cik =
      value
      |> to_string()
      |> String.replace(~r/\D/, "")
      |> String.trim()

    if cik == "",
      do: nil,
      else: "https://data.sec.gov/submissions/CIK#{String.pad_leading(cik, 10, "0")}.json"
  end

  defp sec_filing_url(cik, accession, primary_document) do
    cik_digits = cik |> to_string() |> String.replace(~r/\D/, "")
    accession = accession |> to_string() |> String.trim()
    accession_path = String.replace(accession, "-", "")
    primary_document = primary_document |> to_string() |> String.trim()

    if cik_digits == "" or accession_path == "" or primary_document == "" do
      nil
    else
      "https://www.sec.gov/Archives/edgar/data/#{String.to_integer(cik_digits)}/#{accession_path}/#{primary_document}"
    end
  end

  defp sec_value(values, index) when is_list(values),
    do: values |> Enum.at(index, "") |> to_string()

  defp sec_value(_values, _index), do: ""

  defp decode_json_body(body) when is_map(body), do: body

  defp decode_json_body(body) do
    case Jason.decode(body_to_text(body)) do
      {:ok, payload} when is_map(payload) -> payload
      _ -> %{}
    end
  end

  defp body_to_text(body) when is_binary(body), do: body
  defp body_to_text(body), do: Jason.encode!(body)

  defp header_value(headers, header_name) do
    headers
    |> List.wrap()
    |> Enum.find_value("", fn
      {key, value} ->
        if String.downcase(to_string(key)) == header_name,
          do: value |> List.wrap() |> List.first() |> to_string()

      _ ->
        nil
    end)
  end

  defp parse_datetime(nil), do: nil

  defp parse_datetime(value) do
    text = value |> to_string() |> String.trim()

    cond do
      text == "" ->
        nil

      match?({:ok, _, _}, DateTime.from_iso8601(text)) ->
        {:ok, datetime, _} = DateTime.from_iso8601(text)
        DateTime.to_iso8601(datetime)

      match?({:ok, _}, Date.from_iso8601(text)) ->
        {:ok, date} = Date.from_iso8601(text)
        {:ok, datetime} = DateTime.new(date, ~T[00:00:00], "Etc/UTC")
        DateTime.to_iso8601(datetime)

      true ->
        parse_http_datetime(text)
    end
  end

  defp parse_http_datetime(text) do
    case Regex.run(
           ~r/(?:[A-Za-z]{3},\s*)?(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})/,
           text
         ) do
      [_match, day, month, year, hour, minute, second] ->
        with {:ok, month_number} <- month_number(month),
             {year, ""} <- Integer.parse(year),
             {day, ""} <- Integer.parse(day),
             {hour, ""} <- Integer.parse(hour),
             {minute, ""} <- Integer.parse(minute),
             {second, ""} <- Integer.parse(second),
             {:ok, date} <- Date.new(year, month_number, day),
             {:ok, time} <- Time.new(hour, minute, second),
             {:ok, datetime} <- DateTime.new(date, time, "Etc/UTC") do
          DateTime.to_iso8601(datetime)
        else
          _ -> nil
        end

      _ ->
        nil
    end
  end

  defp month_number(month) do
    %{
      "jan" => 1,
      "feb" => 2,
      "mar" => 3,
      "apr" => 4,
      "may" => 5,
      "jun" => 6,
      "jul" => 7,
      "aug" => 8,
      "sep" => 9,
      "oct" => 10,
      "nov" => 11,
      "dec" => 12
    }
    |> Map.fetch(String.downcase(month))
  end

  defp clean_title(value) do
    value
    |> clean_text()
    |> String.replace(~r/<[^>]+>/, " ")
    |> String.replace(~r/\s+/, " ")
    |> String.trim()
    |> then(fn title ->
      if String.length(title) >= 4, do: String.slice(title, 0, 280), else: nil
    end)
  end

  defp clean_text(value) do
    value
    |> to_string()
    |> String.replace(~r/\s+/, " ")
    |> String.trim()
  end

  defp absolute_url(nil, _base_url), do: nil

  defp absolute_url(href, base_url) do
    href = href |> to_string() |> String.trim()

    case URI.parse(href) do
      %URI{scheme: scheme, host: host} when scheme in ["http", "https"] and is_binary(host) ->
        href

      _ ->
        base_url |> URI.parse() |> URI.merge(href) |> URI.to_string()
    end
  rescue
    _ -> nil
  end

  defp public_http_url?(url) do
    case URI.parse(to_string(url)) do
      %URI{scheme: scheme, host: host} when scheme in ["http", "https"] and is_binary(host) ->
        true

      _ ->
        false
    end
  end

  defp source_timeout_ms do
    Settings.get(:source_fetch_timeout_seconds, 10)
    |> normalize_int(10)
    |> max(1)
    |> Kernel.*(1000)
  end

  defp string_value(value, default \\ "")

  defp string_value(value, default) do
    value
    |> to_string()
    |> String.trim()
    |> case do
      "" -> default
      text -> text
    end
  end

  defp blank_to_nil(value) do
    case string_value(value) do
      "" -> nil
      text -> text
    end
  end

  defp string_list(value) when is_list(value) do
    value
    |> Enum.map(&string_value/1)
    |> Enum.reject(&(&1 == ""))
  end

  defp string_list(value) when is_binary(value) do
    value
    |> String.split(",", trim: true)
    |> Enum.map(&String.trim/1)
    |> Enum.reject(&(&1 == ""))
  end

  defp string_list(_), do: []

  defp first_string(value, default) do
    value
    |> string_list()
    |> List.first(default)
  end

  defp truthy_value?(value) when is_binary(value),
    do: String.downcase(String.trim(value)) in ["1", "true", "yes", "on"]

  defp truthy_value?(value), do: value in [true, 1]

  defp source_symbol_key(symbol) do
    symbol
    |> to_string()
    |> String.upcase()
    |> String.replace(~r/[^A-Z0-9]+/, "_")
    |> String.trim("_")
  end

  defp source_display_name(source_key) do
    source_key
    |> to_string()
    |> String.replace(["_", "-"], " ")
    |> String.split(" ", trim: true)
    |> Enum.map_join(" ", &String.capitalize/1)
  end

  defp normalize_source_key(value), do: value |> to_string() |> String.trim()
  defp blank?(value), do: value |> to_string() |> String.trim() == ""

  defp normalize_int(value, _default) when is_integer(value), do: value

  defp normalize_int(value, default) do
    case Integer.parse(to_string(value || default)) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  defp sha256(value) do
    :crypto.hash(:sha256, value)
    |> Base.encode16(case: :lower)
  end
end
