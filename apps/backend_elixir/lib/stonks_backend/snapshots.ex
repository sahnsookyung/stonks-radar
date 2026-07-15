defmodule StonksBackend.Snapshots do
  @moduledoc "Snapshot candidate/publish compatibility for the local OCI volume model."

  alias StonksBackend.{EarningsCalendar, Repo, Settings, Sql, TrackedTickers, WatchedRegions}
  alias StonksBackend.Disclosures.PublicProjection, as: DisclosureProjection
  alias StonksBackend.News.PublicProjection
  alias StonksBackend.Snapshots.{BootstrapTemplate, LiveData, PublicGuards, SchemaResolver}

  @manifest_filename "manifest.json"
  @latest_manifest_path Path.join(["latest", @manifest_filename])
  @public_manifest_key "public/latest/manifest.json"
  @schema_dir "packages/schemas/snapshots"
  @json_file_glob "**/*.json"
  @default_publish_max_files 50_000
  @default_publish_max_bytes 2_000_000_000
  @published_version_retention_count 4
  @prohibited_public_object_types ["source_status"]
  @prohibited_public_object_keys ["source_status"]
  @schema_by_object_type %{
    "calendar_upcoming" => "calendar_snapshot.schema.json",
    "correction_log" => "correction_log_snapshot.schema.json",
    "country_region" => "country_region_snapshot.schema.json",
    "fund_portfolio" => "fund_portfolio_snapshot.schema.json",
    "home" => "home_snapshot.schema.json",
    "map_events" => "map_events_snapshot.schema.json",
    "news_event" => "news_event_snapshot.schema.json",
    "news_index" => "news_index_snapshot.schema.json",
    "news_region" => "news_region_snapshot.schema.json",
    "news_ticker" => "news_ticker_snapshot.schema.json",
    "news_topic" => "news_topic_snapshot.schema.json",
    "reference_entity" => "reference_entity_snapshot.schema.json",
    "scenario_basket" => "scenario_basket_snapshot.schema.json",
    "sector_page" => "sector_snapshot.schema.json"
  }
  def published_root, do: Settings.get(:published_snapshot_dir, "apps/web/public/public")
  def artifact_root, do: Settings.get(:snapshot_artifact_dir, "artifacts/snapshots")
  def manifest_path, do: @latest_manifest_path
  def public_manifest_key, do: @public_manifest_key
  def public_manifest_url, do: "/#{@public_manifest_key}"
  def published_manifest_path, do: Path.join(published_root(), @latest_manifest_path)

  def candidate_root(version),
    do: Path.join([artifact_root(), "candidates", "v#{version}", "public"])

  def build_candidate(payload \\ %{}) do
    if copy_published_tree_requested?(payload) do
      build_published_tree_candidate(payload)
    else
      build_template_snapshot_candidate(payload)
    end
  end

  defp build_template_snapshot_candidate(payload) do
    version = next_snapshot_version()
    generated_at = DateTime.utc_now()
    candidate_root = candidate_root(version)

    File.rm_rf!(candidate_root)
    File.mkdir_p!(candidate_root)

    with {:ok, seed_manifest, template_source} <- snapshot_template(),
         {:ok, files, manifest} <-
           write_template_snapshot_tree(
             candidate_root,
             seed_manifest,
             template_source,
             version,
             generated_at
           ),
         :ok <- write_manifest(candidate_root, manifest),
         :ok <- validate_snapshot_tree(candidate_root),
         :ok <-
           record_candidate_rows(candidate_root, version, "candidate", payload["requested_by"]) do
      {:ok,
       %{
         files: files ++ [Path.join(candidate_root, @latest_manifest_path)],
         uploaded: false,
         destination: candidate_root,
         manifest_path: @public_manifest_key,
         snapshot_version: version
       }}
    end
  end

  defp snapshot_template do
    case read_snapshot(published_manifest_path()) do
      {:ok, manifest} ->
        {:ok, manifest, :published}

      {:error, reason} ->
        if File.exists?(published_manifest_path()) do
          {:error, reason}
        else
          {:ok, BootstrapTemplate.manifest(), :bootstrap}
        end
    end
  end

  defp write_template_snapshot_tree(
         candidate_root,
         seed_manifest,
         template_source,
         version,
         generated_at
       ) do
    locales = seed_manifest["locales"] || []

    news_events =
      Map.new(locales, fn locale ->
        {locale, PublicProjection.events(locale, now: generated_at)}
      end)

    manifest = %{
      "current_version" => version,
      "generated_at" => iso8601(generated_at),
      "locales" => locales,
      "objects" => %{}
    }

    context = %{
      corrections: corrections(),
      generated_at: generated_at,
      hard_expires_at: DateTime.add(generated_at, 7, :day),
      news_events: news_events,
      seed_manifest: seed_manifest,
      stale_after: DateTime.add(generated_at, 12, :hour),
      template_source: template_source,
      version: version
    }

    base_result =
      (seed_manifest["objects"] || %{})
      |> Enum.reject(fn {object_key, _locale_paths} ->
        prohibited_public_object_key?(object_key) or
          String.starts_with?(object_key, "news_event_")
      end)
      |> Enum.reduce_while({:ok, [], manifest}, fn {object_key, locale_paths},
                                                   {:ok, files, manifest} ->
        case write_template_locale_snapshots(
               candidate_root,
               object_key,
               locale_paths,
               context,
               files,
               manifest
             ) do
          {:ok, files, manifest} -> {:cont, {:ok, files, manifest}}
          {:error, reason} -> {:halt, {:error, reason}}
        end
      end)

    with {:ok, files, manifest} <- base_result do
      write_live_news_event_snapshots(candidate_root, context, files, manifest)
    end
  end

  defp write_live_news_event_snapshots(candidate_root, context, files, manifest) do
    context.seed_manifest
    |> Map.get("locales", [])
    |> Enum.reduce_while({:ok, files, manifest}, fn locale, {:ok, files, manifest} ->
      context
      |> news_events(locale)
      |> Enum.reduce_while({:ok, files, manifest}, fn event, {:ok, files, manifest} ->
        event_id = to_string(event["id"])
        object_key = "news_event_#{event_id}"

        relative =
          Path.join(["v#{context.version}", locale, "news", "events", "#{event_id}.json"])

        snapshot =
          event_snapshot(event, object_key, locale, context)
          |> LiveData.annotate_availability()

        case write_snapshot(candidate_root, relative, snapshot) do
          {:ok, target} ->
            manifest =
              put_manifest_object_path(manifest, object_key, locale, "public/#{relative}")

            {:cont, {:ok, [target | files], manifest}}

          {:error, reason} ->
            {:halt, {:error, reason}}
        end
      end)
      |> case do
        {:ok, files, manifest} -> {:cont, {:ok, files, manifest}}
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
  end

  defp event_snapshot(event, object_key, locale, context) do
    %{
      "schema_version" => "1.0",
      "min_reader_version" => "1.0",
      "snapshot_version" => context.version,
      "locale" => locale,
      "generated_at" => iso8601(context.generated_at),
      "stale_after" => iso8601(context.stale_after),
      "hard_expires_at" => iso8601(context.hard_expires_at),
      "object_type" => "news_event",
      "object_key" => object_key,
      "source_policy_versions" => event_source_policy_versions(event),
      "data" => PublicProjection.detail(event, locale),
      "warnings" => event_warnings(event, locale),
      "corrections" => context.corrections
    }
  end

  defp event_source_policy_versions(event) do
    event
    |> Map.get("source_links", [])
    |> Enum.map(fn source ->
      %{
        "source_key" => source["source_key"],
        "policy_version" => source["policy_version"] || 1
      }
    end)
    |> Enum.reject(&(to_string(&1["source_key"]) == ""))
    |> Enum.uniq_by(& &1["source_key"])
  end

  defp event_warnings(%{"claim_level" => level}, _locale)
       when level in ["reviewed", "published"],
       do: []

  defp event_warnings(_event, "ko") do
    [
      %{
        "code" => "unreviewed_event_candidate",
        "message" => "자동 군집 후보이며 편집 검토가 완료되지 않았습니다.",
        "severity" => "warning"
      }
    ]
  end

  defp event_warnings(_event, _locale) do
    [
      %{
        "code" => "unreviewed_event_candidate",
        "message" => "Automated cluster candidate; editorial review is not complete.",
        "severity" => "warning"
      }
    ]
  end

  defp write_template_locale_snapshots(
         candidate_root,
         object_key,
         locale_paths,
         context,
         files,
         manifest
       )
       when is_map(locale_paths) do
    Enum.reduce_while(locale_paths, {:ok, files, manifest}, fn {locale, source_path},
                                                               {:ok, files, manifest} ->
      with {:ok, snapshot} <- seed_snapshot(source_path, object_key, locale, context),
           {:ok, relative} <-
             versioned_snapshot_relative_path(context.version, locale, source_path),
           snapshot <- apply_template_runtime_data(snapshot, object_key, locale, context),
           snapshot <- refresh_source_policy_versions(snapshot),
           snapshot <- LiveData.annotate_availability(snapshot),
           {:ok, target} <- write_snapshot(candidate_root, relative, snapshot),
           manifest <-
             put_manifest_object_path(manifest, object_key, locale, "public/#{relative}") do
        {:cont, {:ok, [target | files], manifest}}
      else
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
    |> case do
      {:ok, files, manifest} ->
        {:ok, Enum.reverse(files), manifest}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp write_template_locale_snapshots(
         _candidate_root,
         object_key,
         _locale_paths,
         _context,
         _files,
         _manifest
       ),
       do: {:error, "Snapshot manifest object #{object_key} must map locales to snapshot paths"}

  defp put_manifest_object_path(manifest, object_key, locale, public_path) do
    update_in(manifest, ["objects"], fn objects ->
      objects
      |> ensure_map()
      |> Map.update(object_key, %{locale => public_path}, fn locale_paths ->
        locale_paths
        |> ensure_map()
        |> Map.put(locale, public_path)
      end)
    end)
  end

  defp seed_snapshot(_source_path, object_key, locale, %{template_source: :bootstrap} = context) do
    BootstrapTemplate.snapshot(object_key, locale, context.version, context.generated_at)
  end

  defp seed_snapshot(source_path, _object_key, _locale, context) do
    with {:ok, relative} <- manifest_snapshot_relative_path(source_path),
         seed_path = Path.join(published_root(), relative),
         {:ok, snapshot} <- read_snapshot(seed_path) do
      {:ok,
       snapshot
       |> Map.put("snapshot_version", context.version)
       |> Map.put_new("min_reader_version", "1.0")
       |> Map.put("generated_at", iso8601(context.generated_at))
       |> Map.put("stale_after", iso8601(context.stale_after))
       |> Map.put("hard_expires_at", iso8601(context.hard_expires_at))
       |> Map.put("corrections", context.corrections)
       |> Map.put_new("warnings", [])
       |> Map.put_new("source_policy_versions", [])
       |> PublicGuards.scrub_placeholder_metadata()
       |> LiveData.strip_seed_payload()}
    end
  end

  defp versioned_snapshot_relative_path(version, locale, source_path) do
    with {:ok, source_relative} <- manifest_snapshot_relative_path(source_path),
         {:ok, suffix} <- snapshot_suffix(source_relative, locale) do
      {:ok, Path.join(["v#{version}", locale, suffix])}
    end
  end

  defp snapshot_suffix(source_relative, locale) do
    case Path.split(source_relative) do
      ["v" <> _seed_version, ^locale | suffix] when suffix != [] ->
        {:ok, Path.join(suffix)}

      [^locale | suffix] when suffix != [] ->
        {:ok, Path.join(suffix)}

      parts when parts != [] ->
        {:ok, Path.basename(source_relative)}

      _ ->
        {:error, "Snapshot path #{source_relative} has no writable filename"}
    end
  end

  defp apply_template_runtime_data(
         %{"object_type" => "home"} = snapshot,
         _object_key,
         locale,
         context
       ) do
    update_in(snapshot, ["data"], fn data ->
      data
      |> ensure_map()
      |> maybe_put_existing("generated_label", iso8601(context.generated_at))
      |> update_snapshot_health(context)
      |> enrich_home_news_data(context.generated_at, locale, context)
      |> EarningsCalendar.enrich_home_snapshot_data()
      |> StonksBackend.Shorts.enrich_home_snapshot_data()
      |> DisclosureProjection.enrich_home()
      |> maybe_enrich_yield_curves()
    end)
  end

  defp apply_template_runtime_data(
         %{"object_type" => "correction_log"} = snapshot,
         _object_key,
         _locale,
         context
       ) do
    put_in(snapshot, ["data", "entries"], context.corrections)
  end

  defp apply_template_runtime_data(
         %{"object_type" => object_type} = snapshot,
         _object_key,
         locale,
         context
       )
       when object_type in ["news_index", "news_region", "news_ticker", "news_topic"] do
    update_in(snapshot, ["data"], fn data ->
      data
      |> ensure_map()
      |> PublicProjection.project_list(object_type, locale,
        events: news_events(context, locale),
        now: context.generated_at
      )
      |> enrich_news_list_data(object_type, context.generated_at)
    end)
  end

  defp apply_template_runtime_data(
         %{"object_type" => "map_events"} = snapshot,
         _object_key,
         locale,
         context
       ) do
    update_in(snapshot, ["data"], fn data ->
      data
      |> ensure_map()
      |> enrich_map_news_data(context.generated_at, locale, context)
    end)
  end

  defp apply_template_runtime_data(
         %{"object_type" => "calendar_upcoming"} = snapshot,
         _object_key,
         _locale,
         _context
       ) do
    update_in(snapshot, ["data"], fn data ->
      data
      |> ensure_map()
      |> EarningsCalendar.enrich_snapshot_data()
    end)
  end

  defp apply_template_runtime_data(
         %{"object_type" => "news_event"} = snapshot,
         _object_key,
         _locale,
         context
       ) do
    update_in(snapshot, ["data"], fn data ->
      data
      |> ensure_map()
      |> enrich_news_detail_data(context.generated_at)
    end)
  end

  defp apply_template_runtime_data(
         %{"object_type" => "scenario_basket"} = snapshot,
         _object_key,
         _locale,
         _context
       ) do
    update_in(snapshot, ["data"], fn data ->
      data
      |> ensure_map()
      |> enrich_scenario_news_items()
    end)
  end

  defp apply_template_runtime_data(
         %{"object_type" => "country_region"} = snapshot,
         _object_key,
         locale,
         context
       ) do
    update_in(snapshot, ["data"], fn data ->
      enrich_country_region_live_data(data, locale, context)
    end)
  end

  defp apply_template_runtime_data(
         %{"object_type" => "sector_page"} = snapshot,
         _object_key,
         locale,
         context
       ) do
    update_in(snapshot, ["data"], fn data ->
      data
      |> ensure_map()
      |> enrich_sector_live_data(locale, context)
      |> enrich_ticker_calendar_items()
    end)
  end

  defp apply_template_runtime_data(
         %{"object_type" => "reference_entity"} = snapshot,
         _object_key,
         locale,
         context
       ) do
    update_in(snapshot, ["data"], fn data ->
      data
      |> ensure_map()
      |> enrich_reference_entity_live_data(locale, context)
    end)
  end

  defp apply_template_runtime_data(snapshot, _object_key, _locale, _context), do: snapshot

  defp maybe_enrich_yield_curves(data) do
    case StonksBackend.YieldCurves.enrich_home_snapshot_data(data) do
      {:ok, enriched_data} -> enriched_data
    end
  end

  defp enrich_country_region_live_data(data, locale, context) do
    data = ensure_map(data)
    key = to_string(data["key"])

    events =
      context
      |> news_events(locale)
      |> Enum.filter(fn event -> key in news_event_region_keys(event) end)
      |> filter_news_items("analysis", context.generated_at)

    public_events = news_events_to_map_payload(events, context.generated_at).public_events

    data
    |> Map.put("recent_events", public_events)
    |> put_live_collection_status(public_events)
  end

  defp enrich_sector_live_data(data, locale, context) do
    key = to_string(data["key"])

    events =
      context
      |> news_events(locale)
      |> Enum.filter(fn event -> key in news_event_sector_keys(event) end)
      |> filter_news_items("analysis", context.generated_at)

    public_events = news_events_to_map_payload(events, context.generated_at).public_events

    data
    |> Map.put("sector_news", events)
    |> Map.put("recent_events", public_events)
    |> put_live_collection_status(events)
  end

  defp enrich_reference_entity_live_data(data, locale, context) do
    entity = ensure_map(data["entity"])

    symbol =
      [entity["symbol"], entity["display_symbol"], entity["route_key"]]
      |> Enum.find_value(&non_empty_string/1)
      |> to_string()
      |> String.upcase()

    events =
      context
      |> news_events(locale)
      |> Enum.filter(fn event -> symbol in news_event_ticker_symbols(event) end)
      |> filter_news_items("analysis", context.generated_at)

    data
    |> Map.put("latest_news", events)
    |> Map.put("freshness", collection_freshness(events))
  end

  defp put_live_collection_status(data, []), do: data

  defp put_live_collection_status(data, events) do
    data
    |> Map.put("freshness", collection_freshness(events))
    |> maybe_put_existing("source_strength", "source-linked")
  end

  defp collection_freshness(events) do
    cond do
      Enum.any?(events, &(&1["freshness"] == "fresh")) -> "fresh"
      Enum.any?(events, &(&1["freshness"] == "watch")) -> "watch"
      events != [] -> "stale"
      true -> "unsupported"
    end
  end

  defp enrich_home_news_data(data, generated_at, locale, context) do
    data
    |> update_event_collection("breaking_market_events", "breaking_latest", generated_at, false)
    |> update_alternative_signal_window("breaking_market_news", "breaking_latest", generated_at)
    |> update_in(["breaking_market_map"], fn map ->
      map
      |> ensure_map()
      |> update_event_collection("events", "breaking_latest", generated_at, false)
      |> filter_map_points_for_allowed_events(generated_at)
      |> sanitize_regional_briefs(generated_at)
      |> refresh_breaking_market_map_counts()
    end)
    |> backfill_home_map_news_from_index(locale, context, generated_at, "analysis")
  end

  defp enrich_map_news_data(data, generated_at, locale, context) do
    data
    |> Map.put("events", [])
    |> update_event_collection("breaking_market_events", "search_archive", generated_at, false)
    |> update_in(["breaking_market_map"], fn map ->
      map
      |> ensure_map()
      |> update_event_collection("events", "search_archive", generated_at, false)
      |> filter_map_points_for_allowed_events(generated_at)
      |> sanitize_regional_briefs(generated_at)
      |> refresh_breaking_market_map_counts()
    end)
    |> backfill_map_news_from_index(locale, context, generated_at, "search_archive")
  end

  defp backfill_map_news_from_index(data, locale, context, generated_at, window_kind) do
    news_events = news_index_events(locale, context, generated_at, window_kind)

    case news_events_to_map_payload(news_events, generated_at) do
      %{public_events: [], breaking_events: [], map_points: []} ->
        data

      payload ->
        data
        |> maybe_put_non_empty_list("events", payload.public_events)
        |> maybe_put_non_empty_list("breaking_market_events", payload.breaking_events)
        |> update_in(["breaking_market_map"], fn map ->
          map
          |> ensure_map()
          |> maybe_put_non_empty_list("events", payload.breaking_events)
          |> maybe_put_non_empty_list("map_points", payload.map_points)
          |> maybe_put_existing("generated_at", iso8601(generated_at))
          |> refresh_breaking_market_map_counts()
        end)
        |> refresh_map_filters(payload.public_events, payload.map_points)
    end
  end

  defp backfill_home_map_news_from_index(data, locale, context, generated_at, window_kind) do
    news_events = news_index_events(locale, context, generated_at, window_kind)

    case news_events_to_map_payload(news_events, generated_at) do
      %{breaking_events: [], map_points: []} ->
        data

      payload ->
        data
        |> maybe_put_non_empty_list("top_events", Enum.take(payload.public_events, 6))
        |> maybe_put_non_empty_list("breaking_market_events", payload.breaking_events)
        |> update_in(["breaking_market_map"], fn map ->
          map
          |> ensure_map()
          |> maybe_put_non_empty_list("events", payload.breaking_events)
          |> maybe_put_non_empty_list("map_points", payload.map_points)
          |> maybe_put_existing("generated_at", iso8601(generated_at))
          |> refresh_breaking_market_map_counts()
        end)
        |> restore_home_news_copy(locale, payload.public_events)
    end
  end

  defp restore_home_news_copy(data, _locale, []), do: data

  defp restore_home_news_copy(data, "ko", _events) do
    data
    |> Map.put("headline", "최신 출처 연결 시장 정보")
    |> Map.put("summary", "현재 수집된 공개 출처의 뉴스와 시장 메타데이터입니다.")
  end

  defp restore_home_news_copy(data, _locale, _events) do
    data
    |> Map.put("headline", "Latest source-linked market intelligence")
    |> Map.put("summary", "Current news and market metadata from collected public sources.")
  end

  defp news_index_events(locale, context, generated_at, window_kind) do
    context
    |> news_events(locale)
    |> filter_news_items(window_kind, generated_at)
  end

  defp news_events(context, locale) do
    context
    |> Map.get(:news_events, %{})
    |> Map.get(locale, [])
  end

  defp news_events_to_map_payload(events, generated_at) do
    centroids = map_region_centroids()

    events
    |> List.wrap()
    |> Enum.filter(&is_map/1)
    |> Enum.reduce(%{public_events: [], breaking_events: [], map_points: []}, fn event, acc ->
      points = news_event_map_points(event, generated_at, centroids)

      public_event = public_event_from_news_event(event, points)
      breaking_event = breaking_event_from_news_event(event, points, generated_at)

      case {points, public_event} do
        {[], _public_event} ->
          acc

        {_points, nil} ->
          acc

        {_points, public_event} ->
          %{
            acc
            | public_events: [public_event | acc.public_events],
              breaking_events: maybe_prepend(breaking_event, acc.breaking_events),
              map_points: Enum.reverse(points, acc.map_points)
          }
      end
    end)
    |> then(fn payload ->
      %{
        public_events: Enum.reverse(payload.public_events),
        breaking_events: Enum.reverse(payload.breaking_events),
        map_points: Enum.reverse(payload.map_points)
      }
    end)
  end

  defp public_event_from_news_event(event, [primary_point | _points]) do
    event_id = news_event_id(event)
    timestamp = news_event_source_timestamp(event)

    if event_id == "" or timestamp == "" do
      nil
    else
      %{
        "id" => event_id,
        "title" => to_string(event["title"] || "Source-linked market event"),
        "summary" => to_string(event["summary"] || ""),
        "why_it_matters" => to_string(event["summary"] || ""),
        "occurred_at" => timestamp,
        "published_at" => timestamp,
        "country_region_keys" => news_event_region_keys(event),
        "sector_keys" => news_event_sector_keys(event),
        "event_type" => to_string(event["event_type"] || "source_linked_news"),
        "severity" => severity_value(event["severity"]),
        "confidence" => bounded_float(event["confidence"], 0.5),
        "source_strength" => trust_tier(event),
        "freshness" => freshness_value(event["freshness"]),
        "evidence_count" => source_count(event),
        "latitude" => primary_point["latitude"],
        "longitude" => primary_point["longitude"],
        "affected_objects" => news_event_ticker_symbols(event),
        "source_links" => public_source_links(event),
        "item_kind" => event["item_kind"],
        "claim_level" => event["claim_level"],
        "evidence_match_status" => event["evidence_match_status"],
        "review_state" => review_state(event),
        "correction_status" => "none"
      }
      |> drop_nil_values()
    end
  end

  defp public_event_from_news_event(_event, _points), do: nil

  defp breaking_event_from_news_event(event, points, generated_at) do
    event_id = news_event_id(event)
    timestamp = news_event_source_timestamp(event)
    publishable_claim? = event["claim_level"] in ["reviewed", "published"]

    if event_id == "" or timestamp == "" or not publishable_claim? do
      nil
    else
      %{
        "event_id" => event_id,
        "title" => to_string(event["title"] || "Source-linked market event"),
        "summary" => to_string(event["summary"] || ""),
        "source_url" => primary_source_url(event),
        "source_published_at" => timestamp,
        "observed_at" => news_event_observed_timestamp(event, timestamp),
        "verified_at" => iso8601(generated_at),
        "freshness_confidence" => bounded_float(event["confidence"], 0.5),
        "urgency_score" => bounded_int(event["breaking_score"], 50, 0, 100),
        "severity" => severity_value(event["severity"]),
        "trust_tier" => trust_tier(event),
        "discovery_only" =>
          truthy?(event["discovery_only"]) || event["item_kind"] == "source_discovery",
        "review_state" => review_state(event),
        "citation_ids" => citation_ids(event),
        "retention_class" => "summary_only",
        "geo_points" => points,
        "geo_confidence" => geo_confidence(points, event),
        "score_reason_codes" => score_reason_codes(event),
        "dedupe_key" => event_id,
        "label" => breaking_label(event),
        "tickers" =>
          sanitize_news_refs(event["tickers"], [
            "symbol",
            "name",
            "exchange",
            "relationship",
            "confidence"
          ]),
        "regions" =>
          sanitize_news_refs(event["regions"], ["key", "name", "relation", "confidence"]),
        "topics" => sanitize_news_refs(event["topics"], ["key", "label", "confidence"]),
        "source_count" => source_count(event)
      }
      |> drop_nil_values()
    end
  end

  defp maybe_prepend(nil, items), do: items
  defp maybe_prepend(item, items), do: [item | items]

  defp news_event_map_points(event, generated_at, centroids) do
    event_id = news_event_id(event)
    timestamp = news_event_source_timestamp(event)
    observed_at = news_event_observed_timestamp(event, timestamp)
    source_url = primary_source_url(event)
    reason_codes = score_reason_codes(event)
    source_count = source_count(event)
    severity = severity_value(event["severity"])
    urgency = bounded_int(event["breaking_score"], 50, 0, 100)

    event
    |> Map.get("regions", [])
    |> List.wrap()
    |> Enum.filter(&is_map/1)
    |> best_mappable_regions(centroids)
    |> Enum.map(fn region ->
      key = to_string(region["key"] || "")
      centroid = centroids[key]

      %{
        "point_id" => "#{event_id}:#{key}:#{map_point_relation(region["relation"])}",
        "event_id" => event_id,
        "event_ids" => [event_id],
        "title" => to_string(event["title"] || "Source-linked market event"),
        "summary" => to_string(event["summary"] || ""),
        "area_id" => key,
        "area_key" => key,
        "area_label" => to_string(region["name"] || centroid.label),
        "relation" => map_point_relation(region["relation"]),
        "latitude" => centroid.latitude,
        "longitude" => centroid.longitude,
        "severity" => severity,
        "urgency_score" => urgency,
        "source_published_at" => timestamp,
        "observed_at" => if(observed_at == "", do: iso8601(generated_at), else: observed_at),
        "source_url" => source_url,
        "source_count" => source_count,
        "geo_confidence" =>
          bounded_float(region["confidence"], bounded_float(event["confidence"], 0.5)),
        "area_priority" => centroid.priority,
        "score_reason_codes" => reason_codes,
        "item_kind" => event["item_kind"],
        "claim_level" => event["claim_level"],
        "evidence_match_status" => event["evidence_match_status"],
        "review_state" => review_state(event),
        "trust_tier" => trust_tier(event)
      }
      |> drop_nil_values()
    end)
  end

  defp best_mappable_regions(regions, centroids) do
    regions
    |> Enum.filter(fn region ->
      Map.has_key?(centroids, to_string(region["key"] || ""))
    end)
    |> Enum.group_by(&to_string(&1["key"] || ""))
    |> Enum.map(fn {_key, candidates} ->
      Enum.max_by(candidates, fn region ->
        {region_relation_priority(region["relation"]), bounded_float(region["confidence"], 0.0)}
      end)
    end)
    |> Enum.sort_by(fn region ->
      key = to_string(region["key"] || "")

      {-Map.fetch!(centroids, key).priority, -bounded_float(region["confidence"], 0.0), key}
    end)
  end

  defp map_region_centroids do
    WatchedRegions.map_areas()
    |> Enum.filter(fn area ->
      is_binary(area["key"]) and is_number(area["latitude"]) and
        is_number(area["longitude"])
    end)
    |> Map.new(fn area ->
      {area["key"],
       %{
         label: area["name"] || area["key"],
         latitude: area["latitude"],
         longitude: area["longitude"],
         priority: bounded_int(area["base_market_weight"], 50, 0, 100)
       }}
    end)
  end

  defp region_relation_priority("event_region"), do: 5
  defp region_relation_priority("source_region"), do: 4
  defp region_relation_priority("market_region"), do: 3
  defp region_relation_priority("affected_region"), do: 2
  defp region_relation_priority(_relation), do: 1

  defp map_point_relation("event_region"), do: "event_location"
  defp map_point_relation("source_region"), do: "source_region"
  defp map_point_relation(_relation), do: "affected_market"

  defp maybe_put_non_empty_list(data, key, values) do
    current = Map.get(data, key, [])

    if current == [] and values != [] do
      Map.put(data, key, values)
    else
      data
    end
  end

  defp refresh_map_filters(data, public_events, map_points) do
    update_in(data, ["filters"], fn filters ->
      filters = ensure_map(filters)

      filters
      |> put_sorted_filter(
        "countries_regions",
        map_filter_country_keys(public_events, map_points)
      )
      |> put_sorted_filter("sectors", Enum.flat_map(public_events, &List.wrap(&1["sector_keys"])))
      |> put_sorted_filter("event_types", Enum.map(public_events, & &1["event_type"]))
      |> put_sorted_filter("severities", Enum.map(public_events, & &1["severity"]))
    end)
  end

  defp put_sorted_filter(filters, key, values) do
    merged =
      filters
      |> Map.get(key, [])
      |> List.wrap()
      |> Kernel.++(List.wrap(values))
      |> Enum.map(&to_string/1)
      |> Enum.reject(&(&1 == ""))
      |> Enum.uniq()
      |> Enum.sort()

    Map.put(filters, key, merged)
  end

  defp map_filter_country_keys(public_events, map_points) do
    Enum.flat_map(public_events, &List.wrap(&1["country_region_keys"])) ++
      Enum.map(map_points, & &1["area_key"])
  end

  defp news_event_id(event), do: to_string(event["event_id"] || event["id"] || "")

  defp news_event_source_timestamp(event) do
    [
      event["source_published_at"],
      event["published_at"],
      event["last_seen_at"],
      event["first_seen_at"]
    ]
    |> Enum.find_value(&non_empty_string/1)
    |> to_string()
  end

  defp news_event_observed_timestamp(event, fallback) do
    [
      event["observed_at"],
      event["last_seen_at"],
      event["first_seen_at"],
      fallback
    ]
    |> Enum.find_value(&non_empty_string/1)
    |> to_string()
  end

  defp non_empty_string(value) when is_binary(value) do
    value = String.trim(value)
    if value == "", do: nil, else: value
  end

  defp non_empty_string(_value), do: nil

  defp news_event_region_keys(event) do
    event
    |> Map.get("regions", [])
    |> List.wrap()
    |> Enum.map(&to_string(&1["key"] || ""))
    |> Enum.reject(&(&1 == ""))
    |> Enum.uniq()
  end

  defp news_event_sector_keys(event) do
    event
    |> Map.get("topics", [])
    |> List.wrap()
    |> Enum.map(&topic_sector_key/1)
    |> Enum.reject(&(&1 == ""))
    |> Enum.uniq()
  end

  defp topic_sector_key(%{"key" => "energy"}), do: "oil-energy"
  defp topic_sector_key(%{"key" => "semiconductors"}), do: "semiconductors"
  defp topic_sector_key(%{"key" => "space"}), do: "space"
  defp topic_sector_key(%{"key" => "quantum"}), do: "quantum"
  defp topic_sector_key(%{"key" => "big_tech"}), do: "big-tech"
  defp topic_sector_key(%{"key" => key}), do: to_string(key)
  defp topic_sector_key(_topic), do: ""

  defp news_event_ticker_symbols(event) do
    event
    |> Map.get("tickers", [])
    |> List.wrap()
    |> Enum.map(&to_string(&1["symbol"] || ""))
    |> Enum.reject(&(&1 == ""))
    |> Enum.uniq()
  end

  defp public_source_links(event) do
    event
    |> Map.get("source_links", [])
    |> List.wrap()
    |> Enum.filter(&is_map/1)
    |> Enum.map(fn link ->
      link
      |> Map.take(["label", "evidence_id", "url", "source_key", "policy_version"])
      |> Map.put_new("label", to_string(link["title"] || link["source_key"] || "Source"))
      |> Map.put_new("source_key", to_string(link["source_key"] || "public_source"))
      |> Map.put_new("policy_version", to_int(link["policy_version"], 1))
    end)
    |> Enum.filter(&(is_binary(&1["url"]) and String.trim(&1["url"]) != ""))
  end

  defp primary_source_url(event) do
    event
    |> Map.get("source_links", [])
    |> List.wrap()
    |> Enum.find_value(fn link ->
      if is_map(link), do: non_empty_string(link["url"]), else: nil
    end)
  end

  defp citation_ids(event) do
    event
    |> Map.get("source_links", [])
    |> List.wrap()
    |> Enum.filter(&is_map/1)
    |> Enum.map(&to_string(&1["evidence_id"] || ""))
    |> Enum.reject(&(&1 == ""))
    |> Enum.uniq()
  end

  defp trust_tier(%{"trust_tier" => tier}) when is_binary(tier), do: news_trust_tier(tier)

  defp trust_tier(event) do
    event
    |> Map.get("source_links", [])
    |> List.wrap()
    |> Enum.filter(&is_map/1)
    |> Enum.map(&news_trust_tier(&1["trust_tier"]))
    |> Enum.min_by(&trust_tier_rank/1, fn -> "T3_REVIEWED_PUBLIC_SOURCE" end)
  end

  defp news_trust_tier(tier)
       when tier in [
              "T0_OFFICIAL",
              "T1_REGULATED_FILING",
              "T2_REPUTABLE_MEDIA",
              "T3_REVIEWED_PUBLIC_SOURCE",
              "T4_WEAK_SIGNAL",
              "T5_UNREVIEWED",
              "T6_BLOCKED"
            ],
       do: tier

  defp news_trust_tier(_tier), do: "T3_REVIEWED_PUBLIC_SOURCE"

  defp trust_tier_rank("T0_OFFICIAL"), do: 0
  defp trust_tier_rank("T1_REGULATED_FILING"), do: 1
  defp trust_tier_rank("T2_REPUTABLE_MEDIA"), do: 2
  defp trust_tier_rank("T3_REVIEWED_PUBLIC_SOURCE"), do: 3
  defp trust_tier_rank("T4_WEAK_SIGNAL"), do: 4
  defp trust_tier_rank("T5_UNREVIEWED"), do: 5
  defp trust_tier_rank("T6_BLOCKED"), do: 6
  defp trust_tier_rank(_tier), do: 7

  defp review_state(%{"claim_level" => "published"}), do: "published"
  defp review_state(%{"claim_level" => "reviewed"}), do: "reviewed"

  defp review_state(%{"claim_level" => level})
       when level in ["clustered_candidate", "source_only"], do: "candidate"

  defp review_state(%{"review_state" => state})
       when state in ["candidate", "approved", "reviewed", "published"], do: state

  defp review_state(_event), do: "candidate"

  defp breaking_label(%{"freshness" => "stale"}), do: "stale"

  defp breaking_label(%{"breaking_score" => score}) when is_integer(score) and score >= 80,
    do: "breaking"

  defp breaking_label(%{"breaking_score" => score}) when is_integer(score) and score >= 60,
    do: "developing"

  defp breaking_label(_event), do: "latest"

  defp score_reason_codes(event) do
    base = ["source_linked_news", "region_mapped"]
    source_code = if source_count(event) >= 2, do: ["multi_source"], else: []
    trust_code = if trust_tier_rank(trust_tier(event)) <= 1, do: ["high_trust_source"], else: []
    Enum.uniq(base ++ source_code ++ trust_code)
  end

  defp sanitize_news_refs(values, allowed_keys) do
    values
    |> List.wrap()
    |> Enum.filter(&is_map/1)
    |> Enum.map(&Map.take(&1, allowed_keys))
  end

  defp source_count(event),
    do: bounded_int(event["source_count"], length(public_source_links(event)), 0, 10_000)

  defp geo_confidence(points, event) do
    points
    |> Enum.map(&bounded_float(&1["geo_confidence"], 0.0))
    |> Enum.max(fn -> bounded_float(event["confidence"], 0.5) end)
  end

  defp severity_value(value) when value in ["low", "medium", "high", "critical"], do: value
  defp severity_value(_value), do: "medium"

  defp freshness_value(value) when value in ["fresh", "watch", "stale", "unsupported"], do: value
  defp freshness_value(_value), do: "watch"

  defp bounded_float(value, default) do
    value = to_float(value)

    cond do
      not is_number(value) -> default
      value < 0 -> 0.0
      value > 1 -> 1.0
      true -> value
    end
  end

  defp bounded_int(value, default, min, max) do
    value = to_int(value, default)

    cond do
      value < min -> min
      value > max -> max
      true -> value
    end
  end

  defp drop_nil_values(map) do
    Map.reject(map, fn {_key, value} -> is_nil(value) end)
  end

  defp update_event_collection(data, key, window_kind, generated_at, enrich?) do
    if Map.has_key?(data, key) do
      update_in(data, [key], fn items ->
        items
        |> List.wrap()
        |> Enum.filter(&is_map/1)
        |> maybe_enrich_news_items(enrich?)
        |> filter_news_items(window_kind, generated_at)
      end)
    else
      data
    end
  end

  defp update_alternative_signal_window(data, signal_key, window_kind, generated_at) do
    update_in(data, ["alternative_signals"], fn signals ->
      signals
      |> List.wrap()
      |> Enum.filter(&is_map/1)
      |> Enum.map(fn
        %{"key" => ^signal_key} = signal ->
          update_in(signal, ["items"], fn items ->
            filter_news_items_by_window(items, window_kind, generated_at)
          end)

        signal ->
          signal
      end)
    end)
  end

  defp refresh_breaking_market_map_counts(map) do
    mapped_count =
      map
      |> Map.get("map_points", [])
      |> List.wrap()
      |> Enum.count(&is_map/1)

    map
    |> maybe_put_existing("shown_count", mapped_count)
    |> maybe_put_existing("total_count", mapped_count)
  end

  defp sanitize_regional_briefs(map, generated_at) do
    update_in(map, ["regional_briefs"], fn briefs ->
      briefs
      |> List.wrap()
      |> Enum.filter(&is_map/1)
      |> Enum.map(&sanitize_regional_brief(&1, generated_at))
    end)
  end

  defp sanitize_regional_brief(brief, generated_at) do
    evidence =
      brief
      |> Map.get("evidence", [])
      |> List.wrap()
      |> Enum.filter(&is_map/1)
      |> Enum.sort_by(&regional_brief_evidence_sort_key/1)

    event_count = length(evidence)
    label = brief["label"] || brief["region_key"] || "Region"

    coverage_days =
      to_int(brief["coverage_window_days"], Settings.get(:news_analysis_window_days, 7))

    brief
    |> Map.put("event_count", event_count)
    |> Map.put("source_count", event_count)
    |> Map.put("coverage_window_days", max(1, coverage_days))
    |> Map.put("generated_at", iso8601(generated_at))
    |> Map.put("evidence", evidence)
    |> Map.put("summary", regional_brief_summary(label, event_count, coverage_days))
  end

  defp regional_brief_evidence_sort_key(item) do
    observed_at =
      [
        item["source_published_at"],
        item["published_at"],
        item["observed_at"],
        item["updated_at"]
      ]
      |> Enum.find_value(&parse_iso8601_datetime/1)

    timestamp =
      case observed_at do
        %DateTime{} = datetime -> -DateTime.to_unix(datetime)
        _ -> 0
      end

    {timestamp, to_string(item["title"] || ""), to_string(item["event_id"] || item["id"] || "")}
  end

  defp regional_brief_summary(label, 0, coverage_days) do
    "#{label} has no source-linked items in the #{coverage_days}-day metadata window."
  end

  defp regional_brief_summary(label, item_count, coverage_days) do
    "#{label} has #{item_count} source-linked item(s) in the #{coverage_days}-day metadata window."
  end

  defp maybe_enrich_news_items(items, true), do: Enum.map(items, &enrich_news_item/1)
  defp maybe_enrich_news_items(items, false), do: items

  defp enrich_news_list_data(data, object_type, generated_at) do
    window_kind = news_window_kind(object_type)

    events =
      data
      |> Map.get("events", [])
      |> List.wrap()
      |> Enum.filter(&is_map/1)
      |> Enum.map(&enrich_news_item/1)
      |> Enum.map(&put_news_freshness(&1, generated_at))
      |> filter_news_items(window_kind, generated_at)

    data
    |> Map.put("events", events)
    |> Map.put("coverage_window", news_window_label(window_kind))
    |> maybe_enrich_news_filters(object_type, events)
  end

  defp maybe_enrich_news_filters(data, "news_index", events) do
    update_in(data, ["filters"], fn filters ->
      filters
      |> ensure_map()
      |> Map.put("tickers", news_ticker_filter_options(events, filters))
      |> Map.put("regions", news_reference_filter_options(events, "regions", "key", "name"))
      |> Map.put("topics", news_reference_filter_options(events, "topics", "key", "label"))
      |> Map.put("trust_tiers", news_trust_filter_options(events))
    end)
  end

  defp maybe_enrich_news_filters(data, _object_type, _events), do: data

  defp enrich_news_detail_data(data, generated_at) do
    data
    |> enrich_news_item()
    |> put_news_freshness(generated_at)
    |> enrich_news_collection("related_events", generated_at)
  end

  defp enrich_scenario_news_items(data) do
    update_in(data, ["tracker_sections"], fn sections ->
      sections
      |> List.wrap()
      |> Enum.filter(&is_map/1)
      |> Enum.map(fn section ->
        update_in(section, ["news_events"], fn events ->
          events
          |> List.wrap()
          |> Enum.filter(&is_map/1)
          |> Enum.map(&enrich_news_item/1)
        end)
      end)
    end)
  end

  defp enrich_news_collection(data, key, generated_at) do
    update_in(data, [key], fn events ->
      events
      |> List.wrap()
      |> Enum.filter(&is_map/1)
      |> Enum.map(&enrich_news_item/1)
      |> maybe_put_news_freshness(generated_at)
    end)
  end

  defp enrich_ticker_calendar_items(data) do
    update_in(data, ["ticker_calendar_items"], fn items ->
      items
      |> List.wrap()
      |> Enum.filter(&is_map/1)
      |> Enum.map(&enrich_ticker_calendar_item/1)
    end)
  end

  defp enrich_ticker_calendar_item(%{"id" => id, "symbol" => "RKLB"} = item)
       when is_binary(id) do
    if String.contains?(id, "rklb_launch_window_seed") do
      item
      |> Map.put("title", "RKLB: Rocket Lab official updates and filings source watch")
      |> Map.put("catalyst_type", "source_review")
    else
      item
    end
  end

  defp enrich_ticker_calendar_item(item), do: item

  defp news_window_kind("news_index"), do: "search_archive"
  defp news_window_kind("news_region"), do: "analysis"
  defp news_window_kind("news_ticker"), do: "analysis"
  defp news_window_kind("news_topic"), do: "analysis"
  defp news_window_kind(_), do: "breaking_latest"

  defp news_window_label("breaking_latest"),
    do: "#{Settings.get(:news_breaking_window_hours, 24)}h"

  defp news_window_label("analysis"), do: "#{Settings.get(:news_analysis_window_days, 7)}d"
  defp news_window_label("search_archive"), do: "#{Settings.get(:news_search_window_days, 30)}d"

  defp filter_news_items(items, window_kind, generated_at) do
    items
    |> filter_news_items_by_window(window_kind, generated_at)
    |> Enum.filter(&news_item_allowed_on_surface?(&1, window_kind))
  end

  defp filter_news_items_by_window(items, window_kind, generated_at) do
    hours = news_window_hours(window_kind)
    cutoff = DateTime.add(generated_at, -hours, :hour)

    Enum.filter(items, fn item ->
      is_map(item) and news_item_within_window?(item, cutoff)
    end)
  end

  defp news_item_within_window?(item, cutoff) do
    case news_item_datetime(item) do
      nil -> true
      observed_at -> DateTime.compare(observed_at, cutoff) != :lt
    end
  end

  defp maybe_put_news_freshness(items, nil), do: items

  defp maybe_put_news_freshness(items, generated_at),
    do: Enum.map(items, &put_news_freshness(&1, generated_at))

  defp put_news_freshness(%{"freshness" => "unsupported"} = item, _generated_at), do: item

  defp put_news_freshness(item, generated_at) when is_map(item) do
    case news_item_datetime(item) do
      nil ->
        item

      %DateTime{} = observed_at ->
        Map.put(item, "freshness", news_freshness_label(observed_at, generated_at))
    end
  end

  defp put_news_freshness(item, _generated_at), do: item

  defp news_freshness_label(observed_at, generated_at) do
    cond do
      within_news_window?(observed_at, generated_at, "breaking_latest") -> "fresh"
      within_news_window?(observed_at, generated_at, "analysis") -> "watch"
      true -> "stale"
    end
  end

  defp within_news_window?(observed_at, generated_at, window_kind) do
    cutoff = DateTime.add(generated_at, -news_window_hours(window_kind), :hour)
    DateTime.compare(observed_at, cutoff) != :lt
  end

  defp news_item_allowed_on_surface?(item, "breaking_latest") do
    item_kind = item["item_kind"]
    claim_level = item["claim_level"]

    cond do
      truthy?(item["discovery_only"]) ->
        false

      claim_level in ["source_only", "unverified"] ->
        false

      item_kind == "source_discovery" ->
        false

      claim_level in ["clustered_candidate", "reviewed", "published"] ->
        true

      item_kind in ["event_candidate", "reviewed_event", "official_update", "filing_update"] ->
        true

      item["review_state"] in ["approved", "reviewed", "published"] ->
        true

      is_nil(item_kind) and is_nil(claim_level) ->
        false

      true ->
        false
    end
  end

  defp news_item_allowed_on_surface?(_item, _window_kind), do: true

  defp filter_map_points_for_allowed_events(map, generated_at) do
    allowed_event_ids =
      map
      |> Map.get("events", [])
      |> List.wrap()
      |> Enum.flat_map(fn event -> [event["event_id"], event["id"]] end)
      |> Enum.reject(&is_nil/1)
      |> Enum.map(&to_string/1)
      |> MapSet.new()

    cutoff = DateTime.add(generated_at, -news_window_hours("breaking_latest"), :hour)

    update_in(map, ["map_points"], fn points ->
      points
      |> List.wrap()
      |> Enum.filter(&is_map/1)
      |> Enum.filter(fn point ->
        map_point_allowed?(point, allowed_event_ids) and news_item_within_window?(point, cutoff)
      end)
    end)
  end

  defp map_point_allowed?(point, allowed_event_ids) do
    event_ids =
      [point["event_id"] | List.wrap(point["event_ids"])]
      |> Enum.reject(&is_nil/1)
      |> Enum.map(&to_string/1)

    event_ids != [] and Enum.any?(event_ids, &MapSet.member?(allowed_event_ids, &1))
  end

  defp news_window_hours("breaking_latest") do
    Settings.get(:news_breaking_window_hours, 24)
    |> to_int(24)
    |> max(1)
  end

  defp news_window_hours("analysis") do
    Settings.get(:news_analysis_window_days, 7)
    |> to_int(7)
    |> max(1)
    |> Kernel.*(24)
  end

  defp news_window_hours("search_archive") do
    Settings.get(:news_search_window_days, 30)
    |> to_int(30)
    |> max(1)
    |> Kernel.*(24)
  end

  defp news_item_datetime(item) do
    [
      item["last_seen_at"],
      item["observed_at"],
      item["source_published_at"],
      item["published_at"],
      item["updated_at"],
      item["first_seen_at"]
    ]
    |> Enum.find_value(&parse_iso8601_datetime/1)
  end

  defp parse_iso8601_datetime(value) when is_binary(value) do
    value = String.trim(value)

    with false <- value == "",
         {:ok, datetime, _offset} <- DateTime.from_iso8601(value) do
      datetime
    else
      _ -> nil
    end
  end

  defp parse_iso8601_datetime(_), do: nil

  defp enrich_news_item(item) when is_map(item) do
    item
    |> put_source_link_evidence_ids()
    |> put_news_claim_defaults(
      infer_news_item_kind(item),
      infer_news_claim_level(item),
      infer_evidence_match_status(item)
    )
  end

  defp enrich_news_item(other), do: other

  defp put_source_link_evidence_ids(item) do
    update_in(item, ["source_links"], fn
      links when is_list(links) ->
        Enum.map(links, &put_source_link_evidence_id/1)

      other ->
        other
    end)
  end

  defp put_source_link_evidence_id(%{} = link) do
    Map.put_new(link, "evidence_id", public_evidence_id(link))
  end

  defp put_source_link_evidence_id(link), do: link

  defp public_evidence_id(link) do
    seed =
      [
        link["source_key"],
        link["url"],
        link["title"],
        link["published_at"]
      ]
      |> Enum.map(&to_string/1)
      |> Enum.join("|")

    "doc_" <> (sha256(seed) |> String.slice(0, 24))
  end

  defp put_news_claim_defaults(item, item_kind, claim_level, evidence_match_status) do
    item
    |> Map.put_new("item_kind", item_kind)
    |> Map.put_new("claim_level", claim_level)
    |> Map.put_new("evidence_match_status", evidence_match_status)
  end

  defp infer_news_item_kind(item) do
    source_links = List.wrap(item["source_links"])

    cond do
      Enum.any?(source_links, &(Map.get(&1, "trust_tier") == "T0_OFFICIAL")) ->
        "official_update"

      Enum.any?(source_links, &(Map.get(&1, "trust_tier") == "T1_REGULATED_FILING")) ->
        "filing_update"

      true ->
        "source_discovery"
    end
  end

  defp infer_news_claim_level(item) do
    item_kind = infer_news_item_kind(item)
    source_count = to_int(item["source_count"], 0)
    trust_score = to_int(item["trust_score"], 0)

    cond do
      item_kind == "source_discovery" ->
        "source_only"

      source_count >= 2 and trust_score >= 85 ->
        "clustered_candidate"

      true ->
        "source_only"
    end
  end

  defp infer_evidence_match_status(item) do
    confidences =
      item
      |> Map.get("tickers", [])
      |> List.wrap()
      |> Enum.map(&to_float(&1["confidence"]))

    max_confidence = Enum.max(confidences, fn -> 0.0 end)

    cond do
      max_confidence >= 0.75 -> "matched"
      max_confidence > 0 -> "weak_match"
      true -> "unverified"
    end
  end

  defp news_ticker_filter_options(events, filters) do
    event_counts =
      events
      |> Enum.flat_map(&(Map.get(&1, "tickers", []) |> List.wrap()))
      |> Enum.map(&(&1["symbol"] || &1["key"]))
      |> Enum.reject(&is_nil/1)
      |> Enum.map(&(to_string(&1) |> String.trim()))
      |> Enum.reject(&(&1 == ""))
      |> Enum.frequencies()

    labels =
      filters
      |> ensure_map()
      |> Map.get("tickers", [])
      |> List.wrap()
      |> Enum.filter(&is_map/1)
      |> Map.new(fn option -> {to_string(option["key"]), option["label"] || option["key"]} end)

    TrackedTickers.ticker_filter_options(event_counts, labels)
  end

  defp news_reference_filter_options(events, collection_key, key_field, label_field) do
    events
    |> Enum.flat_map(fn event ->
      event
      |> Map.get(collection_key, [])
      |> List.wrap()
      |> Enum.filter(&is_map/1)
      |> Enum.map(fn item ->
        key = item[key_field] |> to_string() |> String.trim()
        label = item[label_field] |> to_string() |> String.trim()
        {key, if(label == "", do: key, else: label)}
      end)
      |> Enum.reject(fn {key, _label} -> key == "" end)
      |> Enum.uniq_by(&elem(&1, 0))
    end)
    |> Enum.group_by(&elem(&1, 0), &elem(&1, 1))
    |> Enum.map(fn {key, labels} ->
      %{"key" => key, "label" => List.first(labels) || key, "count" => length(labels)}
    end)
    |> Enum.sort_by(fn option -> {-option["count"], option["label"]} end)
  end

  defp news_trust_filter_options(events) do
    events
    |> Enum.flat_map(fn event ->
      event
      |> Map.get("source_links", [])
      |> List.wrap()
      |> Enum.map(&news_trust_tier(&1["trust_tier"]))
      |> Enum.uniq()
    end)
    |> Enum.frequencies()
    |> Enum.map(fn {tier, count} ->
      %{"key" => tier, "label" => trust_tier_label(tier), "count" => count}
    end)
    |> Enum.sort_by(fn option -> {trust_tier_rank(option["key"]), option["label"]} end)
  end

  defp trust_tier_label("T0_OFFICIAL"), do: "T0 · Official"
  defp trust_tier_label("T1_REGULATED_FILING"), do: "T1 · Regulated filing"
  defp trust_tier_label("T2_REPUTABLE_MEDIA"), do: "T2 · Reputable media"
  defp trust_tier_label("T3_REVIEWED_PUBLIC_SOURCE"), do: "T3 · Reviewed public source"
  defp trust_tier_label("T4_WEAK_SIGNAL"), do: "T4 · Weak signal"
  defp trust_tier_label("T5_UNREVIEWED"), do: "T5 · Unreviewed"
  defp trust_tier_label("T6_BLOCKED"), do: "T6 · Blocked"
  defp trust_tier_label(tier), do: tier

  defp refresh_source_policy_versions(%{"data" => data} = snapshot) do
    versions =
      data
      |> collect_source_policy_versions([])
      |> Enum.uniq_by(& &1["source_key"])
      |> Enum.sort_by(& &1["source_key"])

    Map.put(snapshot, "source_policy_versions", versions)
  end

  defp refresh_source_policy_versions(snapshot), do: snapshot

  defp collect_source_policy_versions(value, acc) when is_list(value) do
    Enum.reduce(value, acc, &collect_source_policy_versions/2)
  end

  defp collect_source_policy_versions(value, acc) when is_map(value) do
    acc =
      case {value["source_key"], value["policy_version"]} do
        {source_key, policy_version} when is_binary(source_key) and source_key != "" ->
          [
            %{
              "source_key" => source_key,
              "policy_version" => max(to_int(policy_version, 1), 1)
            }
            | acc
          ]

        _ ->
          acc
      end

    Enum.reduce(Map.values(value), acc, &collect_source_policy_versions/2)
  end

  defp collect_source_policy_versions(_value, acc), do: acc

  defp write_snapshot(candidate_root, relative, snapshot) do
    snapshot = Map.put(snapshot, "content_hash", payload_hash(snapshot["data"]))
    target = safe_snapshot_write_path(candidate_root, relative)

    with :ok <- File.mkdir_p(Path.dirname(target)),
         :ok <- File.write(target, Jason.encode!(snapshot, pretty: true) <> "\n"),
         :ok <- validate_snapshot_file(target) do
      {:ok, target}
    else
      {:error, reason} when is_binary(reason) -> {:error, reason}
      {:error, reason} -> {:error, "Could not write snapshot #{target}: #{inspect(reason)}"}
    end
  end

  defp write_manifest(candidate_root, manifest) do
    manifest_path = Path.join(candidate_root, @latest_manifest_path)

    with :ok <- File.mkdir_p(Path.dirname(manifest_path)),
         :ok <- File.write(manifest_path, Jason.encode!(manifest, pretty: true) <> "\n") do
      :ok
    else
      {:error, reason} ->
        {:error, "Could not write snapshot manifest #{manifest_path}: #{inspect(reason)}"}
    end
  end

  defp safe_snapshot_write_path(root, relative) do
    root = Path.expand(root)
    target = Path.expand(Path.join(root, relative))

    if Path.type(relative) == :relative and ".." not in Path.split(relative) and
         String.starts_with?(target, root <> "/") do
      target
    else
      raise ArgumentError, "Unsafe snapshot path: #{relative}"
    end
  end

  defp record_candidate_rows(candidate_root, version, status, generated_by) do
    if snapshot_db_recording_enabled?() do
      record_manifest(candidate_root, version, status, generated_by)
      record_publication_rows(candidate_root, version, status, generated_by)
    end

    :ok
  end

  defp build_published_tree_candidate(payload) do
    version = next_snapshot_version()
    candidate_root = candidate_root(version)
    File.rm_rf!(candidate_root)
    File.mkdir_p!(candidate_root)

    with :ok <- copy_tree(published_root(), candidate_root),
         :ok <- validate_snapshot_tree(candidate_root) do
      record_manifest(candidate_root, version, "candidate", payload["requested_by"])
      record_publication_rows(candidate_root, version, "candidate", payload["requested_by"])

      {:ok,
       %{
         files: json_files(candidate_root),
         uploaded: false,
         destination: candidate_root,
         manifest_path: @public_manifest_key,
         snapshot_version: version
       }}
    end
  end

  def validate_snapshot_tree(root) do
    with :ok <- require_manifest(root) do
      root
      |> json_files()
      |> Enum.reduce_while(:ok, fn path, :ok ->
        case validate_snapshot_file(path) do
          :ok -> {:cont, :ok}
          {:error, reason} -> {:halt, {:error, reason}}
        end
      end)
    end
  end

  def publish_from_payload(%{"snapshot_version" => version}) do
    case parse_positive_snapshot_version(version) do
      {:ok, version} -> publish(version)
      :error -> {:error, "snapshot_publish requires positive snapshot_version"}
    end
  end

  def publish_from_payload(_), do: {:error, "snapshot_publish requires snapshot_version"}

  def parse_positive_snapshot_version(value), do: parse_positive_int(value)

  def refresh(payload \\ %{}) do
    with {:ok, result} <- build_candidate(payload),
         {:ok, published} <- publish(result.snapshot_version) do
      {:ok, published}
    end
  end

  defp copy_published_tree_requested?(payload) when is_map(payload) do
    payload_value(payload, "mode") in ["copy_published_tree", "compatibility_copy"] or
      truthy?(payload_value(payload, "copy_published_tree"))
  end

  defp copy_published_tree_requested?(_), do: false

  defp payload_value(payload, key) do
    Map.get(payload, key) || Map.get(payload, String.to_atom(key))
  end

  defp truthy?(value) when is_binary(value),
    do: String.downcase(value) in ["1", "true", "yes", "on"]

  defp truthy?(value), do: value in [true, 1]

  def publish(version) do
    candidate_root = candidate_root(version)

    with true <- File.exists?(candidate_root),
         :ok <- validate_snapshot_tree(candidate_root),
         {:ok, refresh} <- refresh_published_volume(candidate_root),
         :ok <- mark_published(version) do
      {:ok,
       Map.merge(refresh, %{
         manifest_path: @public_manifest_key,
         snapshot_version: version
       })}
    else
      false -> {:error, "Snapshot candidate files for v#{version} are missing"}
      {:error, reason} -> {:error, reason}
    end
  end

  def rollback(version), do: publish(version)

  def refresh_published_volume(source_root, destination_root \\ published_root()) do
    with true <- File.exists?(source_root),
         :ok <- require_manifest(source_root),
         {:ok, files, byte_size} <- guarded_files(source_root),
         :ok <- validate_snapshot_tree(source_root),
         :ok <- copy_files_with_rollback(files, source_root, destination_root) do
      {:ok,
       %{
         files: json_files(source_root),
         uploaded: false,
         destination: destination_root,
         file_count: length(files),
         byte_size: byte_size
       }}
    else
      false -> {:error, "Snapshot source #{source_root} is missing"}
      {:error, reason} -> {:error, reason}
    end
  end

  def list_candidates do
    Sql.all("""
    select snapshot_version, publication_status, generated_at, published_at, byte_size, content_hash
    from publication_manifest
    order by generated_at desc
    limit 50
    """)
  end

  def manifest_status do
    path = published_manifest_path()

    with true <- File.exists?(path),
         {:ok, stat} <- File.stat(path),
         {:ok, content} <- File.read(path),
         {:ok, manifest} <- Jason.decode(content),
         {:ok, mtime} <- file_stat_time_to_datetime(stat.mtime) do
      generated_at = manifest["generated_at"]

      age_minutes = DateTime.diff(DateTime.utc_now(), mtime, :second) / 60

      %{generated_at: generated_at, age_minutes: age_minutes}
    else
      _ -> nil
    end
  rescue
    _ -> nil
  end

  defp file_stat_time_to_datetime(%DateTime{} = datetime), do: {:ok, datetime}

  defp file_stat_time_to_datetime(%NaiveDateTime{} = naive_datetime),
    do: DateTime.from_naive(naive_datetime, "Etc/UTC")

  defp file_stat_time_to_datetime({date, time}) do
    with {:ok, naive_datetime} <- NaiveDateTime.from_erl({date, time}) do
      DateTime.from_naive(naive_datetime, "Etc/UTC")
    end
  end

  defp file_stat_time_to_datetime(_mtime), do: :error

  defp next_snapshot_version do
    if snapshot_db_recording_enabled?() do
      (Sql.scalar(
         "select coalesce(max(snapshot_version), 0) + 1 from publication_manifest",
         [],
         1
       ) ||
         1)
      |> to_int()
    else
      published_manifest_version() + 1
    end
  end

  defp published_manifest_version do
    published_manifest_path()
    |> read_snapshot()
    |> case do
      {:ok, %{"current_version" => version}} -> to_int(version, 0)
      _ -> 0
    end
  end

  defp record_manifest(candidate_root, version, status, generated_by) do
    generated_by = generated_by_uuid(generated_by)
    manifest_path = Path.join(candidate_root, @latest_manifest_path)
    content = if File.exists?(manifest_path), do: File.read!(manifest_path), else: "{}"
    manifest = decode_json(content, %{})
    hash = "sha256:" <> (:crypto.hash(:sha256, content) |> Base.encode16(case: :lower))
    generated_at = manifest["generated_at"] || DateTime.to_iso8601(DateTime.utc_now())

    Sql.execute(
      """
      insert into publication_manifest(
        snapshot_version, manifest_json, storage_object_key, content_hash,
        byte_size, generated_at, publication_status, generated_by
      )
      values ($1, $2::text::jsonb, $3, $4, $5, $6::text::timestamptz, $7, $8)
      on conflict (snapshot_version) do update
      set manifest_json = excluded.manifest_json,
          storage_object_key = excluded.storage_object_key,
          content_hash = excluded.content_hash,
          byte_size = excluded.byte_size,
          generated_at = excluded.generated_at,
          publication_status = excluded.publication_status,
          generated_by = excluded.generated_by
      """,
      [
        version,
        Jason.encode!(manifest),
        @public_manifest_key,
        hash,
        byte_size(content),
        generated_at,
        status,
        generated_by
      ]
    )
  end

  defp record_publication_rows(candidate_root, version, status, generated_by) do
    generated_by = generated_by_uuid(generated_by)

    candidate_root
    |> json_files()
    |> Enum.reject(&(Path.basename(&1) == @manifest_filename))
    |> Enum.each(fn path ->
      with {:ok, snapshot} <- read_snapshot(path),
           true <- snapshot_recordable?(snapshot) do
        Sql.execute(
          """
          insert into publication_snapshot(
            snapshot_version, locale, object_type, object_key, schema_version,
            storage_object_key, content_hash, byte_size, generated_at, stale_after,
            hard_expires_at, source_policy_versions, publication_status, generated_by
          )
          values (
            $1, $2, $3, $4, $5, $6, $7, $8, $9::text::timestamptz,
            $10::text::timestamptz, $11::text::timestamptz, $12::text::jsonb, $13, $14
          )
          on conflict (snapshot_version, locale, object_type, object_key)
          do update set publication_status = excluded.publication_status,
                        content_hash = excluded.content_hash,
                        byte_size = excluded.byte_size,
                        generated_by = excluded.generated_by
          """,
          [
            version,
            snapshot["locale"],
            snapshot["object_type"],
            snapshot["object_key"],
            snapshot["schema_version"],
            "public/#{Path.relative_to(path, candidate_root)}",
            content_hash(path),
            File.stat!(path).size,
            snapshot["generated_at"],
            snapshot["stale_after"],
            snapshot["hard_expires_at"],
            Jason.encode!(snapshot["source_policy_versions"] || []),
            status,
            generated_by
          ]
        )
      end
    end)
  end

  defp generated_by_uuid(nil), do: nil

  defp generated_by_uuid(generated_by) when is_binary(generated_by) do
    case Ecto.UUID.cast(String.trim(generated_by)) do
      {:ok, uuid} -> uuid
      :error -> nil
    end
  end

  defp generated_by_uuid(_generated_by), do: nil

  defp mark_published(version) do
    if snapshot_db_recording_enabled?() do
      mark_published_rows(version)
    else
      :ok
    end
  end

  defp mark_published_rows(version) do
    Repo.transaction(fn ->
      Sql.execute(
        "update publication_manifest set publication_status = 'rolled_back' where publication_status = 'published'"
      )

      Sql.execute(
        "update publication_snapshot set publication_status = 'rolled_back' where publication_status = 'published'"
      )

      Sql.execute(
        "update publication_manifest set publication_status = 'published', published_at = now() where snapshot_version = $1",
        [version]
      )

      Sql.execute(
        "update publication_snapshot set publication_status = 'published' where snapshot_version = $1",
        [version]
      )

      :ok
    end)
    |> case do
      {:ok, :ok} ->
        :ok

      {:error, reason} ->
        {:error, "Failed to mark snapshot v#{version} published: #{inspect(reason)}"}
    end
  end

  defp validate_snapshot_file(path) do
    if Path.basename(path) == @manifest_filename do
      validate_manifest(path)
    else
      with {:ok, snapshot} <- read_snapshot(path),
           :ok <- validate_snapshot_envelope(snapshot, path),
           :ok <- assert_not_prohibited_public_snapshot(snapshot, path),
           :ok <- PublicGuards.assert_no_raw_private(snapshot, path),
           :ok <- PublicGuards.assert_no_placeholder_display_terms(snapshot, path),
           :ok <- validate_snapshot_schema(snapshot, path) do
        :ok
      end
    end
  end

  defp validate_manifest(path) do
    root = snapshot_root_from_manifest_path(path)

    with {:ok, manifest} <- read_snapshot(path),
         :ok <- validate_manifest_shape(manifest, path),
         :ok <- validate_manifest_references(manifest, root, path) do
      :ok
    else
      {:error, reason} -> {:error, reason}
      _ -> {:error, "#{path} is not a valid snapshot manifest"}
    end
  end

  defp validate_manifest_shape(manifest, path) do
    cond do
      !is_list(manifest["locales"]) or manifest["locales"] == [] or
          !Enum.all?(manifest["locales"], &is_binary/1) ->
        {:error, "#{path} is not a valid snapshot manifest"}

      !is_map(manifest["objects"]) or map_size(manifest["objects"]) == 0 ->
        {:error, "#{path} is not a valid snapshot manifest"}

      prohibited_manifest_object_key(manifest) ->
        {:error, "#{path} references prohibited public operational snapshot"}

      true ->
        :ok
    end
  end

  defp validate_manifest_references(manifest, root, path) do
    locales = MapSet.new(manifest["locales"])

    Enum.reduce_while(manifest["objects"], :ok, fn {object_key, locale_paths}, :ok ->
      if is_map(locale_paths) do
        case validate_manifest_locale_paths(locale_paths, locales, root, object_key) do
          :ok -> {:cont, :ok}
          {:error, reason} -> {:halt, {:error, "#{path} #{reason}"}}
        end
      else
        {:halt, {:error, "#{path} object #{object_key} must map locales to snapshot paths"}}
      end
    end)
  end

  defp validate_manifest_locale_paths(locale_paths, locales, root, object_key) do
    Enum.reduce_while(locale_paths, :ok, fn {locale, public_path}, :ok ->
      cond do
        !MapSet.member?(locales, locale) ->
          {:halt, {:error, "references undeclared locale #{locale} for #{object_key}"}}

        !is_binary(public_path) or String.trim(public_path) == "" ->
          {:halt, {:error, "has an invalid path for #{object_key}/#{locale}"}}

        true ->
          case validate_manifest_snapshot_reference(root, object_key, locale, public_path) do
            :ok -> {:cont, :ok}
            {:error, reason} -> {:halt, {:error, reason}}
          end
      end
    end)
  end

  defp validate_manifest_snapshot_reference(root, object_key, locale, public_path) do
    with {:ok, relative} <- manifest_snapshot_relative_path(public_path),
         snapshot_path = Path.join(root, relative),
         :ok <- require_manifest_snapshot_file(snapshot_path, public_path, object_key, locale),
         {:ok, snapshot} <- read_snapshot(snapshot_path),
         :ok <- require_manifest_snapshot_locale(snapshot, locale, public_path, object_key) do
      :ok
    else
      {:error, reason} ->
        {:error, reason}
    end
  end

  defp assert_not_prohibited_public_snapshot(snapshot, path) do
    cond do
      prohibited_public_object_type?(snapshot["object_type"]) ->
        {:error, "#{path} contains prohibited public operational snapshot"}

      prohibited_public_object_key?(snapshot["object_key"]) ->
        {:error, "#{path} contains prohibited public operational snapshot"}

      true ->
        :ok
    end
  end

  defp prohibited_manifest_object_key(manifest) do
    manifest
    |> Map.get("objects", %{})
    |> Map.keys()
    |> Enum.any?(&prohibited_public_object_key?/1)
  end

  defp prohibited_public_object_key?(key), do: to_string(key) in @prohibited_public_object_keys

  defp prohibited_public_object_type?(type),
    do: to_string(type) in @prohibited_public_object_types

  defp require_manifest_snapshot_file(snapshot_path, public_path, object_key, locale) do
    if File.regular?(snapshot_path) do
      :ok
    else
      {:error, "references missing snapshot #{public_path} for #{object_key}/#{locale}"}
    end
  end

  defp require_manifest_snapshot_locale(snapshot, locale, public_path, object_key) do
    if snapshot["locale"] == locale do
      :ok
    else
      {:error, "references locale-mismatched snapshot #{public_path} for #{object_key}/#{locale}"}
    end
  end

  defp manifest_snapshot_relative_path(public_path) do
    public_path = String.trim(public_path)

    cond do
      !String.starts_with?(public_path, "public/") ->
        {:error, "references non-public snapshot path #{public_path}"}

      String.ends_with?(public_path, "/") ->
        {:error, "references invalid snapshot path #{public_path}"}

      true ->
        relative = String.replace_prefix(public_path, "public/", "")
        parts = Path.split(relative)

        if relative != "" and Path.type(relative) == :relative and ".." not in parts do
          {:ok, relative}
        else
          {:error, "references unsafe snapshot path #{public_path}"}
        end
    end
  end

  defp snapshot_root_from_manifest_path(path) do
    path
    |> Path.dirname()
    |> Path.dirname()
  end

  defp validate_snapshot_envelope(snapshot, path) do
    required = [
      "content_hash",
      "corrections",
      "data",
      "generated_at",
      "hard_expires_at",
      "locale",
      "object_key",
      "object_type",
      "schema_version",
      "snapshot_version",
      "source_policy_versions",
      "stale_after",
      "warnings"
    ]

    missing = Enum.reject(required, &Map.has_key?(snapshot, &1))

    cond do
      missing != [] ->
        {:error, "#{path} missing envelope fields: #{Enum.join(missing, ", ")}"}

      !String.starts_with?(to_string(snapshot["content_hash"]), "sha256:") ->
        {:error, "#{path} content_hash must be sha256"}

      true ->
        :ok
    end
  end

  defp validate_snapshot_schema(snapshot, path) do
    with {:ok, schema_filename} <- schema_filename(snapshot),
         {:ok, schema} <- build_snapshot_schema(schema_filename),
         {:ok, _validated} <- JSV.validate(snapshot, schema) do
      :ok
    else
      {:error, {:unknown_object_type, object_type}} ->
        {:error, "Unknown snapshot object_type: #{inspect(object_type)}"}

      {:error, {:schema_dir_missing, schema_root}} ->
        {:error, "Snapshot schema directory is missing: #{schema_root}"}

      {:error, %JSV.ValidationError{} = error} ->
        {:error, "#{path} failed snapshot schema validation: #{format_schema_error(error)}"}

      {:error, reason} ->
        {:error, "#{path} failed snapshot schema validation: #{inspect(reason)}"}
    end
  end

  defp schema_filename(snapshot) do
    case Map.fetch(@schema_by_object_type, snapshot["object_type"]) do
      {:ok, schema_filename} -> {:ok, schema_filename}
      :error -> {:error, {:unknown_object_type, snapshot["object_type"]}}
    end
  end

  defp build_snapshot_schema(schema_filename) do
    with {:ok, schema_root} <- snapshot_schema_root(),
         schema_path = Path.join(schema_root, schema_filename),
         true <- File.regular?(schema_path),
         {:ok, content} <- File.read(schema_path),
         {:ok, raw_schema} <- Jason.decode(content) do
      schema =
        raw_schema
        |> Map.put("$id", SchemaResolver.schema_base() <> schema_filename)
        |> JSV.build!(resolver: {SchemaResolver, schema_root})

      {:ok, schema}
    else
      false -> {:error, {:schema_missing, schema_filename}}
      {:error, reason} -> {:error, reason}
    end
  rescue
    exception -> {:error, Exception.message(exception)}
  end

  defp snapshot_schema_root do
    configured = Settings.get(:snapshot_schema_dir)

    configured
    |> configured_schema_root()
    |> case do
      nil -> discover_schema_root()
      schema_root -> {:ok, schema_root}
    end
  end

  defp configured_schema_root(value) when is_binary(value) do
    value = String.trim(value)
    if value == "", do: nil, else: Path.expand(value)
  end

  defp configured_schema_root(_), do: nil

  defp discover_schema_root do
    candidates =
      [
        Path.expand(@schema_dir, File.cwd!()),
        Path.expand("../../#{@schema_dir}", File.cwd!()),
        Path.expand("../../../#{@schema_dir}", File.cwd!()),
        Path.join(["/app", @schema_dir])
      ]
      |> Enum.uniq()

    case Enum.find(candidates, &File.dir?/1) do
      nil -> {:error, {:schema_dir_missing, hd(candidates)}}
      schema_root -> {:ok, schema_root}
    end
  end

  defp format_schema_error(error) do
    error
    |> JSV.normalize_error()
    |> collect_schema_messages()
    |> Enum.uniq()
    |> Enum.take(6)
    |> Enum.join("; ")
  end

  defp collect_schema_messages(value), do: collect_schema_messages(value, nil)

  defp collect_schema_messages(value, location) when is_map(value) do
    location = Map.get(value, :instanceLocation) || location

    message =
      case Map.get(value, :message) do
        nil -> []
        text -> ["#{location || "#"} #{text}"]
      end

    nested =
      value
      |> Map.take([:details, :errors])
      |> Map.values()
      |> Enum.flat_map(&collect_schema_messages(&1, location))

    message ++ nested
  end

  defp collect_schema_messages(value, location) when is_list(value) do
    Enum.flat_map(value, &collect_schema_messages(&1, location))
  end

  defp collect_schema_messages(_value, _location), do: []

  defp corrections do
    """
    select id, title, status, published_at, summary
    from correction_log
    order by published_at desc
    limit 200
    """
    |> Sql.all()
    |> Enum.map(fn row ->
      %{
        "id" => to_string(row["id"]),
        "title" => to_string(row["title"] || ""),
        "status" => to_string(row["status"] || "correction"),
        "published_at" => to_string(row["published_at"] || iso8601(DateTime.utc_now())),
        "summary" => to_string(row["summary"] || "")
      }
    end)
  end

  defp ensure_map(value) when is_map(value), do: value
  defp ensure_map(_value), do: %{}

  defp maybe_put_existing(map, key, value) do
    if Map.has_key?(map, key), do: Map.put(map, key, value), else: map
  end

  defp update_snapshot_health(data, context) do
    case data["snapshot_health"] do
      health when is_map(health) ->
        Map.put(
          data,
          "snapshot_health",
          Map.merge(health, %{
            "age_minutes" => 0,
            "stale_after" => iso8601(context.stale_after)
          })
        )

      _ ->
        data
    end
  end

  defp payload_hash(payload) do
    "sha256:" <>
      (:crypto.hash(:sha256, Jason.encode!(payload || %{})) |> Base.encode16(case: :lower))
  end

  defp iso8601(%DateTime{} = value), do: DateTime.to_iso8601(value)

  defp snapshot_db_recording_enabled? do
    Settings.get(:snapshot_db_recording_enabled, true) |> truthy?()
  end

  defp copy_tree(source, dest) do
    with true <- File.exists?(source),
         {:ok, files, _byte_size} <- guarded_files(source),
         :ok <- File.mkdir_p(dest) do
      Enum.reduce_while(files, :ok, fn path, :ok ->
        relative = Path.relative_to(path, source)
        target = Path.join(dest, relative)

        case copy_file_atomic(path, target) do
          :ok -> {:cont, :ok}
          {:error, reason} -> {:halt, {:error, reason}}
        end
      end)
    else
      false -> {:error, "Snapshot source #{source} is missing"}
      {:error, reason} -> {:error, reason}
    end
  end

  defp copy_files_with_rollback(files, source_root, destination_root) do
    files = publish_order(files, source_root)
    rollback_root = rollback_root(destination_root)

    File.rm_rf!(rollback_root)
    File.mkdir_p!(rollback_root)
    File.mkdir_p!(destination_root)

    initial_state = %{backed_up: MapSet.new(), created: MapSet.new()}

    result =
      Enum.reduce_while(files, {:ok, initial_state}, fn path, {:ok, state} ->
        relative = Path.relative_to(path, source_root)
        destination = Path.join(destination_root, relative)

        with {:ok, state} <- backup_destination(destination, relative, rollback_root, state),
             :ok <- copy_file_atomic(path, destination) do
          {:cont, {:ok, state}}
        else
          {:error, reason} -> {:halt, {:error, reason, state}}
        end
      end)

    result =
      with {:ok, state} <- result do
        remove_obsolete_destination_files(
          files,
          source_root,
          destination_root,
          rollback_root,
          state
        )
      end

    case result do
      {:ok, _state} ->
        File.rm_rf!(rollback_root)
        :ok

      {:error, reason, state} ->
        restore_published_files!(state, rollback_root, destination_root)
        File.rm_rf!(rollback_root)
        {:error, reason}
    end
  end

  defp remove_obsolete_destination_files(
         files,
         source_root,
         destination_root,
         rollback_root,
         state
       ) do
    source_relatives =
      files
      |> Enum.map(&Path.relative_to(&1, source_root))
      |> MapSet.new()

    with {:ok, destination_files} <- all_files(destination_root) do
      retained_versions =
        retained_published_versions(
          source_relatives,
          destination_files,
          destination_root
        )

      Enum.reduce_while(destination_files, {:ok, state}, fn destination, {:ok, state} ->
        relative = Path.relative_to(destination, destination_root)

        if MapSet.member?(source_relatives, relative) or
             retained_published_version?(relative, retained_versions) do
          {:cont, {:ok, state}}
        else
          case remove_obsolete_destination_file(destination, relative, rollback_root, state) do
            {:ok, state} -> {:cont, {:ok, state}}
            {:error, reason, state} -> {:halt, {:error, reason, state}}
          end
        end
      end)
    else
      {:error, reason} -> {:error, reason, state}
    end
  end

  defp retained_published_versions(source_relatives, destination_files, destination_root) do
    destination_relatives =
      Enum.map(destination_files, &Path.relative_to(&1, destination_root))

    source_relatives
    |> MapSet.to_list()
    |> Kernel.++(destination_relatives)
    |> Enum.flat_map(fn relative ->
      case published_version(relative) do
        {:ok, version} -> [version]
        :error -> []
      end
    end)
    |> Enum.uniq()
    |> Enum.sort(:desc)
    |> Enum.take(@published_version_retention_count)
    |> MapSet.new()
  end

  defp retained_published_version?(relative, retained_versions) do
    case published_version(relative) do
      {:ok, version} -> MapSet.member?(retained_versions, version)
      :error -> false
    end
  end

  defp published_version(relative) do
    case Path.split(relative) do
      ["v" <> version | suffix] when suffix != [] -> parse_positive_snapshot_version(version)
      _ -> :error
    end
  end

  defp remove_obsolete_destination_file(destination, relative, rollback_root, state) do
    with {:ok, state} <- backup_destination(destination, relative, rollback_root, state),
         :ok <- File.rm(destination) do
      {:ok, state}
    else
      {:error, reason} ->
        {:error, "Could not remove obsolete snapshot file #{destination}: #{inspect(reason)}",
         state}
    end
  end

  defp backup_destination(destination, relative, rollback_root, state) do
    cond do
      MapSet.member?(state.backed_up, relative) or MapSet.member?(state.created, relative) ->
        {:ok, state}

      File.exists?(destination) ->
        backup = Path.join(rollback_root, relative)

        with :ok <- File.mkdir_p(Path.dirname(backup)),
             :ok <- File.cp(destination, backup) do
          {:ok, %{state | backed_up: MapSet.put(state.backed_up, relative)}}
        else
          {:error, reason} ->
            {:error, "Could not back up #{destination}: #{inspect(reason)}"}
        end

      true ->
        {:ok, %{state | created: MapSet.put(state.created, relative)}}
    end
  end

  defp restore_published_files!(state, rollback_root, destination_root) do
    Enum.each(state.created, fn relative ->
      destination_root
      |> Path.join(relative)
      |> File.rm()
    end)

    Enum.each(state.backed_up, fn relative ->
      backup = Path.join(rollback_root, relative)
      destination = Path.join(destination_root, relative)
      File.mkdir_p!(Path.dirname(destination))
      File.cp!(backup, destination)
    end)
  end

  defp copy_file_atomic(source, destination) do
    temporary =
      Path.join(
        Path.dirname(destination),
        ".#{Path.basename(destination)}.#{random_suffix()}.tmp"
      )

    with :ok <- File.mkdir_p(Path.dirname(destination)),
         :ok <- File.cp(source, temporary),
         :ok <- File.rename(temporary, destination) do
      :ok
    else
      {:error, reason} ->
        File.rm(temporary)
        {:error, "Could not copy #{source} to #{destination}: #{inspect(reason)}"}
    end
  end

  defp guarded_files(root) do
    max_files = configured_positive_int(:snapshot_publish_max_files, @default_publish_max_files)

    with {:ok, files} <- all_files(root),
         true <- length(files) <= max_files,
         {:ok, byte_size} <- guarded_byte_size(files) do
      {:ok, files, byte_size}
    else
      false ->
        {:error, "Snapshot tree #{root} exceeds file limit #{max_files}"}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp guarded_byte_size(files) do
    max_bytes = configured_positive_int(:snapshot_publish_max_bytes, @default_publish_max_bytes)

    Enum.reduce_while(files, {:ok, 0}, fn path, {:ok, total} ->
      case File.stat(path) do
        {:ok, %File.Stat{type: :regular, size: size}} ->
          next_total = total + size

          if next_total > max_bytes do
            {:halt, {:error, "Snapshot tree exceeds byte limit #{max_bytes}"}}
          else
            {:cont, {:ok, next_total}}
          end

        {:ok, %File.Stat{type: type}} ->
          {:halt, {:error, "Snapshot tree contains non-regular file #{path}: #{type}"}}

        {:error, reason} ->
          {:halt, {:error, "Could not stat snapshot file #{path}: #{inspect(reason)}"}}
      end
    end)
  end

  defp publish_order(files, source_root) do
    Enum.sort_by(files, fn path ->
      relative = Path.relative_to(path, source_root)
      {relative == @latest_manifest_path, relative}
    end)
  end

  defp rollback_root(destination_root) do
    parent = Path.dirname(destination_root)
    basename = Path.basename(destination_root)
    unique = System.unique_integer([:positive])

    Path.join(parent, ".#{basename}.rollback-#{unique}")
  end

  defp require_manifest(root) do
    if File.exists?(Path.join(root, @latest_manifest_path)) do
      :ok
    else
      {:error, "Snapshot source #{root} is missing #{@latest_manifest_path}"}
    end
  end

  defp all_files(root) do
    root
    |> Path.join("**/*")
    |> Path.wildcard()
    |> Enum.sort()
    |> Enum.reduce_while({:ok, []}, fn path, {:ok, files} ->
      case File.lstat(path) do
        {:ok, %File.Stat{type: :directory}} ->
          {:cont, {:ok, files}}

        {:ok, %File.Stat{type: :regular}} ->
          {:cont, {:ok, [path | files]}}

        {:ok, %File.Stat{type: type}} ->
          relative = Path.relative_to(path, root)

          {:halt,
           {:error, "Snapshot tree #{root} contains non-regular file #{relative}: #{type}"}}

        {:error, reason} ->
          {:halt, {:error, "Could not inspect snapshot path #{path}: #{inspect(reason)}"}}
      end
    end)
    |> case do
      {:ok, files} -> {:ok, Enum.reverse(files)}
      {:error, reason} -> {:error, reason}
    end
  end

  defp json_files(root) do
    root
    |> Path.join(@json_file_glob)
    |> Path.wildcard()
    |> Enum.sort()
  end

  defp read_snapshot(path) do
    with {:ok, content} <- File.read(path),
         {:ok, json} <- Jason.decode(content) do
      {:ok, json}
    else
      {:error, reason} -> {:error, "#{path} is not valid JSON: #{inspect(reason)}"}
    end
  end

  defp decode_json(content, default) do
    case Jason.decode(content) do
      {:ok, decoded} -> decoded
      _ -> default
    end
  end

  defp content_hash(path) do
    "sha256:" <> (:crypto.hash(:sha256, File.read!(path)) |> Base.encode16(case: :lower))
  end

  defp random_suffix do
    8
    |> :crypto.strong_rand_bytes()
    |> Base.url_encode64(padding: false)
  end

  defp sha256(value) do
    :crypto.hash(:sha256, to_string(value))
    |> Base.url_encode64(padding: false)
  end

  defp snapshot_recordable?(snapshot) do
    Enum.all?(["locale", "object_type", "object_key", "schema_version", "generated_at"], fn key ->
      is_binary(snapshot[key]) and snapshot[key] != ""
    end)
  end

  defp parse_positive_int(value) when is_integer(value) and value > 0, do: {:ok, value}

  defp parse_positive_int(value) when is_binary(value) do
    case Integer.parse(String.trim(value)) do
      {integer, ""} when integer > 0 -> {:ok, integer}
      _ -> :error
    end
  end

  defp parse_positive_int(_), do: :error

  defp configured_positive_int(key, default) do
    key
    |> Settings.get(default)
    |> to_int(default)
    |> max(1)
  end

  defp to_int(value) when is_integer(value), do: value
  defp to_int(value) when is_binary(value), do: String.to_integer(value)
  defp to_int(%Decimal{} = value), do: value |> Decimal.to_integer()

  defp to_int(value, _default) when is_integer(value), do: value
  defp to_int(%Decimal{} = value, _default), do: Decimal.to_integer(value)

  defp to_int(value, default) when is_binary(value) do
    case Integer.parse(String.trim(value)) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  defp to_int(_, default), do: default

  defp to_float(value) when is_float(value), do: value
  defp to_float(value) when is_integer(value), do: value / 1
  defp to_float(%Decimal{} = value), do: Decimal.to_float(value)

  defp to_float(value) when is_binary(value) do
    case Float.parse(String.trim(value)) do
      {float, _} -> float
      _ -> 0.0
    end
  end

  defp to_float(_), do: 0.0
end
