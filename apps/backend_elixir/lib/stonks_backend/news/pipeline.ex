defmodule StonksBackend.News.Pipeline do
  @moduledoc "Metadata-only news normalization, classification, clustering, and scoring."

  alias StonksBackend.{
    News.Scoring,
    News.SourceFetcher,
    Settings,
    Sql,
    TrackedTickers,
    WatchedRegions
  }

  @topic_keywords %{
    "semiconductors" => [
      "semiconductor",
      "chip",
      "ai accelerator",
      "memory",
      "foundry",
      "asml",
      "nvidia"
    ],
    "central_banks" => [
      "central bank",
      "fomc",
      "fed",
      "ecb",
      "boj",
      "bank of korea",
      "copom",
      "rate decision"
    ],
    "rates" => ["interest rate", "rate decision", "yield", "monetary policy"],
    "energy" => ["oil", "brent", "wti", "opec", "eia", "lng", "gas"],
    "geopolitics" => ["war", "sanction", "export control", "strait", "tariff", "geopolitical"],
    "trade_policy" => ["export control", "tariff", "trade restriction", "customs"],
    "public_health" => ["outbreak", "public health", "who", "cdc", "disease", "pandemic"],
    "pandemic" => ["pandemic", "epidemic"],
    "supply_chain" => ["supply chain", "shipment", "logistics", "chokepoint"],
    "space" => ["launch", "rocket", "space", "mission"],
    "quantum" => [
      "quantum",
      "qubit",
      "ion trap",
      "annealing",
      "superconducting",
      "fault-tolerant",
      "quantinuum",
      "d-wave"
    ],
    "filings" => ["form 4", "13d", "sec filing", "edgar", "prospectus"],
    "earnings" => ["earnings", "revenue", "guidance"]
  }

  @stop_words MapSet.new(~w(the a an to of and for in on with at amid after face faces could))

  def read_pages(payload), do: ok_stage("news.read_pages", payload)
  def purge_email_raw(payload), do: ok_stage("news.purge_email_raw", payload)
  def generate_summary(payload), do: skipped_llm_stage("news.generate_summary", payload)
  def translate_summary(payload), do: skipped_llm_stage("news.translate_summary", payload)
  def rebuild_search_index(payload), do: ok_stage("news.rebuild_search_index", payload)
  def backfill_source(payload), do: ok_stage("news.backfill_source", payload)

  def prune_metadata(payload) do
    discovery_days =
      payload
      |> Map.get("discovery_retention_days", Settings.get(:news_discovery_retention_days, 30))
      |> to_int()
      |> max(1)

    metadata_days =
      payload
      |> Map.get("metadata_retention_days", Settings.get(:news_metadata_retention_days, 90))
      |> to_int()
      |> max(discovery_days)

    event_days =
      payload
      |> Map.get("event_retention_days", Settings.get(:news_event_retention_days, 365))
      |> to_int()
      |> max(metadata_days)

    weak_documents_deleted =
      prune_source_documents(
        discovery_days,
        "coalesce(d.metadata->>'discovery_only', 'false') = 'true'"
      )

    metadata_documents_deleted =
      prune_source_documents(
        metadata_days,
        "coalesce(d.metadata->>'discovery_only', 'false') <> 'true'"
      )

    archived_candidate_events = archive_old_candidate_events(event_days)

    {:ok,
     %{
       status: "ready",
       weak_discovery_documents_deleted: weak_documents_deleted,
       metadata_documents_deleted: metadata_documents_deleted,
       candidate_events_archived: archived_candidate_events,
       discovery_retention_days: discovery_days,
       metadata_retention_days: metadata_days,
       event_retention_days: event_days
     }}
  end

  def normalize_documents(payload) do
    rows = news_documents(limit(payload), require_unclassified: false)
    now = now_iso8601()

    touched =
      rows
      |> Enum.reject(&metadata(&1)["news_normalized_at"])
      |> Enum.map(fn row ->
        row_metadata = metadata(row)

        update_document_metadata(
          row["id"],
          %{
            "news_normalized_at" => now,
            "news_publication_note" =>
              row_metadata["news_publication_note"] || "metadata_only_source_document"
          },
          "normalized"
        )
      end)
      |> Enum.count(&(&1 == :ok))

    record_pipeline_health("normalized", %{parsed: length(rows)})

    {:ok, %{status: "ready", documents_seen: length(rows), documents_normalized: touched}}
  end

  def classify_documents(payload) do
    rows = news_documents(limit(payload), require_unclassified: true)
    now = now_iso8601()

    classified =
      rows
      |> Enum.map(fn row ->
        classification = classify_document(document_payload(row))

        update_document_metadata(
          row["id"],
          %{
            "news_classified_at" => now,
            "news_entities" => classification.entities,
            "news_regions" => classification.regions,
            "news_topics" => classification.topics,
            "news_item_kind" => news_item_kind(row),
            "news_claim_level" => news_claim_level(row),
            "news_evidence_match_status" => evidence_match_status(classification)
          },
          "classified"
        )
      end)
      |> Enum.count(&(&1 == :ok))

    record_pipeline_health("classified", %{classified: classified, parsed: length(rows)})

    {:ok, %{status: "ready", documents_seen: length(rows), documents_classified: classified}}
  end

  def cluster_events(payload) do
    rows = classified_news_documents(limit(payload))

    if rows == [] do
      record_pipeline_health("clustered", %{clustered: 0, parsed: 0})

      {:ok, %{status: "ready", documents_seen: 0, clusters_upserted: 0, links_upserted: 0}}
    else
      documents =
        rows
        |> Enum.with_index()
        |> Enum.map(fn {row, index} -> Map.put(document_payload(row), "_row_index", index) end)

      clusters = cluster_documents(documents)

      {clusters_upserted, links_upserted} =
        Enum.reduce(clusters, {0, 0}, fn cluster, {cluster_count, link_count} ->
          cluster_rows = Enum.map(cluster.documents, &Enum.at(rows, &1["_row_index"]))
          event = cluster_event_payload(cluster, cluster_rows)

          case upsert_news_event_cluster(event) do
            :ok ->
              links = upsert_cluster_document_links(event, cluster_rows)
              upsert_event_entities(event.id, event.entities)
              upsert_event_regions(event.id, event.regions)
              upsert_event_topics(event.id, event.topics)
              {cluster_count + 1, link_count + links}

            :error ->
              {cluster_count, link_count}
          end
        end)

      record_pipeline_health("clustered", %{
        clustered: clusters_upserted,
        parsed: length(rows),
        published_or_projected: clusters_upserted
      })

      {:ok,
       %{
         status: "ready",
         documents_seen: length(rows),
         clusters_upserted: clusters_upserted,
         links_upserted: links_upserted
       }}
    end
  end

  def score_events(_payload \\ %{}) do
    rows =
      Sql.all("""
      select c.id,
             array_remove(array_agg(distinct d.metadata->>'trust_tier'), null) as trust_tiers,
             count(
               distinct coalesce(
                 nullif(lower(d.publisher), ''),
                 nullif(lower(d.metadata->>'gdelt_domain'), ''),
                 nullif(lower(regexp_replace(coalesce(d.canonical_url, d.original_url, ''), '^https?://([^/]+).*$', '\\1')), ''),
                 nullif(lower(d.metadata->>'source_key'), ''),
                 ed.document_id::text
               )
             ) as source_count,
             count(distinct ee.entity_key) as entity_count,
             count(distinct er.region_key) as region_count,
             count(distinct et.topic_key) as topic_count
      from news_event_cluster c
      left join news_event_document ed on ed.event_id = c.id
      left join source_document d on d.id = ed.document_id
      left join news_event_entity ee on ee.event_id = c.id
      left join news_event_region er on er.event_id = c.id
      left join news_event_topic et on et.event_id = c.id
      where c.status = 'active'
      group by c.id
      """)

    scored = Enum.count(rows, &score_event_row/1)

    record_pipeline_health("scored", %{published_or_projected: scored})

    {:ok, %{status: "ready", events_scored: scored}}
  end

  def classify_document(document) do
    %{
      entities: classify_entities(document),
      regions: classify_regions(document),
      topics: classify_topics(document)
    }
  end

  defp score_event_row(row) do
    score = Scoring.trust_score(row["trust_tiers"] || [])

    breaking =
      Scoring.breaking_score(%{
        recency_score: 70,
        source_trust_score: score,
        source_velocity_score: min(100, to_int(row["source_count"]) * 20),
        novelty_score: 55,
        affected_entity_importance_score: if(to_int(row["entity_count"]) > 0, do: 70, else: 35),
        topic_severity_score: if(to_int(row["topic_count"]) > 0, do: 70, else: 35),
        cross_region_impact_score: if(to_int(row["region_count"]) > 1, do: 70, else: 30)
      })

    Sql.execute(
      """
      update news_event_cluster
      set trust_score = $1,
          breaking_score = $2,
          source_count = $3,
          updated_at = now()
      where id = $4
      """,
      [score, breaking, to_int(row["source_count"]), row["id"]]
    )

    true
  rescue
    _ -> false
  end

  def classify_entities(document) do
    profiles =
      TrackedTickers.ticker_profiles()
      |> Enum.concat(SourceFetcher.all_profiles() |> Map.values())
      |> Enum.filter(&present?(&1[:symbol]))
      |> Enum.uniq_by(&String.upcase(to_string(&1[:symbol])))

    text = searchable_text(document)
    raw_text = raw_searchable_text(document)
    host = host(document["url"] || document[:url])
    source_profile = SourceFetcher.profile_for(document["source_key"] || document[:source_key])
    source_symbol = if source_profile, do: source_profile[:symbol], else: nil

    profiles
    |> Enum.flat_map(fn profile ->
      symbol = profile[:symbol] |> to_string() |> String.upcase()
      official = official_host?(host, profile)
      source_match = present?(source_symbol) and String.upcase(to_string(source_symbol)) == symbol
      cashtag? = Regex.match?(~r/(?<![A-Z0-9])\$#{Regex.escape(symbol)}(?![A-Z0-9])/i, raw_text)
      bare_ticker? = Regex.match?(~r/(?<![A-Z0-9])#{Regex.escape(symbol)}(?![A-Z0-9])/, raw_text)
      company_match? = Enum.any?(company_terms(profile), &keyword_matches?(text, &1))

      sector_context? =
        Enum.any?(
          List.wrap(profile[:topics]),
          &String.contains?(text, String.downcase(to_string(&1)))
        )

      cond do
        source_match or official or company_match? ->
          [
            %{
              symbol: symbol,
              relationship: "direct_subject",
              confidence: if(company_match?, do: 0.82, else: 0.92),
              reason: direct_subject_reason(source_match, official, company_match?)
            }
          ]

        cashtag? ->
          [%{symbol: symbol, relationship: "direct_subject", confidence: 0.78, reason: "cashtag"}]

        bare_ticker? and sector_context? ->
          [
            %{
              symbol: symbol,
              relationship: "affected_company",
              confidence: 0.68,
              reason: "ticker_with_topic_context"
            }
          ]

        true ->
          []
      end
    end)
  end

  def classify_regions(document) do
    text = searchable_text(document)
    source_region = document["source_region"] || document[:source_region]
    market_region = document["market_region"] || document[:market_region]

    []
    |> maybe_add_region(source_region, "source_region", 0.9)
    |> Enum.concat(keyword_regions(text))
    |> maybe_add_region(market_region, "market_region", 0.86)
    |> dedupe_best_by([:key, :relation])
    |> Enum.sort_by(&{&1.key, &1.relation})
  end

  def classify_topics(document) do
    text = searchable_text(document)

    @topic_keywords
    |> Enum.flat_map(fn {key, keywords} ->
      hits = Enum.count(keywords, &String.contains?(text, &1))

      if hits > 0 do
        [%{key: key, confidence: min(0.98, 0.45 + hits * 0.17)}]
      else
        []
      end
    end)
    |> Enum.sort_by(&(-&1.confidence))
  end

  def cluster_documents(documents) do
    documents
    |> Enum.group_by(&cluster_key/1)
    |> Enum.map(fn {key, rows} ->
      timestamps = rows |> Enum.map(&published_at/1) |> Enum.reject(&is_nil/1)

      %{
        id: "news_" <> (sha1(key) |> String.slice(0, 16)),
        document_count: length(rows),
        documents: rows,
        first_seen_at: timestamp_bound(timestamps, :min),
        last_seen_at: timestamp_bound(timestamps, :max)
      }
    end)
    |> Enum.sort_by(&(-&1.document_count))
  end

  def trust_score(trust_tiers), do: Scoring.trust_score(trust_tiers)

  def breaking_score(parts), do: Scoring.breaking_score(parts)

  def independent_source_count(rows), do: Scoring.independent_source_count(rows)

  defp ok_stage(job_type, payload) do
    {:ok,
     %{
       status: "ready",
       job_type: job_type,
       payload: payload,
       elixir_component: "news_pipeline",
       documents_seen: 0,
       note: "metadata-only stage requires no Elixir body scraping work"
     }}
  end

  defp skipped_llm_stage(job_type, payload) do
    {:ok,
     %{
       status: "skipped",
       job_type: job_type,
       payload: payload,
       elixir_component: "news_pipeline",
       llm_output_written: false,
       reason: "llm_summary_translation_requires_policy_and_prompt_parity"
     }}
  end

  defp news_documents(limit, opts) do
    require_unclassified = Keyword.fetch!(opts, :require_unclassified)

    Sql.all(
      """
      select d.id, d.title, d.canonical_url, d.original_url, d.publisher, d.source_published_at,
             d.fetched_at, d.language, d.status, d.metadata, ds.source_key
      from source_document d
      left join data_source ds on ds.id = d.source_id
      where coalesce(ds.source_key, d.metadata->>'source_key') = any($1)
        and ($2 = false or not (d.metadata ? 'news_classified_at'))
      order by coalesce(d.source_published_at, d.fetched_at, d.created_at) desc
      limit $3
      """,
      [source_keys(), require_unclassified, limit]
    )
  end

  defp classified_news_documents(limit) do
    Sql.all(
      """
      select d.id, d.title, d.canonical_url, d.original_url, d.publisher, d.source_published_at,
             d.fetched_at, d.language, d.status, d.metadata, ds.source_key
      from source_document d
      left join data_source ds on ds.id = d.source_id
      where d.metadata ? 'news_classified_at'
        and coalesce(ds.source_key, d.metadata->>'source_key') = any($1)
      order by coalesce(d.source_published_at, d.fetched_at, d.created_at) desc
      limit $2
      """,
      [source_keys(), limit]
    )
  end

  defp source_keys do
    SourceFetcher.all_profiles()
    |> Map.keys()
    |> Enum.uniq()
  rescue
    _ -> ["gdelt", "google_news_rss", "federal_reserve", "who"]
  end

  defp update_document_metadata(document_id, metadata, status) do
    Sql.execute(
      """
      update source_document
      set metadata = coalesce(metadata, '{}'::jsonb) || $1::text::jsonb,
          status = $2,
          updated_at = now()
      where id = $3
      """,
      [Jason.encode!(metadata), status, document_id]
    )

    :ok
  rescue
    _ -> :error
  end

  defp record_pipeline_health(stage, counters) do
    details =
      %{
        elixir_component: "news_pipeline",
        stage: stage,
        discovery:
          Map.merge(
            %{
              fetched: 0,
              parsed: 0,
              deduped: 0,
              classified: 0,
              clustered: 0,
              published: 0,
              published_or_projected: 0,
              blocked_or_denied: 0
            },
            stringify_counter_keys(counters)
          )
      }

    Sql.execute(
      """
      insert into source_health_status(source_key, status, last_checked_at, details)
      values ($1, 'ready', now(), $2::text::jsonb)
      on conflict (source_key) do update
      set status = excluded.status,
          last_checked_at = excluded.last_checked_at,
          details = excluded.details
      """,
      ["news_pipeline:#{stage}", Jason.encode!(details)]
    )
  rescue
    _ -> :ok
  end

  defp stringify_counter_keys(counters) do
    Map.new(counters, fn {key, value} -> {to_string(key), to_int(value)} end)
  end

  defp prune_source_documents(retention_days, condition_sql) do
    Sql.scalar(
      """
      with deleted as (
        delete from source_document d
        where d.acquisition_mode = 'news_metadata'
          and d.retention_class = 'metadata_only'
          and d.public_allowed = false
          and not exists (
            select 1 from news_event_document ed where ed.document_id = d.id
          )
          and coalesce(d.source_published_at, d.fetched_at, d.created_at) <
            now() - ($1::int * interval '1 day')
          and #{condition_sql}
        returning 1
      )
      select count(*) from deleted
      """,
      [retention_days],
      0
    )
  end

  defp archive_old_candidate_events(retention_days) do
    Sql.scalar(
      """
      with archived as (
        update news_event_cluster
        set status = 'archived',
            updated_at = now()
        where status = 'active'
          and review_state = 'candidate'
          and last_seen_at < now() - ($1::int * interval '1 day')
        returning 1
      )
      select count(*) from archived
      """,
      [retention_days],
      0
    )
  end

  defp document_payload(row) do
    metadata = metadata(row)

    %{
      "id" => to_string(row["id"]),
      "title" => row["title"],
      "url" => row["canonical_url"] || row["original_url"],
      "canonical_url" => row["canonical_url"] || row["original_url"],
      "snippet" => metadata["snippet"] || "",
      "summary" => metadata["summary"] || "",
      "published_at" =>
        metadata["published_at"] || row["source_published_at"] || row["fetched_at"],
      "source_region" => metadata["source_region"],
      "market_region" => metadata["market_region"],
      "event_type" => event_type(metadata["news_topics"] || []),
      "event_region" => first_region_key(metadata["news_regions"] || []),
      "entities" => metadata["news_entities"] || [],
      "source_key" => row["source_key"] || metadata["source_key"]
    }
  end

  defp news_item_kind(row) do
    metadata = metadata(row)
    tier = to_string(metadata["trust_tier"])

    cond do
      metadata["discovery_only"] == true or metadata["discovery_only"] == "true" ->
        "source_discovery"

      String.starts_with?(tier, "T0_") ->
        "official_update"

      String.starts_with?(tier, "T1_") ->
        "filing_update"

      true ->
        "event_candidate"
    end
  end

  defp news_claim_level(row) do
    metadata = metadata(row)
    tier = to_string(metadata["trust_tier"])

    cond do
      metadata["discovery_only"] == true or metadata["discovery_only"] == "true" ->
        "source_only"

      String.starts_with?(tier, "T0_") or String.starts_with?(tier, "T1_") ->
        "clustered_candidate"

      true ->
        "source_only"
    end
  end

  defp evidence_match_status(%{entities: entities}) do
    max_confidence =
      entities
      |> List.wrap()
      |> Enum.map(&to_float(&1[:confidence] || &1["confidence"]))
      |> Enum.max(fn -> 0.0 end)

    cond do
      max_confidence >= 0.75 -> "matched"
      max_confidence > 0 -> "weak_match"
      true -> "unverified"
    end
  end

  defp cluster_event_payload(cluster, cluster_rows) do
    first = List.first(cluster_rows) || %{}
    metadata_rows = Enum.map(cluster_rows, &metadata/1)
    topics = dedupe_metadata_items(metadata_rows, "news_topics", ["key"])
    regions = dedupe_metadata_items(metadata_rows, "news_regions", ["key", "relation"])
    entities = dedupe_metadata_items(metadata_rows, "news_entities", ["symbol", "relationship"])
    trust_tiers = Enum.map(metadata_rows, &(&1["trust_tier"] || "T3_REVIEWED_PUBLIC_SOURCE"))
    score = trust_score(trust_tiers)
    confidence = min(0.9, max(0.35, score / 100))
    independent_sources = independent_source_count(cluster_rows)

    %{
      id: cluster.id,
      canonical_title:
        (first["title"] || "Untitled news event") |> to_string() |> String.slice(0, 500),
      event_type: event_type(topics),
      first_seen_at: cluster.first_seen_at || now_iso8601(),
      last_seen_at: cluster.last_seen_at || now_iso8601(),
      published_at: cluster.last_seen_at || cluster.first_seen_at || now_iso8601(),
      primary_region: primary_region(regions),
      severity: severity(topics),
      confidence: confidence,
      breaking_score:
        breaking_score(%{
          recency_score: 75,
          source_trust_score: score,
          source_velocity_score: min(100, independent_sources * 20),
          novelty_score: 55,
          affected_entity_importance_score: if(entities == [], do: 35, else: 70),
          topic_severity_score: if(topics == [], do: 35, else: 70),
          cross_region_impact_score:
            if(MapSet.size(MapSet.new(Enum.map(regions, & &1.key))) > 1, do: 70, else: 30)
        }),
      trust_score: score,
      novelty_score: 55,
      source_count: independent_sources,
      entities: entities,
      regions: regions,
      topics: topics
    }
  end

  defp upsert_news_event_cluster(event) do
    Sql.execute(
      """
      insert into news_event_cluster(
        id, canonical_title, event_type, first_seen_at, last_seen_at, published_at,
        primary_region, severity, confidence, breaking_score, trust_score, novelty_score,
        source_count, review_state, status
      )
      values (
        $1, $2, $3, $4::text::timestamptz, $5::text::timestamptz, $6::text::timestamptz,
        $7, $8, $9, $10, $11, $12,
        $13, 'candidate', 'active'
      )
      on conflict (id) do update
      set canonical_title = excluded.canonical_title,
          last_seen_at = excluded.last_seen_at,
          confidence = excluded.confidence,
          breaking_score = excluded.breaking_score,
          trust_score = excluded.trust_score,
          source_count = excluded.source_count,
          updated_at = now()
      """,
      [
        event.id,
        event.canonical_title,
        event.event_type,
        event.first_seen_at,
        event.last_seen_at,
        event.published_at,
        event.primary_region,
        event.severity,
        event.confidence,
        event.breaking_score,
        event.trust_score,
        event.novelty_score,
        event.source_count
      ]
    )

    :ok
  rescue
    _ -> :error
  end

  defp upsert_cluster_document_links(event, cluster_rows) do
    Enum.count(cluster_rows, &upsert_cluster_document_link(event, &1))
  end

  defp upsert_cluster_document_link(event, row) do
    metadata = metadata(row)

    Sql.execute(
      """
      insert into news_event_document(event_id, document_id, relationship, confidence, is_primary_source)
      values ($1, $2, 'supporting_source', $3, $4)
      on conflict (event_id, document_id) do update
      set confidence = excluded.confidence,
          is_primary_source = excluded.is_primary_source
      """,
      [event.id, row["id"], event.confidence, primary_source?(metadata)]
    )

    true
  rescue
    _ -> false
  end

  defp upsert_event_entities(event_id, entities) do
    Enum.each(entities, fn entity ->
      if present?(entity.symbol) do
        Sql.execute(
          """
          insert into news_event_entity(event_id, entity_key, entity_type, relationship, confidence)
          values ($1, $2, 'ticker', $3, $4)
          on conflict (event_id, entity_key, relationship) do update
          set confidence = excluded.confidence
          """,
          [
            event_id,
            entity.symbol,
            entity.relationship || "affected_company",
            entity.confidence || 0.5
          ]
        )
      end
    end)
  rescue
    _ -> :ok
  end

  defp upsert_event_regions(event_id, regions) do
    Enum.each(regions, fn region ->
      if present?(region.key) and present?(region.relation) do
        Sql.execute(
          """
          insert into news_event_region(event_id, region_key, relation, confidence)
          values ($1, $2, $3, $4)
          on conflict (event_id, region_key, relation) do update
          set confidence = excluded.confidence
          """,
          [event_id, region.key, region.relation, region.confidence || 0.5]
        )
      end
    end)
  rescue
    _ -> :ok
  end

  defp upsert_event_topics(event_id, topics) do
    Enum.each(topics, fn topic ->
      if present?(topic.key) do
        Sql.execute(
          """
          insert into news_event_topic(event_id, topic_key, confidence)
          values ($1, $2, $3)
          on conflict (event_id, topic_key) do update
          set confidence = excluded.confidence
          """,
          [event_id, topic.key, topic.confidence || 0.5]
        )
      end
    end)
  rescue
    _ -> :ok
  end

  defp keyword_regions(text) do
    Enum.flat_map(region_keyword_entries(), fn {key, keywords} ->
      if Enum.any?(keywords, &keyword_matches?(text, &1)) do
        relation =
          if Enum.any?(
               ["affect", "impact", "supply chain", "exports", "sanctions"],
               &String.contains?(text, &1)
             ),
             do: "affected_region",
             else: "event_region"

        confidence = if relation == "affected_region", do: 0.68, else: 0.72

        [
          %{key: key, relation: relation, confidence: confidence},
          %{key: key, relation: "mentioned_region", confidence: 0.5}
        ]
      else
        []
      end
    end)
  end

  defp region_keyword_entries do
    WatchedRegions.region_keyword_entries()
    |> Enum.map(fn %{key: key, keywords: keywords} ->
      {key, keywords}
    end)
  rescue
    _ -> []
  end

  defp maybe_add_region(regions, value, relation, confidence) do
    value = value |> to_string() |> String.upcase() |> String.trim()

    if value == "" do
      regions
    else
      [%{key: value, relation: relation, confidence: confidence} | regions]
    end
  end

  defp keyword_matches?(text, keyword) do
    clean = keyword |> String.trim() |> String.downcase()
    compact = String.replace(clean, ".", "")

    cond do
      clean == "" ->
        false

      Regex.match?(~r/^[a-z0-9.]+$/, clean) and String.length(compact) <= 4 ->
        Regex.match?(~r/(?<![a-z0-9])#{Regex.escape(clean)}(?![a-z0-9])/, text)

      true ->
        String.contains?(text, clean)
    end
  end

  defp cluster_key(document) do
    title = normalized_title(document["title"] || document[:title] || "")
    event_type = document["event_type"] || document[:event_type] || ""

    region =
      document["event_region"] || document[:event_region] || document["source_region"] ||
        document[:source_region] || ""

    entities = entity_key(document)
    published = published_at(document)
    date_bucket = if published, do: published |> DateTime.to_date() |> Date.to_iso8601(), else: ""

    cond do
      present?(event_type) or present?(region) or present?(entities) ->
        "event:#{String.downcase(to_string(event_type))}|#{String.upcase(to_string(region))}|#{entities}|#{date_bucket}|#{title_signature(title)}"

      present?(
        document["canonical_url"] || document[:canonical_url] || document["url"] || document[:url]
      ) ->
        "url:#{String.downcase(to_string(document["canonical_url"] || document[:canonical_url] || document["url"] || document[:url]))}"

      true ->
        "title:#{title}"
    end
  end

  defp normalized_title(title) do
    ~r/[a-z0-9]+/
    |> Regex.scan(String.downcase(to_string(title)))
    |> List.flatten()
    |> Enum.map(&stem_title_token/1)
    |> Enum.reject(&MapSet.member?(@stop_words, &1))
    |> Enum.join(" ")
    |> String.slice(0, 120)
  end

  defp stem_title_token(token) do
    if String.length(token) > 3 and String.ends_with?(token, "s") do
      String.trim_trailing(token, "s")
    else
      token
    end
  end

  defp title_signature(title) do
    tokens = String.split(title, " ", trim: true)

    if length(tokens) <= 3 do
      title
    else
      tokens |> MapSet.new() |> MapSet.to_list() |> Enum.sort() |> Enum.take(8) |> Enum.join(" ")
    end
  end

  defp entity_key(document) do
    raw_values =
      document["entities"] || document[:entities] || document["affected_tickers"] ||
        document[:affected_tickers] || []

    raw_values
    |> List.wrap()
    |> Enum.map(fn
      value when is_map(value) ->
        value["symbol"] || value[:symbol] || value["entity_key"] || value[:entity_key]

      value ->
        value
    end)
    |> Enum.map(&(to_string(&1) |> String.trim() |> String.upcase()))
    |> Enum.reject(&(&1 == ""))
    |> Enum.uniq()
    |> Enum.sort()
    |> Enum.join(",")
  end

  defp published_at(document) do
    value = document["published_at"] || document[:published_at]

    cond do
      match?(%DateTime{}, value) ->
        value

      match?(%NaiveDateTime{}, value) ->
        DateTime.from_naive!(value, "Etc/UTC")

      is_binary(value) ->
        parse_datetime(value)

      true ->
        nil
    end
  end

  defp parse_datetime(value) do
    value = String.replace(to_string(value), "Z", "+00:00")

    case DateTime.from_iso8601(value) do
      {:ok, datetime, _} ->
        datetime

      _ ->
        case NaiveDateTime.from_iso8601(value) do
          {:ok, naive} -> DateTime.from_naive!(naive, "Etc/UTC")
          _ -> nil
        end
    end
  end

  defp event_type(topics) do
    keys =
      topics
      |> List.wrap()
      |> Enum.map(&((&1["key"] || &1[:key]) |> to_string()))
      |> MapSet.new()

    cond do
      MapSet.member?(keys, "central_banks") or MapSet.member?(keys, "rates") ->
        "central_bank"

      MapSet.member?(keys, "public_health") or MapSet.member?(keys, "pandemic") ->
        "public_health"

      MapSet.member?(keys, "energy") ->
        "energy_supply"

      MapSet.member?(keys, "geopolitics") or MapSet.member?(keys, "trade_policy") ->
        "geopolitical"

      MapSet.member?(keys, "space") ->
        "company_news"

      true ->
        "market_news"
    end
  end

  defp severity(topics) do
    keys =
      topics
      |> Enum.map(&to_string(&1.key))
      |> MapSet.new()

    cond do
      not MapSet.disjoint?(keys, MapSet.new(["public_health", "geopolitics", "energy"])) -> "high"
      not MapSet.disjoint?(keys, MapSet.new(["central_banks", "semiconductors"])) -> "medium"
      true -> "low"
    end
  end

  defp primary_region([region | _]), do: region.key
  defp primary_region(_), do: nil

  defp timestamp_bound([], _direction), do: nil

  defp timestamp_bound(timestamps, :min) do
    timestamps
    |> Enum.min_by(&DateTime.to_unix(&1, :microsecond))
    |> DateTime.to_iso8601()
  end

  defp timestamp_bound(timestamps, :max) do
    timestamps
    |> Enum.max_by(&DateTime.to_unix(&1, :microsecond))
    |> DateTime.to_iso8601()
  end

  defp first_region_key(regions) do
    regions
    |> List.wrap()
    |> Enum.find_value(fn
      region when is_map(region) -> region["key"] || region[:key]
      _ -> nil
    end)
  end

  defp dedupe_metadata_items(rows, key, identity_fields) do
    rows
    |> Enum.flat_map(fn row ->
      row
      |> Map.get(key, [])
      |> List.wrap()
      |> Enum.filter(&is_map/1)
    end)
    |> dedupe_best_by(identity_fields)
  end

  defp dedupe_best_by(items, fields) do
    items
    |> Enum.reduce(%{}, fn item, acc ->
      item = atomize_keys(item)

      identity =
        Enum.map(fields, &(Map.get(item, &1) || Map.get(item, String.to_atom(to_string(&1)))))

      if not Map.has_key?(acc, identity) or
           to_float(item[:confidence]) > to_float(acc[identity][:confidence]) do
        Map.put(acc, identity, item)
      else
        acc
      end
    end)
    |> Map.values()
  end

  defp atomize_keys(map) do
    Map.new(map, fn {key, value} ->
      key =
        if is_atom(key) do
          key
        else
          key |> to_string() |> String.to_atom()
        end

      {key, value}
    end)
  end

  defp metadata(row) do
    case row["metadata"] || row[:metadata] do
      metadata when is_map(metadata) -> metadata
      metadata when is_binary(metadata) -> Jason.decode!(metadata)
      _ -> %{}
    end
  rescue
    _ -> %{}
  end

  defp primary_source?(metadata) do
    tier = to_string(metadata["trust_tier"] || metadata[:trust_tier])
    String.starts_with?(tier, "T0_") or String.starts_with?(tier, "T1_")
  end

  defp official_host?("", _profile), do: false

  defp official_host?(host, profile) do
    domains =
      profile
      |> Map.get(:official_domains, [])
      |> List.wrap()
      |> Enum.map(&(to_string(&1) |> String.downcase()))
      |> Enum.reject(&(&1 == ""))

    symbol = profile[:symbol] |> to_string() |> String.downcase()

    Enum.any?(domains, &(host == &1 or String.ends_with?(host, "." <> &1))) or
      (symbol != "" and String.contains?(host, symbol))
  end

  defp company_terms(profile) do
    [profile[:legal_name], profile[:name] | List.wrap(profile[:aliases])]
    |> Enum.map(&(to_string(&1) |> String.trim()))
    |> Enum.reject(&(String.length(&1) < 3))
    |> Enum.uniq()
  end

  defp direct_subject_reason(true, _official, _company), do: "source_profile"
  defp direct_subject_reason(_source, true, _company), do: "official_domain"
  defp direct_subject_reason(_source, _official, true), do: "company_name_or_alias"
  defp direct_subject_reason(_, _, _), do: "direct_match"

  defp searchable_text(document) do
    document
    |> raw_searchable_text()
    |> String.downcase()
    |> String.replace(~r/[-_]/, " ")
  end

  defp raw_searchable_text(document) do
    ["title", "snippet", "summary", "body"]
    |> Enum.map(&(document[&1] || document[String.to_atom(&1)] || ""))
    |> Enum.join(" ")
  end

  defp host(url) do
    case URI.parse(to_string(url)) do
      %URI{host: host} when is_binary(host) -> String.downcase(host)
      _ -> ""
    end
  end

  defp present?(value), do: String.trim(to_string(value || "")) != ""

  defp limit(payload) do
    payload
    |> Map.get("limit", 500)
    |> to_int()
    |> max(1)
    |> min(5_000)
  end

  defp to_int(value) when is_integer(value), do: value

  defp to_int(value) do
    case Integer.parse(to_string(value)) do
      {integer, _} -> integer
      _ -> 0
    end
  end

  defp to_float(value) when is_float(value), do: value
  defp to_float(value) when is_integer(value), do: value / 1

  defp to_float(value) do
    case Float.parse(to_string(value)) do
      {float, _} -> float
      _ -> 0.0
    end
  end

  defp now_iso8601, do: DateTime.utc_now() |> DateTime.to_iso8601()

  defp sha1(value), do: :crypto.hash(:sha, to_string(value)) |> Base.encode16(case: :lower)
end
