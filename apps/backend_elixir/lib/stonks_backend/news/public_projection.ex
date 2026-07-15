defmodule StonksBackend.News.PublicProjection do
  @moduledoc """
  Builds public, metadata-only news views from stored event clusters.

  It deliberately does not fall back to checked-in snapshot events. Empty or
  failed queries return no events so snapshot availability is explicit.
  """

  alias StonksBackend.{Sql, TrackedTickers, WatchedRegions}
  require Logger

  @default_limit 500
  @published_review_states ~w(approved reviewed published)

  def events(locale \\ "en", opts \\ []) do
    query_fun =
      Keyword.get(opts, :query_fun) ||
        Application.get_env(:stonks_backend, :public_news_query_fun) ||
        (&Sql.all/2)

    limit = opts |> Keyword.get(:limit, @default_limit) |> normalize_limit()
    now = Keyword.get(opts, :now, DateTime.utc_now())

    news_sql()
    |> query_fun.([locale, limit])
    |> List.wrap()
    |> Enum.map(&event_from_row(&1, locale, now))
    |> Enum.reject(&is_nil/1)
    |> Enum.filter(&within_search_window?(&1, now))
    |> deduplicate_events()
  rescue
    _error ->
      Logger.error("Public news projection query failed")
      []
  end

  def project_list(data, object_type, locale \\ "en", opts \\ [])

  def project_list(data, object_type, locale, opts) when is_map(data) do
    projected =
      opts
      |> Keyword.get_lazy(:events, fn -> events(locale, opts) end)
      |> filter_for_object(object_type, data)

    Map.put(data, "events", projected)
  end

  def project_list(data, _object_type, _locale, _opts), do: data

  def detail(event, locale \\ "en") when is_map(event) do
    source_titles =
      event
      |> Map.get("source_links", [])
      |> Enum.map(& &1["title"])
      |> Enum.reject(&blank?/1)

    event
    |> Map.merge(%{
      "one_sentence_summary" => event["summary"],
      "what_happened" => factual_list(event["summary"]),
      "why_it_matters" => [],
      "known_facts" => source_titles,
      "uncertainties" => [unreviewed_notice(event, locale)],
      "conflicting_reports" => [],
      "market_relevance" => %{
        "direction" => "unclear",
        "confidence" => "low",
        "reasoning" => no_directional_conclusion(locale)
      },
      "related_events" => [],
      "methodology" => methodology(locale),
      "disclaimer" => disclaimer(locale)
    })
  end

  defp news_sql do
    """
    select c.id,
           c.canonical_title,
           c.event_type,
           c.first_seen_at,
           c.last_seen_at,
           c.published_at,
           (
             select min(d.source_published_at)
             from news_event_document ed
             join source_document d on d.id = ed.document_id
             where ed.event_id = c.id and d.source_published_at is not null
           ) as earliest_source_published_at,
           (
             select max(d.source_published_at)
             from news_event_document ed
             join source_document d on d.id = ed.document_id
             where ed.event_id = c.id and d.source_published_at is not null
           ) as latest_source_published_at,
           c.primary_region,
           c.severity,
           c.confidence,
           c.breaking_score,
           c.trust_score,
           c.novelty_score,
           c.source_count,
           c.review_state,
           coalesce(
             (
               select s.summary_json
               from news_event_summary s
               where s.event_id = c.id
                 and s.locale = $1
                 and s.status = 'succeeded'
                 and s.review_state in ('approved', 'reviewed', 'published')
                 and s.public_allowed = true
               order by s.created_at desc
               limit 1
             ),
             '{}'::jsonb
           ) as summary_json,
           coalesce(
             (
               select jsonb_agg(
                 jsonb_build_object(
                   'symbol', e.entity_key,
                   'relationship', e.relationship,
                   'confidence', e.confidence
                 ) order by e.confidence desc, e.entity_key
               )
               from news_event_entity e
               where e.event_id = c.id and e.entity_type = 'ticker'
             ),
             '[]'::jsonb
           ) as tickers,
           coalesce(
             (
               select jsonb_agg(
                 jsonb_build_object(
                   'key', r.region_key,
                   'relation', r.relation,
                   'confidence', r.confidence
                 ) order by r.confidence desc, r.region_key
               )
               from news_event_region r
               where r.event_id = c.id
             ),
             '[]'::jsonb
           ) as regions,
           coalesce(
             (
               select jsonb_agg(
                 jsonb_build_object('key', t.topic_key, 'confidence', t.confidence)
                 order by t.confidence desc, t.topic_key
               )
               from news_event_topic t
               where t.event_id = c.id
             ),
             '[]'::jsonb
           ) as topics,
           coalesce(
             (
               select jsonb_agg(
                 jsonb_build_object(
                   'label', coalesce(ds.display_name, d.publisher, 'Public source'),
                   'url', coalesce(d.canonical_url, d.original_url),
                   'source_key', coalesce(ds.source_key, d.publisher, 'public_source'),
                   'policy_version', case
                     when coalesce(d.metadata->>'source_policy_version', '') ~ '^[0-9]+$'
                       then (d.metadata->>'source_policy_version')::integer
                     else 1
                   end,
                   'title', coalesce(d.title, c.canonical_title),
                   'published_at', d.source_published_at,
                   'trust_tier', coalesce(
                     d.metadata->>'trust_tier',
                     d.metadata->'metadata'->>'trust_tier',
                     'T4_WEAK_SIGNAL'
                   ),
                   'is_primary', ed.is_primary_source
                 ) order by ed.is_primary_source desc, d.source_published_at desc nulls last
               )
               from news_event_document ed
               join source_document d on d.id = ed.document_id
               left join data_source ds on ds.id = d.source_id
               where ed.event_id = c.id
                 and d.source_published_at is not null
                 and coalesce(d.canonical_url, d.original_url, '') ~ '^https?://'
             ),
             '[]'::jsonb
           ) as source_links
    from news_event_cluster c
    where c.status = 'active'
      and c.last_seen_at >= now() - interval '30 days'
      and exists (
        select 1
        from news_event_document ed
        join source_document d on d.id = ed.document_id
        where ed.event_id = c.id
          and d.source_published_at is not null
          and coalesce(d.canonical_url, d.original_url, '') ~ '^https?://'
      )
    order by latest_source_published_at desc, c.breaking_score desc, c.id
    limit $2
    """
  end

  defp event_from_row(row, locale, now) when is_map(row) do
    source_links = normalize_source_links(row["source_links"])
    source_published_at = row["latest_source_published_at"]

    if source_links == [] or is_nil(datetime(source_published_at)) or
         not valid_event_id?(row["id"]) or not credible_title?(row["canonical_title"]) do
      nil
    else
      summary_json = ensure_map(row["summary_json"])
      summary = public_summary(summary_json, source_links, locale)
      review_state = to_string(row["review_state"] || "candidate")
      source_count = length(source_links)

      %{
        "id" => to_string(row["id"]),
        "title" => to_string(row["canonical_title"]),
        "summary" => summary,
        "event_type" => to_string(row["event_type"] || "source_linked_news"),
        "item_kind" => item_kind(review_state),
        "claim_level" => claim_level(review_state),
        "evidence_match_status" => evidence_match_status(source_count, review_state),
        "review_state" => public_review_state(review_state),
        "first_seen_at" => iso8601(row["earliest_source_published_at"] || source_published_at),
        "last_seen_at" => iso8601(source_published_at),
        "published_at" => iso8601(source_published_at),
        "source_published_at" => iso8601(source_published_at),
        "observed_at" => iso8601(source_published_at),
        "freshness" => freshness(source_published_at, now),
        "severity" => severity(row["severity"]),
        "confidence" => bounded_float(row["confidence"]),
        "breaking_score" => bounded_int(row["breaking_score"], 0, 100),
        "trust_score" => bounded_int(row["trust_score"], 0, 100),
        "source_count" => max(source_count, 1),
        "tickers" => normalize_tickers(row["tickers"], locale),
        "regions" => normalize_regions(row["regions"], locale),
        "topics" => normalize_topics(row["topics"], locale),
        "market_direction" => "unclear",
        "source_links" => source_links
      }
    end
  end

  defp event_from_row(_row, _locale, _now), do: nil

  defp filter_for_object(events, "news_index", _data), do: events

  defp filter_for_object(events, "news_region", data) do
    key = to_string(data["key"])
    Enum.filter(events, &Enum.any?(&1["regions"], fn region -> region["key"] == key end))
  end

  defp filter_for_object(events, "news_ticker", data) do
    symbol = data["symbol"] |> to_string() |> String.upcase()

    Enum.filter(events, fn event ->
      Enum.any?(event["tickers"], fn ticker -> String.upcase(ticker["symbol"]) == symbol end)
    end)
  end

  defp filter_for_object(events, "news_topic", data) do
    key = to_string(data["key"])
    Enum.filter(events, &Enum.any?(&1["topics"], fn topic -> topic["key"] == key end))
  end

  defp filter_for_object(_events, _object_type, _data), do: []

  defp normalize_source_links(links) do
    links
    |> List.wrap()
    |> Enum.filter(&is_map/1)
    |> Enum.map(fn link ->
      %{
        "label" => to_string(link["label"] || link["source_key"] || "Public source"),
        "url" => to_string(link["url"]),
        "source_key" => to_string(link["source_key"] || "public_source"),
        "policy_version" => max(to_int(link["policy_version"]), 1),
        "title" => to_string(link["title"] || link["label"] || "Source"),
        "published_at" => iso8601(link["published_at"]),
        "trust_tier" => trust_tier(link["trust_tier"]),
        "is_primary" => truthy?(link["is_primary"])
      }
    end)
    |> Enum.filter(&String.starts_with?(&1["url"], ["https://", "http://"]))
    |> Enum.uniq_by(& &1["url"])
  end

  defp normalize_tickers(tickers, locale) do
    names =
      TrackedTickers.ticker_entities()
      |> Map.new(fn entity ->
        symbol = entity["symbol"] || entity["display_symbol"]
        name = entity[if(locale == "ko", do: "name_ko", else: "name_en")] || entity["name_en"]
        {to_string(symbol), to_string(name || symbol)}
      end)

    tickers
    |> List.wrap()
    |> Enum.filter(&is_map/1)
    |> Enum.map(fn ticker ->
      symbol = ticker["symbol"] |> to_string() |> String.upcase()

      %{
        "symbol" => symbol,
        "name" => names[symbol] || symbol,
        "relationship" => ticker_relationship(ticker["relationship"]),
        "confidence" => bounded_float(ticker["confidence"])
      }
    end)
    |> Enum.reject(&blank?(&1["symbol"]))
    |> Enum.uniq_by(& &1["symbol"])
  end

  defp normalize_regions(regions, locale) do
    names =
      WatchedRegions.all()
      |> Map.new(fn region ->
        label =
          get_in(region, ["display_names", locale]) || get_in(region, ["display_names", "en"])

        {to_string(region["key"]), to_string(label || region["key"])}
      end)

    regions
    |> List.wrap()
    |> Enum.filter(&is_map/1)
    |> Enum.map(fn region ->
      key = to_string(region["key"])

      %{
        "key" => key,
        "name" => names[key] || key,
        "relation" => region_relation(region["relation"]),
        "confidence" => bounded_float(region["confidence"])
      }
    end)
    |> Enum.reject(&blank?(&1["key"]))
    |> Enum.uniq_by(&{&1["key"], &1["relation"]})
  end

  defp normalize_topics(topics, locale) do
    topics
    |> List.wrap()
    |> Enum.filter(&is_map/1)
    |> Enum.map(fn topic ->
      key = to_string(topic["key"])

      %{
        "key" => key,
        "label" => topic_label(key, locale),
        "confidence" => bounded_float(topic["confidence"])
      }
    end)
    |> Enum.reject(&blank?(&1["key"]))
    |> Enum.uniq_by(& &1["key"])
  end

  defp public_summary(summary_json, source_links, locale) do
    [
      summary_json["summary"],
      summary_json["one_sentence_summary"],
      summary_json["what_happened"]
    ]
    |> Enum.find_value(fn
      value when is_binary(value) -> if(blank?(value), do: nil, else: value)
      [value | _] when is_binary(value) -> if(blank?(value), do: nil, else: value)
      _ -> nil
    end)
    |> case do
      nil -> source_linked_summary(length(source_links), locale)
      value -> value
    end
  end

  defp item_kind(review_state) when review_state in @published_review_states,
    do: "reviewed_event"

  defp item_kind(_review_state), do: "event_candidate"

  defp public_review_state(review_state) when review_state in @published_review_states,
    do: review_state

  defp public_review_state(_review_state), do: "candidate"

  defp claim_level("published"), do: "published"
  defp claim_level(review_state) when review_state in @published_review_states, do: "reviewed"
  defp claim_level(_review_state), do: "clustered_candidate"

  defp evidence_match_status(source_count, review_state)
       when source_count >= 2 and review_state in @published_review_states,
       do: "matched"

  defp evidence_match_status(source_count, _review_state) when source_count >= 2, do: "weak_match"
  defp evidence_match_status(_source_count, _review_state), do: "unverified"

  defp freshness(value, now) do
    case datetime(value) do
      nil ->
        "unsupported"

      observed_at ->
        age_hours = DateTime.diff(now, observed_at, :hour)

        cond do
          age_hours <= 24 -> "fresh"
          age_hours <= 24 * 7 -> "watch"
          true -> "stale"
        end
    end
  end

  defp within_search_window?(event, now) do
    case datetime(event["source_published_at"]) do
      nil ->
        false

      observed_at ->
        DateTime.compare(observed_at, DateTime.add(now, -30, :day)) != :lt and
          DateTime.compare(observed_at, DateTime.add(now, 5, :minute)) != :gt
    end
  end

  defp event_dedupe_key(event) do
    normalized_title =
      event["title"]
      |> to_string()
      |> String.downcase()
      |> String.replace(~r/[^[:alnum:]]+/u, " ")
      |> String.trim()

    publication_day = event["source_published_at"] |> to_string() |> String.slice(0, 10)
    {normalized_title, publication_day}
  end

  defp deduplicate_events(events) do
    events
    |> Enum.group_by(&event_dedupe_key/1)
    |> Enum.map(fn {_key, candidates} -> Enum.max_by(candidates, &event_quality_rank/1) end)
    |> Enum.sort_by(&event_sort_key/1)
  end

  defp event_sort_key(event) do
    published_unix =
      case datetime(event["source_published_at"]) do
        %DateTime{} = published_at -> DateTime.to_unix(published_at, :microsecond)
        _ -> 0
      end

    {-published_unix, to_string(event["id"])}
  end

  defp event_quality_rank(event) do
    review_rank =
      case event["claim_level"] do
        "published" -> 3
        "reviewed" -> 2
        "clustered_candidate" -> 1
        _ -> 0
      end

    {review_rank, to_int(event["trust_score"]), to_int(event["source_count"])}
  end

  defp credible_title?(value) when is_binary(value) do
    title = String.trim(value)
    normalized = String.downcase(title)
    word_count = ~r/[[:alpha:]]{2,}/u |> Regex.scan(title) |> length()

    String.length(title) >= 12 and word_count >= 3 and
      normalized not in ["log in", "login", "sign in", "contact", "home", "menu", "search"] and
      not Regex.match?(~r/\b(primary document|click here|read more|subscribe now)\b/i, title) and
      not Regex.match?(~r/^[A-Z0-9.\-]{1,12}\s+\d+:\s*$/, title)
  end

  defp credible_title?(_value), do: false

  defp severity(value) when value in ["low", "medium", "high", "critical"], do: value
  defp severity(_value), do: "medium"

  defp trust_tier(value)
       when value in [
              "T0_OFFICIAL",
              "T1_REGULATED_FILING",
              "T2_REPUTABLE_MEDIA",
              "T3_REVIEWED_PUBLIC_SOURCE",
              "T4_WEAK_SIGNAL",
              "T5_UNREVIEWED",
              "T6_BLOCKED"
            ],
       do: value

  defp trust_tier(_value), do: "T4_WEAK_SIGNAL"

  defp ticker_relationship(value)
       when value in [
              "direct_subject",
              "affected_company",
              "competitor",
              "supplier",
              "customer",
              "mentioned_only"
            ],
       do: value

  defp ticker_relationship(_value), do: "mentioned_only"

  defp region_relation(value)
       when value in [
              "source_region",
              "event_region",
              "company_region",
              "affected_region",
              "market_region",
              "mentioned_region"
            ],
       do: value

  defp region_relation(_value), do: "mentioned_region"

  defp topic_label(key, "ko"), do: key |> String.replace("_", " ")

  defp topic_label(key, _locale) do
    key
    |> String.replace("_", " ")
    |> String.split()
    |> Enum.map_join(" ", &String.capitalize/1)
  end

  defp source_linked_summary(count, "ko"), do: "#{count}개의 공개 출처 메타데이터로 묶인 뉴스 이벤트입니다."

  defp source_linked_summary(count, _locale),
    do: "News event clustered from #{count} public source link(s)."

  defp unreviewed_notice(%{"claim_level" => level}, "ko")
       when level in ["reviewed", "published"],
       do: "검토된 출처 메타데이터만 표시됩니다."

  defp unreviewed_notice(%{"claim_level" => level}, _locale)
       when level in ["reviewed", "published"],
       do: "Only reviewed source metadata is displayed."

  defp unreviewed_notice(_event, "ko"), do: "이 이벤트는 자동 군집 후보이며 편집 검토가 완료되지 않았습니다."

  defp unreviewed_notice(_event, _locale),
    do: "This is an automated event candidate and has not completed editorial review."

  defp no_directional_conclusion("ko"), do: "검토된 시장 방향 결론이 없습니다."

  defp no_directional_conclusion(_locale),
    do: "No reviewed market-direction conclusion is available."

  defp methodology("ko"), do: "저장된 공개 출처 메타데이터를 결정론적으로 군집화합니다. 정적 뉴스는 사용하지 않습니다."

  defp methodology(_locale),
    do: "Deterministic clustering of stored public-source metadata; no static news is used."

  defp disclaimer("ko"), do: "정보 제공 목적이며 투자 조언이 아닙니다. 원문 출처를 확인하세요."

  defp disclaimer(_locale),
    do: "For information only, not investment advice. Verify the linked primary sources."

  defp factual_list(value) when is_binary(value), do: if(blank?(value), do: [], else: [value])
  defp factual_list(_value), do: []

  defp iso8601(%DateTime{} = value), do: DateTime.to_iso8601(value)

  defp iso8601(%NaiveDateTime{} = value),
    do: value |> DateTime.from_naive!("Etc/UTC") |> DateTime.to_iso8601()

  defp iso8601(value) when is_binary(value), do: value
  defp iso8601(_value), do: ""

  defp datetime(%DateTime{} = value), do: value
  defp datetime(%NaiveDateTime{} = value), do: DateTime.from_naive!(value, "Etc/UTC")

  defp datetime(value) when is_binary(value) do
    case DateTime.from_iso8601(value) do
      {:ok, parsed, _offset} -> parsed
      _ -> nil
    end
  end

  defp datetime(_value), do: nil

  defp normalize_limit(value), do: value |> to_int() |> max(1) |> min(2_000)

  defp bounded_float(value) when is_float(value), do: value |> max(0.0) |> min(1.0)
  defp bounded_float(%Decimal{} = value), do: value |> Decimal.to_float() |> bounded_float()
  defp bounded_float(value) when is_integer(value), do: bounded_float(value / 1)
  defp bounded_float(_value), do: 0.0

  defp bounded_int(value, min_value, max_value),
    do: value |> to_int() |> max(min_value) |> min(max_value)

  defp to_int(value) when is_integer(value), do: value
  defp to_int(%Decimal{} = value), do: Decimal.to_integer(value)

  defp to_int(value) do
    case Integer.parse(to_string(value)) do
      {integer, _} -> integer
      _ -> 0
    end
  end

  defp truthy?(value), do: value in [true, "true", "1", 1]
  defp valid_event_id?(value), do: Regex.match?(~r/^[A-Za-z0-9_.-]{1,120}$/, to_string(value))
  defp ensure_map(value) when is_map(value), do: value
  defp ensure_map(_value), do: %{}
  defp blank?(value), do: value |> to_string() |> String.trim() == ""
end
