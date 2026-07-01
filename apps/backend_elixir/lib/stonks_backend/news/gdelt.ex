defmodule StonksBackend.News.Gdelt do
  @moduledoc "GDELT discovery query-pack logic ported from the Python news ingestion path."

  @doc_provider_cap 250
  @country_chunk_size 6
  @diversified_floor 25
  @doc_api_url "https://api.gdeltproject.org/api/v2/doc/doc"

  @tracked_country_terms [
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
    "Spain",
    "Indonesia",
    "Turkiye",
    "Turkey",
    ~s("Saudi Arabia"),
    "Netherlands",
    "Switzerland",
    "Poland",
    "Belgium",
    "Argentina",
    "Ireland",
    "Sweden",
    ~s("United Arab Emirates"),
    "UAE",
    "Singapore",
    "Israel",
    "Austria",
    "Thailand",
    "Norway",
    ~s("South Africa")
  ]

  @theme_queries [
    ~s|(markets OR stocks OR energy OR commodities OR rates OR sanctions OR trade)|,
    ~s|(sanctions OR tariff OR "trade war" OR export OR controls OR supply)|,
    ~s|(oil OR gas OR lng OR shipping OR chokepoint OR refinery OR pipeline)|
  ]

  def tracked_country_terms, do: @tracked_country_terms
  def theme_queries, do: @theme_queries

  def doc_queries(cycle_budget), do: doc_queries("market_watch", cycle_budget, [])
  def doc_queries(pack_name, cycle_budget), do: doc_queries(pack_name, cycle_budget, [])

  def doc_queries(pack_name, cycle_budget, opts) do
    pack = doc_query_pack(pack_name)
    cycle_budget = normalize_int(cycle_budget, 0)

    cond do
      cycle_budget <= 0 ->
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

  def doc_request_params(query, max_records) do
    max_records =
      max_records
      |> normalize_int(@doc_provider_cap)
      |> max(1)
      |> min(@doc_provider_cap)

    %{
      "query" => query,
      "mode" => "ArtList",
      "format" => "json",
      "maxrecords" => to_string(max_records),
      "sort" => "DateDesc"
    }
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

    provider_cap =
      Keyword.get(opts, :provider_cap, @doc_provider_cap) |> normalize_int(@doc_provider_cap)

    queries = doc_queries(pack_name, cycle_budget, cycle_index: cycle_index)
    records_per_query = records_per_query(max_documents, length(queries), provider_cap)

    %{
      query_pack: normalize_pack_name(pack_name),
      query_count: length(queries),
      candidate_records_per_query: records_per_query,
      queries: queries,
      requests: Enum.map(queries, &doc_request_params(&1, records_per_query))
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
              parsed = parse_doc_payload(body, max_documents * 2)

              merged =
                dedupe_documents(documents ++ parsed)
                |> rank_documents()
                |> Enum.take(max_documents)

              {:cont,
               {merged,
                discovery
                |> Map.update!(:fetched, &(&1 + 1))
                |> Map.update!(:parsed, &(&1 + length(parsed)))
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

    {documents, discovery}
  end

  def parse_doc_payload(%{"articles" => rows}, max_documents) when is_list(rows) do
    rows
    |> Enum.flat_map(&doc_row_to_document/1)
    |> dedupe_documents()
    |> rank_documents()
    |> Enum.take(max_documents)
  end

  def parse_doc_payload(_payload, _max_documents), do: []

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
        []

      not public_http_url?(url) ->
        []

      true ->
        title =
          row
          |> Map.get("title")
          |> clean_title()
          |> Kernel.||(title_from_url_path(url))
          |> Kernel.||(source_report_title(url, row["sourcecountry"]))

        [
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
            "dedupe_key" => "gdelt:doc:" <> sha256(String.downcase(url)),
            "metadata" => %{
              "gdelt_domain" => row["domain"],
              "gdelt_query_source" => "doc_api",
              "gdelt_title_source" =>
                if(clean_title(row["title"]), do: "doc_api", else: "fallback")
            }
          }
        ]
    end
  end

  defp doc_row_to_document(_), do: []

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

  defp market_watch_pack do
    country_theme_queries([Enum.at(@theme_queries, 0)]) ++
      [
        ~s|(hormuz OR "red sea" OR oil OR lng OR pipeline OR refinery OR shipping)|,
        ~s|(semiconductor OR chip OR "export control" OR BIS OR Taiwan OR Korea OR Japan)|,
        ~s|("AI infrastructure" OR datacenter OR "data center" OR capex OR HBM OR accelerator)|,
        ~s|("central bank" OR rates OR inflation OR treasury OR yen OR dollar)|
      ] ++
      country_theme_queries(Enum.drop(@theme_queries, 1)) ++
      [
        ~s|(sanctions OR tariff OR "trade war" OR blockade OR missile OR conflict)|,
        ~s|(outbreak OR pandemic OR WHO OR avian OR vaccine OR public health)|,
        ~s|(NVDA OR AMD OR MSFT OR AAPL OR TSMC OR Samsung OR ASML OR RKLB OR IONQ OR RGTI OR QBTS OR LUNR OR ASTS OR RDW OR DJT)|
      ]
  end

  defp country_theme_queries(theme_queries) do
    chunks = Enum.chunk_every(@tracked_country_terms, @country_chunk_size)

    for theme <- theme_queries, chunk <- chunks do
      "(#{Enum.join(chunk, " OR ")}) AND #{theme}"
    end
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
end
