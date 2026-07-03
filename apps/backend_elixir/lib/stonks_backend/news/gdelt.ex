defmodule StonksBackend.News.Gdelt do
  @moduledoc "GDELT discovery query-pack logic ported from the Python news ingestion path."

  alias StonksBackend.{SafeFetch, Sql, TrackedTickers, WatchedRegions}

  @doc_provider_cap 250
  @country_chunk_size 6
  @ticker_chunk_size 5
  @diversified_floor 25
  @doc_api_url "https://api.gdeltproject.org/api/v2/doc/doc"
  @default_doc_timespan "36h"
  @fair_bucket_order [
    "top_gdp_regions",
    "tracked_tickers",
    "top_gdp_regions",
    "strategic_themes",
    "top_gdp_regions",
    "regional_reserve",
    "tracked_tickers",
    "top_gdp_regions",
    "strategic_themes",
    "tracked_tickers"
  ]

  @theme_queries [
    ~s|(markets OR stocks OR energy OR commodities OR rates OR sanctions OR trade)|,
    ~s|(sanctions OR tariff OR "trade war" OR export OR controls OR supply)|,
    ~s|(oil OR gas OR lng OR shipping OR chokepoint OR refinery OR pipeline)|
  ]

  def tracked_country_terms, do: WatchedRegions.tracked_country_terms()

  def tracked_ticker_terms, do: TrackedTickers.gdelt_terms()

  def theme_queries, do: @theme_queries

  def doc_queries(cycle_budget), do: doc_queries("market_watch", cycle_budget, [])
  def doc_queries(pack_name, cycle_budget), do: doc_queries(pack_name, cycle_budget, [])

  def doc_queries(pack_name, cycle_budget, opts) do
    pack_name
    |> doc_query_entries(cycle_budget, opts)
    |> Enum.map(& &1.query)
  end

  def doc_request_params(query, max_records, opts \\ []) do
    max_records =
      max_records
      |> normalize_int(@doc_provider_cap)
      |> max(1)
      |> min(@doc_provider_cap)

    timespan =
      opts
      |> Keyword.get(:timespan, @default_doc_timespan)
      |> normalize_timespan(@default_doc_timespan)

    params = %{
      "query" => query,
      "mode" => "ArtList",
      "format" => "json",
      "maxrecords" => to_string(max_records),
      "sort" => "DateDesc"
    }

    if timespan == "", do: params, else: Map.put(params, "timespan", timespan)
  end

  def records_per_query(max_documents, query_count, provider_cap \\ @doc_provider_cap) do
    max_documents = max(1, normalize_int(max_documents, 1))
    provider_cap = max(1, normalize_int(provider_cap, @doc_provider_cap))

    if query_count <= 0 do
      min(max_documents, provider_cap)
    else
      per_query = div(max_documents + query_count - 1, query_count)
      min(provider_cap, max(@diversified_floor, per_query))
    end
  end

  def query_pack_summary(opts \\ []) do
    pack_name = Keyword.get(opts, :pack_name, "market_watch")
    max_documents = Keyword.get(opts, :max_documents, 100) |> normalize_int(100)
    cycle_budget = Keyword.get(opts, :cycle_budget, 10) |> normalize_int(10)
    cycle_index = Keyword.get(opts, :cycle_index, 0) |> normalize_int(0)

    timespan =
      Keyword.get(opts, :timespan, @default_doc_timespan)
      |> normalize_timespan(@default_doc_timespan)

    provider_cap =
      Keyword.get(opts, :provider_cap, @doc_provider_cap) |> normalize_int(@doc_provider_cap)

    entries = doc_query_entries(pack_name, cycle_budget, cycle_index: cycle_index)
    queries = Enum.map(entries, & &1.query)
    records_per_query = records_per_query(max_documents, length(queries), provider_cap)

    %{
      query_pack: normalize_pack_name(pack_name),
      query_count: length(queries),
      candidate_records_per_query: records_per_query,
      timespan: timespan,
      queries: queries,
      query_buckets:
        Enum.map(entries, &Map.take(&1, [:bucket_name, :bucket_budget, :coverage_window])),
      requests:
        Enum.map(entries, &doc_request_params(&1.query, records_per_query, timespan: timespan))
    }
  end

  def fetch_doc_documents(summary, opts \\ []) do
    endpoint = Keyword.get(opts, :endpoint, @doc_api_url)
    max_documents = Keyword.get(opts, :max_documents, 100) |> normalize_int(100) |> max(1)
    request_fun = Keyword.get(opts, :request_fun, &Req.get/2)
    requests = Map.get(summary, :requests, [])

    {documents, discovery} =
      Enum.reduce_while(requests, {[], discovery_zero()}, fn request, {documents, discovery} ->
        if length(documents) >= max_documents do
          {:halt, {documents, discovery}}
        else
          case request_fun.(endpoint, params: request, headers: [{"accept", "application/json"}]) do
            {:ok, %{status: status, body: body}} when status in 200..299 ->
              {parsed, parse_stats} = parse_doc_payload_with_discovery(body, max_documents * 2)

              merged =
                dedupe_documents(documents ++ parsed)
                |> rank_documents()
                |> Enum.take(max_documents)

              {:cont,
               {merged,
                discovery
                |> Map.update!(:fetched, &(&1 + 1))
                |> Map.update!(:parsed, &(&1 + length(parsed)))
                |> Map.update!(:irrelevant_dropped, &(&1 + parse_stats.irrelevant_dropped))
                |> Map.update!(:no_geo_dropped, &(&1 + parse_stats.no_geo_dropped))
                |> Map.put(:deduped, max(0, discovery.parsed + length(parsed) - length(merged)))
                |> Map.put(:published_or_projected, length(merged))}}

            {:ok, %{status: status}} ->
              {:cont,
               {documents,
                discovery
                |> Map.update!(:blocked_or_denied, &(&1 + 1))
                |> Map.put(:last_status, status)}}

            {:error, _reason} ->
              {:cont, {documents, Map.update!(discovery, :blocked_or_denied, &(&1 + 1))}}
          end
        end
      end)

    {documents, enrichment} = enrich_document_titles(documents, opts)

    discovery =
      discovery
      |> Map.update!(:title_enriched, &(&1 + enrichment.title_enriched))
      |> Map.update!(:blocked_or_denied, &(&1 + enrichment.blocked_or_denied))
      |> Map.put(:title_fallback, fallback_title_count(documents))

    {documents, discovery}
  end

  def parse_doc_payload(%{"articles" => rows}, max_documents) when is_list(rows) do
    {documents, _stats} = parse_doc_payload_with_discovery(%{"articles" => rows}, max_documents)
    documents
  end

  def parse_doc_payload(_payload, _max_documents), do: []

  defp parse_doc_payload_with_discovery(%{"articles" => rows}, max_documents)
       when is_list(rows) do
    {documents, stats} =
      Enum.reduce(rows, {[], %{irrelevant_dropped: 0, no_geo_dropped: 0}}, fn row,
                                                                              {documents, stats} ->
        case doc_row_to_document(row) do
          {:ok, document} ->
            {[document | documents], stats}

          {:drop, :no_geo} ->
            {documents, Map.update!(stats, :no_geo_dropped, &(&1 + 1))}

          {:drop, _reason} ->
            {documents, Map.update!(stats, :irrelevant_dropped, &(&1 + 1))}
        end
      end)

    documents =
      documents
      |> Enum.reverse()
      |> dedupe_documents()
      |> rank_documents()
      |> Enum.take(max_documents)

    {documents, stats}
  end

  defp parse_doc_payload_with_discovery(_payload, _max_documents),
    do: {[], %{irrelevant_dropped: 0, no_geo_dropped: 0}}

  def discovery_zero do
    %{
      fetched: 0,
      parsed: 0,
      deduped: 0,
      title_enriched: 0,
      title_fallback: 0,
      stale_dropped: 0,
      irrelevant_dropped: 0,
      no_geo_dropped: 0,
      blocked_or_denied: 0,
      published_or_projected: 0
    }
  end

  defp doc_query_pack("market_watch"), do: market_watch_pack()
  defp doc_query_pack(_), do: market_watch_pack()

  defp doc_row_to_document(row) when is_map(row) do
    language = row |> Map.get("language", "") |> to_string() |> String.downcase()
    url = row |> Map.get("url", "") |> to_string() |> String.trim()

    cond do
      language not in ["", "english", "en"] ->
        {:drop, :language}

      not public_http_url?(url) ->
        {:drop, :url}

      true ->
        title =
          row
          |> Map.get("title")
          |> clean_title()
          |> Kernel.||(title_from_url_path(url))
          |> Kernel.||(source_report_title(url, row["sourcecountry"]))

        if String.trim(to_string(row["sourcecountry"])) == "" do
          {:drop, :no_geo}
        else
          {:ok,
           %{
             "title" => title,
             "url" => url,
             "canonical_url" => url,
             "snippet" => row["seendate"] || row["domain"] || "",
             "published_at" => gdelt_datetime(row["seendate"]),
             "source_region" => row["sourcecountry"],
             "language" => row["language"],
             "source_key" => "gdelt",
             "trust_tier" => "T4_WEAK_SIGNAL",
             "copyright_mode" => "metadata_only",
             "discovery_only" => true,
             "item_kind" => "source_discovery",
             "claim_level" => "source_only",
             "evidence_match_status" => "unverified",
             "dedupe_key" => "gdelt:doc:" <> sha256(String.downcase(url)),
             "metadata" => %{
               "gdelt_domain" => row["domain"],
               "gdelt_query_source" => "doc_api",
               "gdelt_title_source" =>
                 if(clean_title(row["title"]), do: "doc_api", else: "fallback")
             }
           }}
        end
    end
  end

  defp doc_row_to_document(_), do: {:drop, :malformed}

  defp enrich_document_titles(documents, opts) do
    limit = opts |> Keyword.get(:title_fetch_limit, 0) |> normalize_int(0) |> max(0)

    timeout_seconds =
      opts |> Keyword.get(:title_fetch_timeout_seconds, 8) |> normalize_int(8) |> max(1)

    max_bytes =
      opts |> Keyword.get(:title_fetch_max_bytes, 131_072) |> normalize_int(131_072) |> max(4096)

    per_host_interval =
      opts |> Keyword.get(:title_per_host_interval_seconds, 0) |> normalize_int(0) |> max(0)

    fetch_fun = Keyword.get(opts, :title_fetch_fun, &SafeFetch.fetch_url/2)

    {documents, stats, _seen_hosts, _remaining} =
      Enum.reduce(
        documents,
        {[], %{title_enriched: 0, blocked_or_denied: 0}, %{}, limit},
        fn document, {acc, stats, seen_hosts, remaining} ->
          if remaining <= 0 or not title_enrichment_needed?(document) do
            {[document | acc], stats, seen_hosts, remaining}
          else
            url = document["canonical_url"] || document["url"]
            host = host_for_url(url)
            maybe_wait_for_host(host, seen_hosts, per_host_interval)

            fetch_opts = [
              timeout_seconds: timeout_seconds,
              max_bytes: max_bytes,
              text_max_chars: 512
            ]

            case title_cache_hit(document, opts) do
              {:hit, cached} ->
                {[cached | acc], Map.update!(stats, :title_enriched, &(&1 + 1)),
                 Map.put(seen_hosts, host, true), remaining}

              :miss ->
                fetch_enriched_title(
                  document,
                  url,
                  host,
                  fetch_fun,
                  fetch_opts,
                  acc,
                  stats,
                  seen_hosts,
                  remaining
                )
            end
          end
        end
      )

    {Enum.reverse(documents), stats}
  end

  defp fetch_enriched_title(
         document,
         url,
         host,
         fetch_fun,
         fetch_opts,
         acc,
         stats,
         seen_hosts,
         remaining
       ) do
    case fetch_fun.(url, fetch_opts) do
      {:ok, fetched} ->
        title = clean_title(fetched["title"])

        if title do
          canonical_url = fetched["canonical_url"] || fetched["final_url"] || url

          enriched =
            document
            |> Map.put("title", title)
            |> Map.put("canonical_url", canonical_url)
            |> maybe_put_published_at(fetched["published_at"])
            |> put_title_cache(title, canonical_url, fetched)

          {[enriched | acc], Map.update!(stats, :title_enriched, &(&1 + 1)),
           Map.put(seen_hosts, host, true), remaining - 1}
        else
          blocked = put_title_fetch_failure(document, url, "empty_title")
          {[blocked | acc], stats, Map.put(seen_hosts, host, true), remaining - 1}
        end

      {:error, _reason} ->
        blocked = put_title_fetch_failure(document, url, "blocked_or_denied")

        {[blocked | acc], Map.update!(stats, :blocked_or_denied, &(&1 + 1)),
         Map.put(seen_hosts, host, true), remaining - 1}
    end
  end

  defp title_enrichment_needed?(document) do
    source = get_in(document, ["metadata", "gdelt_title_source"])
    title = document["title"] |> to_string() |> String.downcase()
    source != "doc_api" or String.starts_with?(title, "gdelt ")
  end

  defp title_cache_hit(document, opts) do
    cache_get_fun = Keyword.get(opts, :title_cache_get_fun, &default_title_cache_get/1)

    document
    |> title_cache_key()
    |> cache_get_fun.()
    |> case do
      %{"title" => title} = cache when is_binary(title) and title != "" ->
        canonical_url = cache["canonical_url"] || document["canonical_url"] || document["url"]

        {:hit,
         document
         |> Map.put("title", title)
         |> Map.put("canonical_url", canonical_url)
         |> maybe_put_published_at(cache["published_at"])
         |> put_in(["metadata", "gdelt_title_source"], "persistent_title_cache")
         |> put_in(["metadata", "gdelt_title_cache"], cache)}

      _ ->
        :miss
    end
  end

  defp default_title_cache_get(nil), do: nil

  defp default_title_cache_get(cache_key) do
    Sql.scalar(
      """
      select metadata->'gdelt_title_cache'
      from source_document
      where dedupe_key = $1
        and metadata ? 'gdelt_title_cache'
      order by updated_at desc
      limit 1
      """,
      [cache_key]
    )
  rescue
    _ -> nil
  end

  defp title_cache_key(document) do
    document["dedupe_key"] ||
      "gdelt:doc:" <> sha256(String.downcase(document["canonical_url"] || document["url"] || ""))
  end

  defp put_title_cache(document, title, canonical_url, fetched) do
    cache = %{
      "url_hash" => sha256(String.downcase(canonical_url || document["url"] || "")),
      "title" => title,
      "canonical_url" => canonical_url,
      "source_domain" => fetched["source_domain"] || host_for_url(canonical_url),
      "published_at" => fetched["published_at"],
      "cached_at" => DateTime.utc_now() |> DateTime.truncate(:second) |> DateTime.to_iso8601()
    }

    document
    |> put_in(["metadata", "gdelt_title_source"], "safe_fetch_metadata")
    |> put_in(["metadata", "gdelt_title_cache"], cache)
  end

  defp put_title_fetch_failure(document, url, reason) do
    put_in(document, ["metadata", "gdelt_title_fetch_failure"], %{
      "url_hash" => sha256(String.downcase(url || "")),
      "source_domain" => host_for_url(url),
      "reason" => reason,
      "failed_at" => DateTime.utc_now() |> DateTime.truncate(:second) |> DateTime.to_iso8601()
    })
  end

  defp maybe_put_published_at(document, nil), do: document
  defp maybe_put_published_at(document, ""), do: document

  defp maybe_put_published_at(document, published_at),
    do: Map.put(document, "published_at", published_at)

  defp maybe_wait_for_host(host, seen_hosts, interval_seconds) do
    if host && Map.has_key?(seen_hosts, host) && interval_seconds > 0 do
      Process.sleep(interval_seconds * 1000)
    end
  end

  defp fallback_title_count(documents) do
    Enum.count(documents, fn document ->
      get_in(document, ["metadata", "gdelt_title_source"]) in [
        "fallback",
        "source_report",
        "url_slug"
      ]
    end)
  end

  defp dedupe_documents(documents) do
    documents
    |> Enum.reduce(%{}, fn document, acc ->
      key = document["canonical_url"] || document["url"] || document["dedupe_key"]
      Map.put_new(acc, key, document)
    end)
    |> Map.values()
  end

  defp rank_documents(documents) do
    Enum.sort_by(
      documents,
      fn document ->
        {title_score(document["title"]), document["published_at"] || "",
         document["canonical_url"] || ""}
      end,
      :desc
    )
  end

  defp title_score(title) do
    title = to_string(title)

    cond do
      title == "" -> 0
      String.starts_with?(String.downcase(title), "gdelt") -> 1
      true -> min(String.length(title), 140)
    end
  end

  defp clean_title(value) do
    text =
      value
      |> to_string()
      |> String.replace(~r/<[^>]+>/, " ")
      |> String.replace(~r/\s+/, " ")
      |> String.trim()

    lowered = String.downcase(text)

    blocked =
      lowered in [
        "",
        "access denied",
        "attention required!",
        "403 forbidden",
        "404 not found",
        "just a moment...",
        "service unavailable"
      ] or String.starts_with?(lowered, "gdelt event") or
        String.starts_with?(lowered, "gdelt gkg")

    if blocked, do: nil, else: String.slice(text, 0, 280)
  end

  defp title_from_url_path(url) do
    path =
      case URI.parse(url) do
        %URI{path: path} when is_binary(path) -> path
        _ -> ""
      end

    path
    |> String.split("/", trim: true)
    |> Enum.map(&String.replace(&1, ~r/\.(html?|amp|php|aspx?)$/i, ""))
    |> Enum.map(fn segment ->
      words = segment |> URI.decode() |> String.split(~r/[-_\s]+/, trim: true)
      {length(words), words}
    end)
    |> Enum.filter(fn {count, words} ->
      count >= 3 and Enum.any?(words, &String.match?(&1, ~r/[A-Za-z]/))
    end)
    |> Enum.sort_by(fn {count, words} -> {count, Enum.join(words, " ")} end, :desc)
    |> List.first()
    |> case do
      {_count, words} -> words |> Enum.map_join(" ", &title_word/1) |> clean_title()
      nil -> nil
    end
  end

  defp source_report_title(url, region) do
    source = source_domain_display_name(url)
    subject = region |> to_string() |> String.trim()

    cond do
      source && subject != "" -> "#{source} source report: #{title_phrase(subject)}"
      source -> "#{source} source report"
      subject != "" -> "Source report: #{title_phrase(subject)}"
      true -> "Source-linked market report"
    end
  end

  defp source_domain_display_name(url) do
    host =
      case URI.parse(url) do
        %URI{host: host} when is_binary(host) -> String.downcase(host)
        _ -> ""
      end

    labels =
      host
      |> String.split(".", trim: true)
      |> Enum.reject(&(&1 in ["www", "m", "mobile", "en", "eng", "news"]))
      |> Enum.reject(
        &(&1 in ["com", "co", "net", "org", "eu", "pk", "uk", "jp", "kr", "au", "ca", "in"])
      )

    known = %{
      "aljazeera" => "Al Jazeera",
      "arabnews" => "Arab News",
      "hindustantimes" => "Hindustan Times",
      "rferl" => "Radio Free Europe",
      "radiofreeeurope" => "Radio Free Europe",
      "themoscowtimes" => "The Moscow Times",
      "wsj" => "WSJ"
    }

    case List.last(labels) do
      nil ->
        nil

      label ->
        Map.get(
          known,
          label,
          label |> String.split(~r/[-_]+/, trim: true) |> Enum.map_join(" ", &title_word/1)
        )
    end
  end

  defp public_http_url?(url) do
    case URI.parse(url) do
      %URI{scheme: scheme, host: host} when scheme in ["http", "https"] and is_binary(host) ->
        not (host == "data.gdeltproject.org" or String.ends_with?(url, ".zip"))

      _ ->
        false
    end
  end

  defp gdelt_datetime(nil), do: nil

  defp gdelt_datetime(value) do
    text = to_string(value)

    with <<year::binary-size(4), month::binary-size(2), day::binary-size(2), "T",
           hour::binary-size(2), minute::binary-size(2), second::binary-size(2), "Z">> <- text,
         {:ok, datetime, _} <-
           DateTime.from_iso8601("#{year}-#{month}-#{day}T#{hour}:#{minute}:#{second}Z") do
      DateTime.to_iso8601(datetime)
    else
      _ -> nil
    end
  end

  defp title_phrase(value) do
    value
    |> to_string()
    |> String.split(~r/[\s_\/-]+/, trim: true)
    |> Enum.map_join(" ", &title_word/1)
  end

  defp title_word(word) do
    raw = to_string(word)
    word = String.downcase(raw)

    if String.length(raw) <= 3 and String.upcase(raw) == raw do
      raw
    else
      String.capitalize(word)
    end
  end

  defp sha256(value) do
    :crypto.hash(:sha256, value)
    |> Base.encode16(case: :lower)
  end

  defp doc_query_entries(pack_name, cycle_budget, opts) do
    pack = doc_query_pack(pack_name)
    cycle_budget = normalize_int(cycle_budget, 0)

    cond do
      cycle_budget <= 0 or pack == [] ->
        []

      cycle_budget >= length(pack) ->
        pack

      true ->
        budget = min(cycle_budget, length(pack))
        cycle_index = opts |> Keyword.get(:cycle_index, 0) |> normalize_int(0) |> max(0)
        start = rem(cycle_index * budget, length(pack))

        Enum.map(0..(budget - 1), fn offset ->
          Enum.at(pack, rem(start + offset, length(pack)))
        end)
    end
  end

  defp market_watch_pack do
    top_gdp_queries =
      tracked_region_queries(["top_30_gdp", "high_priority"], [Enum.at(@theme_queries, 0)])

    reserve_queries =
      tracked_region_queries(
        ["rotating_reserve", "smaller_economy"],
        Enum.drop(@theme_queries, 1)
      )

    ticker_queries = tracked_ticker_queries()

    thematic_queries = [
      ~s|(hormuz OR "red sea" OR oil OR lng OR pipeline OR refinery OR shipping)|,
      ~s|(semiconductor OR chip OR "export control" OR BIS OR Taiwan OR Korea OR Japan)|,
      ~s|("AI infrastructure" OR datacenter OR "data center" OR capex OR HBM OR accelerator)|,
      ~s|("central bank" OR rates OR inflation OR treasury OR yen OR dollar)|,
      ~s|(outbreak OR pandemic OR WHO OR avian OR vaccine OR public health)|
    ]

    [
      {"top_gdp_regions", 45, top_gdp_queries, "36h"},
      {"tracked_tickers", 25, ticker_queries, "36h"},
      {"strategic_themes", 20, thematic_queries, "36h"},
      {"regional_reserve", 10, reserve_queries, "36h"}
    ]
    |> Enum.map(fn {bucket_name, bucket_budget, queries, coverage_window} ->
      Enum.map(queries, fn query ->
        %{
          query: query,
          bucket_name: bucket_name,
          bucket_budget: bucket_budget,
          coverage_window: coverage_window
        }
      end)
    end)
    |> fair_interleave_bucket_entries()
  end

  defp tracked_region_queries(groups, theme_queries) do
    terms =
      WatchedRegions.all()
      |> Enum.filter(&(Map.get(&1, "gather_news") != false))
      |> Enum.filter(fn region ->
        region_groups = Map.get(region, "groups", [])
        priority = region |> Map.get("priority", 0) |> normalize_int(0)
        gdp_rank = region |> Map.get("gdp_rank", nil) |> normalize_int(999)

        cond do
          "top_30_gdp" in groups -> gdp_rank <= 30 or priority >= 80
          "high_priority" in groups -> priority >= 80
          "rotating_reserve" in groups -> gdp_rank > 30 and priority < 80
          true -> Enum.any?(groups, &(&1 in region_groups))
        end
      end)
      |> Enum.flat_map(fn region ->
        region
        |> Map.get("gdelt_terms", [])
        |> List.wrap()
        |> Enum.map(&gdelt_term/1)
      end)
      |> Enum.reject(&(&1 == ""))
      |> Enum.uniq()

    chunks = Enum.chunk_every(terms, @country_chunk_size)

    for theme <- theme_queries, chunk <- chunks do
      "(#{Enum.join(chunk, " OR ")}) AND #{theme}"
    end
  end

  defp tracked_ticker_queries do
    tracked_ticker_terms()
    |> Enum.uniq()
    |> Enum.chunk_every(@ticker_chunk_size)
    |> Enum.map(fn chunk ->
      "(#{Enum.join(chunk, " OR ")}) AND (acquisition OR merger OR earnings OR guidance OR contract OR launch OR supply OR export OR filing OR stock)"
    end)
  end

  defp gdelt_term(value) do
    value =
      value
      |> to_string()
      |> String.replace(~r/["]/, " ")
      |> String.replace(~r/\s+/, " ")
      |> String.trim()

    cond do
      value == "" -> ""
      String.contains?(value, " ") -> ~s|"#{value}"|
      true -> value
    end
  end

  defp fair_interleave_bucket_entries(bucket_entries) do
    buckets =
      bucket_entries
      |> List.flatten()
      |> Enum.group_by(& &1.bucket_name)

    do_fair_interleave_bucket_entries(buckets, [])
  end

  defp do_fair_interleave_bucket_entries(buckets, acc) when map_size(buckets) == 0,
    do: Enum.reverse(acc)

  defp do_fair_interleave_bucket_entries(buckets, acc) do
    {buckets, acc} =
      Enum.reduce(@fair_bucket_order, {buckets, acc}, fn bucket_name, {buckets, acc} ->
        case Map.get(buckets, bucket_name, []) do
          [] ->
            {Map.delete(buckets, bucket_name), acc}

          [entry | rest] ->
            {Map.put(buckets, bucket_name, rest), [entry | acc]}
        end
      end)

    buckets =
      buckets
      |> Enum.reject(fn {_name, entries} -> entries == [] end)
      |> Map.new()

    do_fair_interleave_bucket_entries(buckets, acc)
  end

  defp normalize_pack_name(value) do
    name = value |> to_string() |> String.trim()

    if name == "", do: "market_watch", else: name
  end

  defp normalize_int(value, _default) when is_integer(value), do: value

  defp normalize_int(value, default) when is_binary(value) do
    case Integer.parse(String.trim(value)) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  defp normalize_int(_, default), do: default

  defp normalize_timespan(value, default) do
    value = value |> to_string() |> String.trim() |> String.downcase()

    if Regex.match?(~r/^\d+[mhd]$/, value), do: value, else: default
  end

  defp host_for_url(url) do
    case URI.parse(to_string(url)) do
      %URI{host: host} when is_binary(host) -> String.downcase(host)
      _ -> nil
    end
  end
end
