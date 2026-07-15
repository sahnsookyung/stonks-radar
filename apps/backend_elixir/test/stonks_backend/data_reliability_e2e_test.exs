defmodule StonksBackend.DataReliabilityE2ETest do
  use ExUnit.Case, async: false

  @moduletag :db

  alias StonksBackend.{
    MarketData,
    Jobs.Workers.GenericWorker,
    Repo,
    ReleaseControls,
    Shorts,
    Snapshots,
    Sources,
    Sql
  }

  setup do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)

    release_id = "db-e2e-#{System.unique_integer([:positive])}"
    previous_release = System.get_env("STONKS_RELEASE_ID")
    System.put_env("STONKS_RELEASE_ID", release_id)

    root = Path.join(System.tmp_dir!(), "stonks-db-e2e-#{System.unique_integer([:positive])}")
    published_root = Path.join(root, "published")
    artifact_root = Path.join(root, "artifacts")
    previous_settings = Application.get_env(:stonks_backend, :settings, [])

    Application.put_env(
      :stonks_backend,
      :settings,
      Keyword.merge(previous_settings,
        published_snapshot_dir: published_root,
        snapshot_artifact_dir: artifact_root,
        snapshot_db_recording_enabled: false,
        yield_curve_history_enabled: "true"
      )
    )

    on_exit(fn ->
      cleanup_release_rows(release_id)
      restore_env("STONKS_RELEASE_ID", previous_release)
      Application.put_env(:stonks_backend, :settings, previous_settings)
      File.rm_rf!(root)
      checkin_repo()
    end)

    %{release_id: release_id, published_root: published_root, artifact_root: artifact_root}
  end

  test "runs a source-to-public-snapshot reliability path with rollout provenance", context do
    now = ~U[2026-07-02 22:30:00Z]

    seed_news_documents(context.release_id, now)

    assert {:ok, %{documents_seen: documents_seen}} =
             perform_worker_job(9101, "news.normalize_document", %{"limit" => 20})

    assert documents_seen >= 2

    assert {:ok, %{documents_classified: classified}} =
             perform_worker_job(9102, "news.classify_entities", %{"limit" => 20})

    assert classified >= 2

    assert {:ok, %{clusters_upserted: clusters_upserted}} =
             perform_worker_job(9103, "news.cluster_events", %{"limit" => 20})

    assert clusters_upserted >= 1

    assert {:ok, %{events_scored: scored}} =
             perform_worker_job(9104, "news.score_events", %{})

    assert scored >= 1

    assert %{"source_count" => source_count} = rklb_cluster()
    assert source_count >= 2

    assert %{"confidence" => confidence} =
             Sql.one("""
             select confidence
             from news_event_entity
             where entity_key = 'RKLB'
             order by confidence desc
             limit 1
             """)

    assert to_float(confidence) >= 0.75

    assert {:ok, %{persisted_count: 1}} =
             Shorts.fetch_daily_short_volume(
               %{"date" => "2026-07-02"},
               fetch_fun: fn _url ->
                 {:ok,
                  %{
                    "text" =>
                      "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n20260702|RKLB|800|0|1000|Q\n"
                  }}
               end,
               tracked_symbols: ["RKLB"],
               now: now
             )

    assert %{
             "object_json" => %{
               "release_id" => persisted_release_id,
               "ingestion_run_id" => run_id
             }
           } =
             Sql.one(
               "select object_json from source_fact where fact_type = 'short_volume' and object_json->>'release_id' = $1",
               [context.release_id]
             )

    assert persisted_release_id == context.release_id
    assert String.starts_with?(run_id, "ingestion:shorts:")

    assert {:ok, %{persisted_count: 1, settlement_date: "2026-06-30"}} =
             Shorts.fetch_short_interest_release(%{},
               tracked_symbols: ["RKLB"],
               partition_fetch_fun: fn ->
                 {:ok, %{"availablePartitions" => [%{"partitions" => ["2026-06-30"]}]}}
               end,
               data_fetch_fun: fn ~D[2026-06-30], ["RKLB"] ->
                 {:ok,
                  [
                    %{
                      "symbolCode" => "RKLB",
                      "issueName" => "Rocket Lab Corporation Common Stock",
                      "currentShortPositionQuantity" => 42_599_639,
                      "previousShortPositionQuantity" => 34_175_955,
                      "averageDailyVolumeQuantity" => 33_547_558,
                      "daysToCoverQuantity" => 1.27,
                      "changePercent" => 24.65,
                      "changePreviousNumber" => 8_423_684,
                      "settlementDate" => "2026-06-30"
                    }
                  ]}
               end
             )

    assert %{
             "extraction_source" => "rule",
             "object_json" => %{
               "short_interest" => 42_599_639,
               "release_id" => ^persisted_release_id
             }
           } =
             Sql.one(
               "select extraction_source, object_json from source_fact where fact_type = 'short_interest' and object_json->>'release_id' = $1",
               [context.release_id]
             )

    insert_market_bar!(context.release_id)

    assert {:ok, %{status: "ok", series: [%{points: points}]}} =
             MarketData.history("RKLB", "2026-07-01", "2026-07-02")

    assert Enum.map(points, & &1.date) == ["2026-07-01", "2026-07-02"]

    insert_yield_observation!(context.release_id)
    seed_snapshot!(context.published_root, now)

    assert {:ok, result} = Snapshots.build_candidate()
    assert result.destination == Path.join([context.artifact_root, "candidates", "v2", "public"])
    assert :ok = Snapshots.validate_snapshot_tree(result.destination)

    candidate_home =
      result.destination
      |> Path.join("v2/en/home.json")
      |> File.read!()
      |> Jason.decode!()

    assert Jason.encode!(candidate_home) =~ "FINRA daily short-sale volume"
    assert Jason.encode!(candidate_home) =~ "monthly sampled"

    release =
      ReleaseControls.admin_summary(
        scalar_fun: canary_scalar_fun(),
        one_fun: canary_one_fun(),
        all_fun: canary_all_fun()
      )

    assert release.release_id == context.release_id
    assert release.canary.status == "ready"
    assert release.provenance.release_id == context.release_id
    assert release.provenance.source_documents >= 2
    assert release.provenance.source_facts >= 2
    assert release.provenance.market_bars == 2
    assert release.provenance.quarantine_available
    assert release.source_funnel.totals["classified"] >= 2
    assert release.source_funnel.totals["clustered"] >= 1
  end

  defp start_repo do
    case Process.whereis(Repo) do
      nil -> {:ok, start_supervised!(Repo)}
      pid -> {:ok, pid}
    end
  end

  defp perform_worker_job(id, job_type, payload) do
    GenericWorker.perform(%Oban.Job{
      id: id,
      args: %{
        "job_type" => job_type,
        "payload" => payload,
        "payload_version" => ReleaseControls.payload_version()
      }
    })
  end

  defp checkin_repo do
    if Process.whereis(Repo) do
      Ecto.Adapters.SQL.Sandbox.checkin(Repo)
    end
  rescue
    _ -> :ok
  end

  defp seed_news_documents(release_id, now) do
    title = "Rocket Lab announces Iridium acquisition agreement for RKLB space systems"
    published_at = DateTime.to_iso8601(now)

    docs = [
      %{
        "title" => title,
        "url" => "https://www.rocketlabusa.com/news/#{release_id}/iridium-acquisition",
        "canonical_url" => "https://www.rocketlabusa.com/news/#{release_id}/iridium-acquisition",
        "published_at" => published_at,
        "language" => "en",
        "metadata" => %{
          "source_key" => "gdelt",
          "snippet" =>
            "Rocket Lab and Iridium acquisition agreement affects RKLB space launch cadence.",
          "trust_tier" => "T4_WEAK_SIGNAL",
          "discovery_only" => false,
          "source_region" => "USA",
          "gdelt_domain" => "rocketlabusa.com"
        }
      },
      %{
        "title" => title,
        "url" => "https://news.example.com/#{release_id}/rocket-lab-iridium",
        "canonical_url" => "https://news.example.com/#{release_id}/rocket-lab-iridium",
        "published_at" => published_at,
        "language" => "en",
        "metadata" => %{
          "source_key" => "google_news_rss",
          "snippet" =>
            "Rocket Lab acquisition agreement and $RKLB space systems update reported by an independent source.",
          "trust_tier" => "T3_REVIEWED_PUBLIC_SOURCE",
          "discovery_only" => false,
          "source_region" => "USA"
        }
      },
      %{
        "title" => title,
        "url" => "https://news.example.com/#{release_id}/rocket-lab-iridium?utm_source=duplicate",
        "canonical_url" => "https://news.example.com/#{release_id}/rocket-lab-iridium",
        "published_at" => published_at,
        "language" => "en",
        "metadata" => %{
          "source_key" => "gdelt",
          "snippet" => "Duplicate canonical URL should upsert, not create a third source row.",
          "trust_tier" => "T4_WEAK_SIGNAL",
          "discovery_only" => false,
          "source_region" => "USA"
        }
      }
    ]

    assert %{documents: 3} = Sources.persist_metadata_documents("gdelt", docs)

    assert Sql.scalar(
             """
             select count(*)
             from source_document
             where coalesce(metadata->>'release_id', metadata->'metadata'->>'release_id') = $1
             """,
             [release_id],
             0
           ) == 2
  end

  defp rklb_cluster do
    Sql.one("""
    select c.source_count
    from news_event_cluster c
    join news_event_entity e on e.event_id = c.id
    where e.entity_key = 'RKLB'
    order by c.last_seen_at desc
    limit 1
    """)
  end

  defp insert_market_bar!(release_id) do
    policy =
      Jason.encode!(%{
        "provider_key" => "test_provider",
        "endpoint_key" => "daily_prices",
        "raw_public_allowed" => true,
        "release_id" => release_id,
        "ingestion_run_id" => "ingestion:market:test:#{release_id}",
        "source_policy_version" => 1,
        "corporate_action_policy" => "test adjusted and unadjusted series are distinct"
      })

    Enum.each(
      [
        {"2026-07-01", "41.20", "4100"},
        {"2026-07-02", "42.10", "4200"}
      ],
      fn {date, close, volume} ->
        Sql.execute(
          """
          insert into market_price_bar(
            symbol, interval, price_date, provider_key, open, high, low, close,
            adjusted_close, volume, currency_code, timezone, provider_price_timestamp,
            source_hash, source_revision, is_adjusted, quality_state, quality_json,
            source_policy_json
          )
          values (
            'RKLB', '1day', $1::text::date, 'test_provider', $2::text::numeric, $2::text::numeric,
            $2::text::numeric, $2::text::numeric, $2::text::numeric, $3::text::numeric, 'USD', 'America/New_York',
            cast($1 || 'T00:00:00Z' as timestamptz), $4, $5, true, 'valid',
            '{"test":"db_e2e"}'::jsonb, $6::text::jsonb
          )
          on conflict (symbol, interval, price_date, provider_key) do update set
            close = excluded.close,
            source_policy_json = excluded.source_policy_json,
            quality_state = excluded.quality_state,
            updated_at = now()
          """,
          [
            date,
            close,
            volume,
            "sha256:market-#{release_id}-#{date}",
            "#{release_id}-#{date}",
            policy
          ]
        )
      end
    )
  end

  defp insert_yield_observation!(release_id) do
    observation = %{
      "country" => "USA",
      "tenor" => "10Y",
      "series_key" => "us_10y",
      "label" => "US Treasury 10Y",
      "value" => 4.21,
      "unit" => "%",
      "as_of_date" => "2026-07-02",
      "source" => "U.S. Treasury XML feed",
      "source_url" =>
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates",
      "adjustment_policy" => "official_unadjusted",
      "ingestion_run_id" => "ingestion:yield:test:#{release_id}",
      "release_id" => release_id,
      "source_policy_version" => 1
    }

    Sql.execute(
      """
      insert into source_fact(
        fact_type, predicate, object_json, time_reference, confidence,
        extraction_source, review_status, public_allowed, dedupe_key
      )
      values (
        'yield_curve_observation', 'reports', $1::text::jsonb, $2::text::jsonb, 0.95,
        'rule', 'approved', true, $3
      )
      on conflict (dedupe_key) where dedupe_key is not null do update set
        object_json = excluded.object_json,
        time_reference = excluded.time_reference,
        review_status = excluded.review_status,
        public_allowed = excluded.public_allowed
      """,
      [
        Jason.encode!(observation),
        Jason.encode!(%{"as_of_date" => "2026-07-02"}),
        "yield_curve:db-e2e:#{release_id}"
      ]
    )
  end

  defp seed_snapshot!(root, now) do
    write_json!(root, "latest/manifest.json", %{
      "current_version" => 1,
      "generated_at" => DateTime.to_iso8601(now),
      "locales" => ["en"],
      "objects" => %{"home" => %{"en" => "public/v1/en/home.json"}}
    })

    write_json!(root, "v1/en/home.json", %{
      "schema_version" => "1.0",
      "snapshot_version" => 1,
      "locale" => "en",
      "generated_at" => DateTime.to_iso8601(now),
      "stale_after" => now |> DateTime.add(3600, :second) |> DateTime.to_iso8601(),
      "hard_expires_at" => now |> DateTime.add(7200, :second) |> DateTime.to_iso8601(),
      "object_type" => "home",
      "object_key" => "home",
      "content_hash" => "sha256:test",
      "source_policy_versions" => [%{"source_key" => "seed", "policy_version" => 1}],
      "warnings" => [],
      "corrections" => [],
      "data" => %{
        "headline" => "Market radar",
        "summary" => "Source-backed market context.",
        "generated_label" => DateTime.to_iso8601(now),
        "snapshot_health" => %{},
        "top_events" => [],
        "breaking_market_events" => [],
        "breaking_market_map" => %{
          "events" => [],
          "map_points" => [],
          "watched_regions" => [],
          "coverage_gaps" => [],
          "regional_briefs" => [],
          "shown_count" => 0,
          "total_count" => 0,
          "ranking_cutoff" => nil,
          "registry_version" => 1,
          "scoring_version" => "test",
          "thinning_version" => "test",
          "generated_at" => DateTime.to_iso8601(now)
        },
        "macro_tiles" => [
          %{
            "key" => "us_10y",
            "label" => "US Treasury 10Y",
            "value" => "coverage gap",
            "unit" => "%",
            "source" => "U.S. Treasury XML feed",
            "source_url" =>
              "https://home.treasury.gov/resource-center/data-chart-center/interest-rates",
            "freshness" => "watch",
            "delay_label" => "official daily data pending cached observation",
            "updated_at" => DateTime.to_iso8601(now)
          }
        ],
        "alternative_signals" => [
          %{
            "key" => "short_volume_monitor",
            "title" => "Official daily short-sale volume",
            "summary" => "FINRA daily short-sale volume flow for tracked tickers.",
            "value" => "placeholder",
            "cadence" => "daily after FINRA publication",
            "source" => "FINRA daily short sale volume",
            "source_url" =>
              "https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data/daily-short-sale-volume-files",
            "freshness" => "watch",
            "severity" => "medium",
            "refresh_seconds" => 86_400,
            "items" => []
          }
        ],
        "sector_tiles" => [],
        "calendar_preview" => [],
        "scenario_baskets" => []
      }
    })
  end

  defp write_json!(root, relative_path, payload) do
    path = Path.join(root, relative_path)
    File.mkdir_p!(Path.dirname(path))
    File.write!(path, Jason.encode!(payload, pretty: true))
  end

  defp canary_scalar_fun do
    fn sql, params, default ->
      cond do
        sql =~ "from oban_jobs" -> 0
        sql =~ "from source_health_status" -> 0
        sql =~ "max(coalesce(published_at, generated_at))" -> 60
        sql =~ "operation_status" and params == ["public_p95_ms"] -> 120
        sql =~ "operation_status" and params == ["disk_watermark"] -> "info"
        sql =~ "content_hash" -> "abc123"
        true -> Sql.scalar(sql, params, default)
      end
    end
  end

  defp canary_one_fun do
    fn sql, params ->
      if sql =~ "provider_usage_event" do
        %{"total" => 0.0, "failed" => 0.0}
      else
        Sql.one(sql, params)
      end
    end
  end

  defp canary_all_fun do
    fn sql, params -> Sql.all(sql, params) end
  end

  defp cleanup_release_rows(release_id) do
    event_ids =
      Sql.all(
        """
        select distinct ed.event_id
        from news_event_document ed
        join source_document d on d.id = ed.document_id
        where d.metadata->>'release_id' = $1
        """,
        [release_id]
      )
      |> Enum.map(& &1["event_id"])

    if event_ids != [] do
      Sql.execute("delete from news_event_topic where event_id = any($1)", [event_ids])
      Sql.execute("delete from news_event_region where event_id = any($1)", [event_ids])
      Sql.execute("delete from news_event_entity where event_id = any($1)", [event_ids])
      Sql.execute("delete from news_event_document where event_id = any($1)", [event_ids])
      Sql.execute("delete from news_event_cluster where id = any($1)", [event_ids])
    end

    Sql.execute(
      "delete from source_document where coalesce(metadata->>'release_id', metadata->'metadata'->>'release_id') = $1",
      [release_id]
    )

    Sql.execute("delete from source_fact where object_json->>'release_id' = $1", [release_id])

    Sql.execute("delete from market_price_bar where source_policy_json->>'release_id' = $1", [
      release_id
    ])
  rescue
    _ -> :ok
  end

  defp restore_env(key, nil), do: System.delete_env(key)
  defp restore_env(key, value), do: System.put_env(key, value)

  defp to_float(value) when is_float(value), do: value
  defp to_float(value) when is_integer(value), do: value * 1.0
  defp to_float(%Decimal{} = value), do: Decimal.to_float(value)

  defp to_float(value) do
    case Float.parse(to_string(value)) do
      {parsed, _rest} -> parsed
      :error -> 0.0
    end
  end
end
