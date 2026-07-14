defmodule StonksBackend.SnapshotsTest do
  use ExUnit.Case, async: false

  alias StonksBackend.{Repo, Snapshots, Sql}

  setup do
    root = Path.join(System.tmp_dir!(), "stonks-snapshots-#{System.unique_integer([:positive])}")
    published_root = Path.join(root, "published")
    artifact_root = Path.join(root, "artifacts")
    previous_settings = Application.get_env(:stonks_backend, :settings, [])

    Application.put_env(
      :stonks_backend,
      :settings,
      Keyword.merge(previous_settings,
        published_snapshot_dir: published_root,
        snapshot_artifact_dir: artifact_root,
        snapshot_db_recording_enabled: false
      )
    )

    on_exit(fn ->
      Application.put_env(:stonks_backend, :settings, previous_settings)
      File.rm_rf!(root)
    end)

    %{published_root: published_root, artifact_root: artifact_root}
  end

  test "snapshot API paths preserve the public manifest contract" do
    assert Snapshots.manifest_path() == Path.join(["latest", "manifest.json"])
    assert Snapshots.public_manifest_key() == "public/latest/manifest.json"
    assert Snapshots.public_manifest_url() == "/public/latest/manifest.json"
  end

  test "candidate root preserves local artifact shape", %{artifact_root: artifact_root} do
    assert Snapshots.candidate_root(7) == Path.join([artifact_root, "candidates", "v7", "public"])
  end

  test "manifest status handles the published manifest file timestamp", %{published_root: root} do
    write_manifest!(root)

    assert %{age_minutes: age_minutes, generated_at: generated_at} = Snapshots.manifest_status()
    assert is_number(age_minutes)
    assert is_binary(generated_at)
  end

  test "default candidate build refreshes the public snapshot template tree", %{
    published_root: root,
    artifact_root: artifact_root
  } do
    write_manifest!(root, %{
      "corrections" => %{"en" => "public/v1/en/corrections.json"}
    })

    write_snapshot!(root, "v1/en/corrections.json", %{
      "object_type" => "correction_log",
      "object_key" => "corrections",
      "data" => %{"entries" => []}
    })

    assert {:ok, result} = Snapshots.build_candidate()
    assert result.snapshot_version == 2
    assert result.destination == Path.join([artifact_root, "candidates", "v2", "public"])

    assert Path.join(result.destination, "latest/manifest.json") |> File.exists?()
    assert Path.join(result.destination, "v2/en/corrections.json") |> File.exists?()

    manifest =
      result.destination
      |> Path.join("latest/manifest.json")
      |> File.read!()
      |> Jason.decode!()

    assert manifest["objects"]["corrections"]["en"] == "public/v2/en/corrections.json"

    snapshot =
      result.destination
      |> Path.join("v2/en/corrections.json")
      |> File.read!()
      |> Jason.decode!()

    assert snapshot["snapshot_version"] == 2
    assert snapshot["min_reader_version"] == "1.0"
    assert snapshot["content_hash"] =~ "sha256:"
    assert snapshot["stale_after"] != snapshot["generated_at"]
    assert :ok = Snapshots.validate_snapshot_tree(result.destination)
  end

  @tag :db
  test "candidate DB recording treats system requested_by labels as anonymous", %{
    published_root: root
  } do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)

    Application.put_env(
      :stonks_backend,
      :settings,
      Keyword.put(
        Application.get_env(:stonks_backend, :settings, []),
        :snapshot_db_recording_enabled,
        true
      )
    )

    write_manifest!(root, %{
      "corrections" => %{"en" => "public/v1/en/corrections.json"}
    })

    write_snapshot!(root, "v1/en/corrections.json", %{
      "object_type" => "correction_log",
      "object_key" => "corrections",
      "data" => %{"entries" => []}
    })

    on_exit(fn -> checkin_repo() end)

    assert {:ok, %{snapshot_version: snapshot_version}} =
             Snapshots.build_candidate(%{"requested_by" => "deploy"})

    assert %{"generated_by" => nil} =
             Sql.one(
               "select generated_by from publication_manifest where snapshot_version = $1",
               [snapshot_version]
             )

    assert %{"generated_by" => nil} =
             Sql.one(
               """
               select generated_by
               from publication_snapshot
               where snapshot_version = $1 and object_key = 'corrections'
               """,
               [snapshot_version]
             )
  end

  test "snapshot tree validation accepts envelope files and rejects private fields", %{
    published_root: root
  } do
    write_manifest!(root)
    write_snapshot!(root, "v1/en/home.json", %{"data" => %{"entries" => []}})

    assert :ok = Snapshots.validate_snapshot_tree(root)

    write_snapshot!(root, "v1/en/home.json", %{"data" => %{"entries" => [], "secret" => "nope"}})

    assert {:error, message} = Snapshots.validate_snapshot_tree(root)
    assert message =~ "prohibited public field secret"
  end

  test "snapshot tree validation uses shared Draft 2020-12 schemas", %{published_root: root} do
    write_manifest!(root)
    write_snapshot!(root, "v1/en/home.json", %{"data" => %{}})

    assert {:error, message} = Snapshots.validate_snapshot_tree(root)
    assert message =~ "failed snapshot schema validation"
    assert message =~ "entries"
  end

  test "snapshot validation requires news claim classification fields", %{published_root: root} do
    write_manifest!(root, %{
      "news_index" => %{"en" => "public/v1/en/news/index.json"}
    })

    write_snapshot!(root, "v1/en/news/index.json", %{
      "object_type" => "news_index",
      "object_key" => "news_index",
      "data" => %{
        "generated_label" => "2026-07-01T12:00:00Z",
        "filters" => empty_news_filters(),
        "events" => [news_event("missing_claim_fields", DateTime.utc_now(), %{})]
      }
    })

    assert {:error, message} = Snapshots.validate_snapshot_tree(root)
    assert message =~ "failed snapshot schema validation"
    assert message =~ "item_kind"
  end

  test "map events snapshot fixture covers enriched map contract", %{published_root: root} do
    timestamp = ~U[2026-07-05 09:15:00Z]
    timestamp_iso = DateTime.to_iso8601(timestamp)
    map_point = map_point("shipping_watch", timestamp)

    write_manifest!(root, %{
      "map_events" => %{"en" => "public/v1/en/map_events.json"}
    })

    write_snapshot!(root, "v1/en/map_events.json", %{
      "object_type" => "map_events",
      "object_key" => "map_events",
      "generated_at" => timestamp_iso,
      "data" => %{
        "events" => [],
        "breaking_market_events" => [
          breaking_event("shipping_watch", timestamp, %{
            "geo_points" => [map_point],
            "regions" => [
              %{
                "key" => "USA",
                "name" => "United States",
                "relation" => "event_region",
                "confidence" => 0.9
              }
            ],
            "topics" => [%{"key" => "shipping", "label" => "Shipping", "confidence" => 0.8}],
            "tickers" => [
              %{
                "symbol" => "FDX",
                "name" => "FedEx",
                "relationship" => "affected_company",
                "confidence" => 0.7
              }
            ]
          })
        ],
        "breaking_market_map" => %{
          "events" => [
            breaking_event("shipping_watch", timestamp, %{"geo_points" => [map_point]})
          ],
          "map_points" => [map_point],
          "watched_regions" => [
            %{
              "key" => "USA",
              "type" => "country",
              "label" => "United States",
              "iso3" => "USA",
              "natural_earth_names" => ["United States of America"],
              "groups" => ["g7"],
              "priority" => 95,
              "gdp_rank" => 1,
              "gather_news" => true,
              "render_on_map" => true,
              "nav_visible" => true,
              "coverage_status" => "active",
              "coverage_window_days" => 7,
              "event_count" => 1,
              "map_point_count" => 1,
              "newest_source_published_at" => timestamp_iso,
              "quiet_reason" => nil
            }
          ],
          "coverage_gaps" => [
            %{
              "region_key" => "strait_of_hormuz",
              "label" => "Strait of Hormuz",
              "reason" => "no_recent_evidence",
              "coverage_window_days" => 7,
              "newest_source_published_at" => nil
            }
          ],
          "regional_briefs" => [
            %{
              "region_key" => "USA",
              "label" => "United States",
              "coverage_window_days" => 7,
              "generated_at" => timestamp_iso,
              "summary" => "Source-linked regional brief for the enriched map contract.",
              "event_count" => 1,
              "source_count" => 1,
              "newest_source_published_at" => timestamp_iso,
              "evidence" => [
                %{
                  "event_id" => "shipping_watch",
                  "title" => "Reviewed market update",
                  "source_url" => "https://example.com/shipping_watch",
                  "source_published_at" => timestamp_iso,
                  "severity" => "high"
                }
              ],
              "confidence" => "source_linked"
            }
          ],
          "shown_count" => 1,
          "total_count" => 1,
          "ranking_cutoff" => nil,
          "registry_version" => 1,
          "scoring_version" => "test",
          "thinning_version" => "test",
          "generated_at" => timestamp_iso
        },
        "filters" => %{
          "countries_regions" => ["USA"],
          "sectors" => ["shipping"],
          "severities" => ["high"],
          "event_types" => ["market_news"]
        }
      }
    })

    assert :ok = Snapshots.validate_snapshot_tree(root)
    assert String.ends_with?(timestamp_iso, "Z")
  end

  test "snapshot validation rejects placeholder wording in public display fields", %{
    published_root: root
  } do
    write_manifest!(root, %{
      "news_index" => %{"en" => "public/v1/en/news/index.json"}
    })

    write_snapshot!(root, "v1/en/news/index.json", %{
      "object_type" => "news_index",
      "object_key" => "news_index",
      "data" => %{
        "generated_label" => "2026-07-01T12:00:00Z",
        "filters" => empty_news_filters(),
        "events" => [
          news_event("source_watch", DateTime.utc_now(), %{
            "title" => "The seed event demonstrates ticker-level grouping",
            "item_kind" => "source_discovery",
            "claim_level" => "source_only",
            "evidence_match_status" => "weak_match"
          })
        ]
      }
    })

    assert {:error, message} = Snapshots.validate_snapshot_tree(root)
    assert message =~ "contains prohibited placeholder display text"
  end

  test "candidate build enriches news claims, windows, and configured ticker facets", %{
    published_root: root,
    artifact_root: artifact_root
  } do
    now = DateTime.utc_now()
    recent = DateTime.add(now, -2, :hour)
    two_days_old = DateTime.add(now, -2, :day)
    eight_days_old = DateTime.add(now, -8, :day)
    thirty_one_days_old = DateTime.add(now, -31, :day)

    write_manifest!(root, %{
      "news_index" => %{"en" => "public/v1/en/news/index.json"},
      "news_ticker_RKLB" => %{"en" => "public/v1/en/news/tickers/RKLB.json"}
    })

    write_snapshot!(root, "v1/en/news/index.json", %{
      "object_type" => "news_index",
      "object_key" => "news_index",
      "data" => %{
        "generated_label" => DateTime.to_iso8601(now),
        "filters" => empty_news_filters(),
        "events" => [
          news_event("rklb_launch_window_seed", recent, %{
            "title" =>
              "Rocket Lab launch-window monitoring is linked to source evidence for RKLB",
            "summary" =>
              "Company and filing sources are grouped into a ticker-specific event for Rocket Lab launch-cadence monitoring."
          }),
          news_event("analysis_window_source", two_days_old, %{
            "title" => "Rocket Lab source-linked filing context",
            "freshness" => "fresh"
          }),
          news_event("stale_source_discovery", thirty_one_days_old, %{})
        ]
      }
    })

    write_snapshot!(root, "v1/en/news/tickers/RKLB.json", %{
      "object_type" => "news_ticker",
      "object_key" => "news_ticker_RKLB",
      "data" => %{
        "symbol" => "RKLB",
        "name" => "Rocket Lab",
        "generated_label" => DateTime.to_iso8601(now),
        "summary" => "Rocket Lab source-linked items.",
        "events" => [
          news_event("rklb_launch_window_seed", recent, %{}),
          news_event("old_rklb_source_discovery", eight_days_old, %{})
        ]
      }
    })

    assert {:ok, result} = Snapshots.build_candidate()
    assert result.destination == Path.join([artifact_root, "candidates", "v2", "public"])

    index =
      result.destination
      |> Path.join("v2/en/news/index.json")
      |> File.read!()
      |> Jason.decode!()

    assert index["data"]["coverage_window"] == "30d"

    assert index["source_policy_versions"] == [
             %{"source_key" => "snapshot", "policy_version" => 1}
           ]

    refute Enum.any?(index["data"]["events"], &(&1["id"] == "stale_source_discovery"))
    refute Jason.encode!(index["data"]) =~ "seed event"
    refute Jason.encode!(index["data"]) =~ "Source policy seed"
    refute Jason.encode!(index["data"]) =~ "source-linked news event"

    assert %{"freshness" => "watch"} =
             Enum.find(index["data"]["events"], &(&1["id"] == "analysis_window_source"))

    assert %{
             "title" => "Rocket Lab source links for RKLB filings and company updates",
             "freshness" => "fresh",
             "summary" => summary,
             "item_kind" => "source_discovery",
             "claim_level" => "source_only",
             "evidence_match_status" => "weak_match",
             "source_links" => [%{"evidence_id" => "doc_" <> evidence_hash}]
           } = Enum.find(index["data"]["events"], &(&1["id"] == "rklb_launch_window_seed"))

    assert summary =~ "not a verified launch-window event"
    assert String.length(evidence_hash) == 24

    assert %{"count" => 0} =
             Enum.find(index["data"]["filters"]["tickers"], &(&1["key"] == "AMD"))

    ticker =
      result.destination
      |> Path.join("v2/en/news/tickers/RKLB.json")
      |> File.read!()
      |> Jason.decode!()

    assert ticker["data"]["coverage_window"] == "7d"
    assert Enum.map(ticker["data"]["events"], & &1["id"]) == ["rklb_launch_window_seed"]
    refute ticker["data"]["summary"] =~ "source-linked news event"
    assert :ok = Snapshots.validate_snapshot_tree(result.destination)
  end

  test "candidate build keeps source-only discovery out of breaking map surfaces", %{
    published_root: root,
    artifact_root: artifact_root
  } do
    now = DateTime.utc_now() |> DateTime.truncate(:second)

    write_manifest!(root, %{
      "home" => %{"en" => "public/v1/en/home.json"}
    })

    write_snapshot!(root, "v1/en/home.json", %{
      "object_type" => "home",
      "object_key" => "home",
      "data" => %{
        "headline" => "Market radar",
        "summary" => "Source-backed market context.",
        "generated_label" => DateTime.to_iso8601(now),
        "snapshot_health" => %{},
        "top_events" => [],
        "breaking_market_events" => [
          breaking_event("source_only", now, %{
            "title" => "Weak source discovery",
            "discovery_only" => true,
            "trust_tier" => "T4_WEAK_SIGNAL"
          }),
          breaking_event("reviewed_event", now, %{
            "title" => "Reviewed official update",
            "discovery_only" => false,
            "trust_tier" => "T1_REGULATED_FILING"
          })
        ],
        "breaking_market_map" => %{
          "events" => [
            breaking_event("source_only", now, %{
              "title" => "Weak source discovery",
              "discovery_only" => true,
              "trust_tier" => "T4_WEAK_SIGNAL"
            }),
            breaking_event("reviewed_event", now, %{
              "title" => "Reviewed official update",
              "discovery_only" => false,
              "trust_tier" => "T1_REGULATED_FILING"
            })
          ],
          "map_points" => [
            map_point("source_only", now),
            map_point("reviewed_event", now)
          ],
          "watched_regions" => [],
          "coverage_gaps" => [],
          "regional_briefs" => [
            %{
              "region_key" => "USA",
              "label" => "United States",
              "coverage_window_days" => 7,
              "generated_at" => DateTime.to_iso8601(now),
              "summary" =>
                "United States has 99 source-linked breaking/developing event(s) in the current metadata window.",
              "event_count" => 99,
              "source_count" => 99,
              "newest_source_published_at" => DateTime.to_iso8601(now),
              "confidence" => "metadata_only",
              "evidence" => [
                %{
                  "event_id" => "reviewed_event",
                  "title" => "Reviewed official update",
                  "source_url" => "https://example.com/reviewed_event",
                  "source_published_at" => DateTime.to_iso8601(now),
                  "severity" => "high"
                },
                %{
                  "event_id" => "source_only",
                  "title" => "Weak source discovery",
                  "source_url" => "https://example.com/source_only",
                  "source_published_at" => DateTime.to_iso8601(DateTime.add(now, -60, :second)),
                  "severity" => "medium"
                }
              ]
            }
          ],
          "shown_count" => 2,
          "total_count" => 2,
          "ranking_cutoff" => nil,
          "registry_version" => 1,
          "scoring_version" => "test",
          "thinning_version" => "test",
          "generated_at" => DateTime.to_iso8601(now)
        },
        "macro_tiles" => [],
        "alternative_signals" => [
          %{
            "key" => "breaking_market_news",
            "title" => "Breaking market news",
            "summary" => "Fresh source-linked items only.",
            "value" => "2 items",
            "cadence" => "24h",
            "source" => "source-linked news",
            "source_url" => "https://example.com/news",
            "freshness" => "fresh",
            "severity" => "medium",
            "refresh_seconds" => 3600,
            "items" => [
              %{
                "key" => "fresh",
                "label" => "Fresh reviewed update",
                "value" => "fresh",
                "detail" => "Within the breaking news window.",
                "source" => "source-linked news",
                "freshness" => "fresh",
                "severity" => "medium",
                "updated_at" => DateTime.to_iso8601(now)
              },
              %{
                "key" => "stale",
                "label" => "Stale reviewed update",
                "value" => "stale",
                "detail" => "Outside the breaking news window.",
                "source" => "source-linked news",
                "freshness" => "stale",
                "severity" => "medium",
                "updated_at" => now |> DateTime.add(-49, :hour) |> DateTime.to_iso8601()
              }
            ]
          }
        ],
        "sector_tiles" => [],
        "calendar_preview" => [],
        "scenario_baskets" => []
      }
    })

    assert {:ok, result} = Snapshots.build_candidate()
    assert result.destination == Path.join([artifact_root, "candidates", "v2", "public"])

    home =
      result.destination
      |> Path.join("v2/en/home.json")
      |> File.read!()
      |> Jason.decode!()

    assert Enum.map(home["data"]["breaking_market_events"], & &1["event_id"]) == [
             "reviewed_event"
           ]

    assert Enum.map(home["data"]["breaking_market_map"]["events"], & &1["event_id"]) == [
             "reviewed_event"
           ]

    assert Enum.map(home["data"]["breaking_market_map"]["map_points"], & &1["event_id"]) == [
             "reviewed_event"
           ]

    assert home["data"]["breaking_market_map"]["shown_count"] == 1
    assert home["data"]["breaking_market_map"]["total_count"] == 1

    assert [
             %{
               "summary" =>
                 "United States has 2 source-linked item(s) in the 7-day metadata window.",
               "event_count" => 2,
               "source_count" => 2,
               "evidence" => [%{"event_id" => "reviewed_event"}, %{"event_id" => "source_only"}]
             }
           ] = home["data"]["breaking_market_map"]["regional_briefs"]

    refute Jason.encode!(home["data"]["breaking_market_map"]["regional_briefs"]) =~
             "breaking/developing event"

    assert Enum.map(hd(home["data"]["alternative_signals"])["items"], & &1["key"]) == ["fresh"]
    assert :ok = Snapshots.validate_snapshot_tree(result.destination)
  end

  test "map events snapshot backfills mappable news index rows without changing public paths", %{
    published_root: root,
    artifact_root: artifact_root
  } do
    now = DateTime.utc_now() |> DateTime.truncate(:second)

    write_manifest!(root, %{
      "news_index" => %{"en" => "public/v1/en/news/index.json"},
      "map_events" => %{"en" => "public/v1/en/map/events.json"}
    })

    write_snapshot!(root, "v1/en/news/index.json", %{
      "object_type" => "news_index",
      "object_key" => "news_index",
      "data" => %{
        "generated_label" => DateTime.to_iso8601(now),
        "filters" => empty_news_filters(),
        "events" => [
          news_event("semiconductor_export_controls_seed", DateTime.add(now, -2, :day), %{
            "event_type" => "trade_policy",
            "severity" => "high",
            "source_count" => 3,
            "topics" => [
              %{"key" => "semiconductors", "label" => "Semiconductors", "confidence" => 0.92}
            ],
            "regions" => [
              %{
                "key" => "CHN",
                "name" => "China",
                "relation" => "event_region",
                "confidence" => 0.92
              },
              %{
                "key" => "USA",
                "name" => "United States",
                "relation" => "affected_region",
                "confidence" => 0.86
              }
            ]
          })
        ]
      }
    })

    write_snapshot!(root, "v1/en/map/events.json", %{
      "object_type" => "map_events",
      "object_key" => "map_events",
      "data" => %{
        "events" => [
          %{
            "id" => "legacy_static_marker",
            "latitude" => 37.5,
            "longitude" => -96.0
          }
        ],
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
        "filters" => %{
          "countries_regions" => [],
          "sectors" => [],
          "severities" => ["low", "medium", "high", "critical"],
          "event_types" => []
        }
      }
    })

    assert {:ok, result} = Snapshots.build_candidate()
    assert result.destination == Path.join([artifact_root, "candidates", "v2", "public"])

    manifest =
      result.destination
      |> Path.join("latest/manifest.json")
      |> File.read!()
      |> Jason.decode!()

    assert manifest["objects"]["map_events"]["en"] == "public/v2/en/map/events.json"

    map =
      result.destination
      |> Path.join("v2/en/map/events.json")
      |> File.read!()
      |> Jason.decode!()

    assert map["data"]["events"] == []

    assert [%{"event_id" => "semiconductor_export_controls_seed"}] =
             map["data"]["breaking_market_events"]

    assert Enum.map(map["data"]["breaking_market_map"]["map_points"], & &1["area_key"]) == [
             "USA",
             "CHN"
           ]

    assert map["data"]["breaking_market_map"]["shown_count"] == 2
    assert "semiconductors" in map["data"]["filters"]["sectors"]
    assert "trade_policy" in map["data"]["filters"]["event_types"]

    assert "source_linked_news" in hd(map["data"]["breaking_market_map"]["map_points"])[
             "score_reason_codes"
           ]

    assert :ok = Snapshots.validate_snapshot_tree(result.destination)
  end

  test "snapshot tree validation rejects public operational status snapshots", %{
    published_root: root
  } do
    write_manifest!(root, %{
      "source_status" => %{"en" => "public/v1/en/status.json"}
    })

    write_snapshot!(root, "v1/en/status.json", %{
      "object_type" => "source_status",
      "object_key" => "source_status",
      "data" => %{"providers" => []}
    })

    assert {:error, message} = Snapshots.validate_snapshot_tree(root)
    assert message =~ "references prohibited public operational snapshot"

    write_manifest!(root, %{
      "home" => %{"en" => "public/v1/en/status.json"}
    })

    assert {:error, message} = Snapshots.validate_snapshot_tree(root)
    assert message =~ "contains prohibited public operational snapshot"
  end

  test "snapshot tree validation rejects public internal source identifiers", %{
    published_root: root
  } do
    write_manifest!(root)

    write_snapshot!(root, "v1/en/home.json", %{
      "data" => %{
        "source_document_id" => "2aa2e34a-4b6d-4b6e-b224-268dcdd50810",
        "fact_id" => "raw-internal-fact",
        "article_body" => "full article body must not publish",
        "provider_status" => %{"quota_state" => "private"}
      }
    })

    assert {:error, message} = Snapshots.validate_snapshot_tree(root)
    assert message =~ "contains prohibited public field"
  end

  test "snapshot tree validation requires manifest references to resolve inside the tree", %{
    published_root: root
  } do
    write_snapshot!(root, "v1/en/home.json", %{"data" => %{"entries" => []}})

    assert {:error, message} = Snapshots.validate_snapshot_tree(root)
    assert message =~ "missing latest/manifest.json"

    write_manifest!(root, %{
      "home" => %{"en" => "public/v1/en/missing.json"}
    })

    assert {:error, message} = Snapshots.validate_snapshot_tree(root)
    assert message =~ "references missing snapshot public/v1/en/missing.json"

    write_snapshot!(root, "v1/en/home.json", %{"locale" => "ko", "data" => %{"entries" => []}})
    write_manifest!(root)

    assert {:error, message} = Snapshots.validate_snapshot_tree(root)
    assert message =~ "references locale-mismatched snapshot public/v1/en/home.json"

    write_manifest!(root, %{
      "home" => %{"en" => "public/../outside.json"}
    })

    assert {:error, message} = Snapshots.validate_snapshot_tree(root)
    assert message =~ "unsafe snapshot path public/../outside.json"
  end

  test "published-volume refresh copies files and leaves manifest at the semantic path", %{
    published_root: destination
  } do
    source = Path.join(System.tmp_dir!(), "stonks-source-#{System.unique_integer([:positive])}")

    try do
      write_manifest!(source)
      write_snapshot!(source, "v1/en/home.json", %{"data" => %{"entries" => []}})

      assert {:ok, result} = Snapshots.refresh_published_volume(source, destination)

      assert result.destination == destination
      assert Path.join(destination, "latest/manifest.json") |> File.exists?()
      assert Path.join(destination, "v1/en/home.json") |> File.exists?()

      assert result.files == [
               Path.join(source, "latest/manifest.json"),
               Path.join(source, "v1/en/home.json")
             ]
    after
      File.rm_rf!(source)
    end
  end

  test "published-volume refresh removes stale files from previous versions", %{
    published_root: destination
  } do
    source = Path.join(System.tmp_dir!(), "stonks-source-#{System.unique_integer([:positive])}")

    try do
      write_manifest!(source, %{"home" => %{"en" => "public/v2/en/home.json"}})
      write_snapshot!(source, "v2/en/home.json", %{"data" => %{"entries" => []}})

      write_manifest!(destination, %{"home" => %{"en" => "public/v1/en/home.json"}})
      write_snapshot!(destination, "v1/en/home.json", %{"data" => %{"entries" => []}})
      write_snapshot!(destination, "v1/en/news/index.json", %{"data" => %{"entries" => []}})

      assert {:ok, _result} = Snapshots.refresh_published_volume(source, destination)

      assert Path.join(destination, "latest/manifest.json") |> File.exists?()
      assert Path.join(destination, "v2/en/home.json") |> File.exists?()
      refute Path.join(destination, "v1/en/home.json") |> File.exists?()
      refute Path.join(destination, "v1/en/news/index.json") |> File.exists?()
    after
      File.rm_rf!(source)
    end
  end

  test "published-volume refresh validates source before changing destination", %{
    published_root: destination
  } do
    source = Path.join(System.tmp_dir!(), "stonks-source-#{System.unique_integer([:positive])}")

    try do
      write_manifest!(source)

      write_snapshot!(source, "v1/en/home.json", %{
        "data" => %{"entries" => [], "secret" => "nope"}
      })

      write_json!(destination, "v1/en/home.json", %{"data" => %{"headline" => "old"}})

      assert {:error, message} = Snapshots.refresh_published_volume(source, destination)
      assert message =~ "prohibited public field secret"

      assert %{"data" => %{"headline" => "old"}} =
               destination
               |> Path.join("v1/en/home.json")
               |> File.read!()
               |> Jason.decode!()
    after
      File.rm_rf!(source)
    end
  end

  test "published-volume refresh does not reuse stale fixed temp paths", %{
    published_root: destination
  } do
    source = Path.join(System.tmp_dir!(), "stonks-source-#{System.unique_integer([:positive])}")

    try do
      write_manifest!(source)
      write_snapshot!(source, "v1/en/home.json", %{"data" => %{"entries" => []}})

      File.mkdir_p!(Path.join(destination, "latest/.manifest.json.tmp"))
      File.mkdir_p!(Path.join(destination, "v1/en/.home.json.tmp"))

      assert {:ok, _result} = Snapshots.refresh_published_volume(source, destination)
      assert Path.join(destination, "latest/manifest.json") |> File.exists?()
      assert Path.join(destination, "v1/en/home.json") |> File.exists?()
    after
      File.rm_rf!(source)
    end
  end

  test "published-volume refresh requires a manifest and enforces file limits", %{
    published_root: destination,
    artifact_root: artifact_root
  } do
    missing_manifest_source = Path.join(artifact_root, "missing-manifest")

    write_snapshot!(missing_manifest_source, "v1/en/home.json", %{"data" => %{"entries" => []}})

    assert {:error, message} =
             Snapshots.refresh_published_volume(missing_manifest_source, destination)

    assert message =~ "missing latest/manifest.json"

    limited_source = Path.join(artifact_root, "limited")
    write_manifest!(limited_source)
    write_snapshot!(limited_source, "v1/en/home.json", %{"data" => %{"entries" => []}})

    previous_settings = Application.get_env(:stonks_backend, :settings, [])

    try do
      Application.put_env(
        :stonks_backend,
        :settings,
        Keyword.merge(previous_settings, snapshot_publish_max_files: 1)
      )

      assert {:error, message} = Snapshots.refresh_published_volume(limited_source, destination)
      assert message =~ "exceeds file limit 1"
    after
      Application.put_env(:stonks_backend, :settings, previous_settings)
    end
  end

  test "published-volume refresh rejects non-regular source files", %{
    published_root: destination
  } do
    source = Path.join(System.tmp_dir!(), "stonks-source-#{System.unique_integer([:positive])}")

    outside =
      Path.join(System.tmp_dir!(), "stonks-secret-#{System.unique_integer([:positive])}.txt")

    try do
      write_manifest!(source)
      write_snapshot!(source, "v1/en/home.json", %{"data" => %{"entries" => []}})
      File.write!(outside, "do not publish")
      :ok = File.ln_s(outside, Path.join(source, "v1/en/leak.txt"))

      assert {:error, message} = Snapshots.refresh_published_volume(source, destination)
      assert message =~ "contains non-regular file"
      refute Path.join(destination, "v1/en/leak.txt") |> File.exists?()
    after
      File.rm_rf!(source)
      File.rm(outside)
    end
  end

  test "published-volume refresh restores overwritten files if a later copy fails", %{
    published_root: destination
  } do
    source = Path.join(System.tmp_dir!(), "stonks-source-#{System.unique_integer([:positive])}")

    try do
      write_manifest!(source)
      write_snapshot!(source, "v1/en/home.json", %{"data" => %{"entries" => []}})
      write_snapshot!(source, "v1/en/secondary.json", %{"data" => %{"entries" => []}})

      write_json!(destination, "v1/en/home.json", %{"data" => %{"headline" => "old"}})
      File.mkdir_p!(Path.join(destination, "v1/en/secondary.json"))

      assert {:error, message} = Snapshots.refresh_published_volume(source, destination)
      assert message =~ "Could not back up"

      assert %{"data" => %{"headline" => "old"}} =
               destination
               |> Path.join("v1/en/home.json")
               |> File.read!()
               |> Jason.decode!()

      refute Path.join(destination, "latest/manifest.json") |> File.exists?()
    after
      File.rm_rf!(source)
    end
  end

  test "snapshot publish payload rejects invalid versions without raising" do
    assert Snapshots.publish_from_payload(%{"snapshot_version" => "not-an-int"}) ==
             {:error, "snapshot_publish requires positive snapshot_version"}

    assert Snapshots.publish_from_payload(%{"snapshot_version" => "0"}) ==
             {:error, "snapshot_publish requires positive snapshot_version"}
  end

  test "snapshot version parser accepts only positive integer values" do
    assert Snapshots.parse_positive_snapshot_version(3) == {:ok, 3}
    assert Snapshots.parse_positive_snapshot_version(" 3 ") == {:ok, 3}

    assert Snapshots.parse_positive_snapshot_version("not-an-int") == :error
    assert Snapshots.parse_positive_snapshot_version("3abc") == :error
    assert Snapshots.parse_positive_snapshot_version("0") == :error
    assert Snapshots.parse_positive_snapshot_version(-1) == :error
  end

  defp write_manifest!(root, objects \\ %{"home" => %{"en" => "public/v1/en/home.json"}}) do
    write_json!(root, "latest/manifest.json", %{
      "current_version" => 1,
      "generated_at" => DateTime.utc_now() |> DateTime.to_iso8601(),
      "locales" => ["en"],
      "objects" => objects
    })
  end

  defp write_snapshot!(root, relative_path, overrides) do
    base = %{
      "schema_version" => "1.0",
      "snapshot_version" => 1,
      "locale" => "en",
      "generated_at" => DateTime.utc_now() |> DateTime.to_iso8601(),
      "stale_after" => DateTime.utc_now() |> DateTime.add(3600, :second) |> DateTime.to_iso8601(),
      "hard_expires_at" =>
        DateTime.utc_now() |> DateTime.add(7200, :second) |> DateTime.to_iso8601(),
      "object_type" => "correction_log",
      "object_key" => "corrections",
      "content_hash" => "sha256:test",
      "source_policy_versions" => [%{"source_key" => "seed", "policy_version" => 1}],
      "data" => %{},
      "warnings" => [],
      "corrections" => []
    }

    write_json!(root, relative_path, deep_merge(base, overrides))
  end

  defp write_json!(root, relative_path, payload) do
    path = Path.join(root, relative_path)
    File.mkdir_p!(Path.dirname(path))
    File.write!(path, Jason.encode!(payload))
  end

  defp start_repo do
    case Process.whereis(Repo) do
      nil -> {:ok, start_supervised!(Repo)}
      pid -> {:ok, pid}
    end
  end

  defp checkin_repo do
    if Process.whereis(Repo) do
      Ecto.Adapters.SQL.Sandbox.checkin(Repo)
    end
  rescue
    _ -> :ok
  end

  defp empty_news_filters do
    %{
      "regions" => [],
      "topics" => [],
      "tickers" => [],
      "trust_tiers" => []
    }
  end

  defp news_event(id, timestamp, overrides) do
    timestamp = timestamp |> DateTime.truncate(:second) |> DateTime.to_iso8601()

    %{
      "id" => id,
      "title" => "Source-linked report for RKLB",
      "summary" => "Source-linked context for Rocket Lab.",
      "event_type" => "company",
      "first_seen_at" => timestamp,
      "last_seen_at" => timestamp,
      "published_at" => timestamp,
      "freshness" => "fresh",
      "severity" => "medium",
      "confidence" => 0.8,
      "breaking_score" => 60,
      "trust_score" => 82,
      "source_count" => 1,
      "tickers" => [
        %{
          "symbol" => "RKLB",
          "name" => "Rocket Lab",
          "relationship" => "direct_subject",
          "confidence" => 0.8
        }
      ],
      "regions" => [
        %{
          "key" => "USA",
          "name" => "United States",
          "relation" => "company_region",
          "confidence" => 0.8
        }
      ],
      "topics" => [%{"key" => "space", "label" => "Space", "confidence" => 0.8}],
      "market_direction" => "unclear",
      "source_links" => [
        %{
          "label" => "Rocket Lab",
          "url" => "https://investors.rocketlabusa.com/",
          "source_key" => "rocketlab_ir",
          "policy_version" => 1,
          "title" => "Rocket Lab investor relations",
          "published_at" => timestamp,
          "trust_tier" => "T0_OFFICIAL",
          "is_primary" => true
        }
      ]
    }
    |> deep_merge(overrides)
  end

  defp breaking_event(event_id, timestamp, overrides) do
    timestamp = timestamp |> DateTime.truncate(:second) |> DateTime.to_iso8601()

    %{
      "event_id" => event_id,
      "title" => "Reviewed market update",
      "summary" => "Reviewed market source context.",
      "source_url" => "https://example.com/#{event_id}",
      "source_published_at" => timestamp,
      "observed_at" => timestamp,
      "verified_at" => timestamp,
      "freshness_confidence" => 0.9,
      "urgency_score" => 75,
      "severity" => "high",
      "trust_tier" => "T2_REPUTABLE_MEDIA",
      "discovery_only" => false,
      "review_state" => "approved",
      "citation_ids" => ["doc_test"],
      "retention_class" => "metadata_only",
      "geo_points" => [map_point(event_id, timestamp)],
      "geo_confidence" => 0.9,
      "score_reason_codes" => ["fixture"],
      "dedupe_key" => "fixture:#{event_id}",
      "label" => "breaking",
      "tickers" => [],
      "regions" => [],
      "topics" => [],
      "source_count" => 1
    }
    |> deep_merge(overrides)
  end

  defp map_point(event_id, timestamp) do
    timestamp =
      case timestamp do
        %DateTime{} = datetime -> DateTime.to_iso8601(DateTime.truncate(datetime, :second))
        value -> to_string(value)
      end

    %{
      "point_id" => "point_#{event_id}",
      "event_id" => event_id,
      "event_ids" => [event_id],
      "title" => "Map point #{event_id}",
      "summary" => "Mapped source context.",
      "area_id" => "USA",
      "area_key" => "USA",
      "area_label" => "United States",
      "relation" => "event_location",
      "latitude" => 38.0,
      "longitude" => -97.0,
      "severity" => "high",
      "urgency_score" => 75,
      "source_published_at" => timestamp,
      "observed_at" => timestamp,
      "source_url" => "https://example.com/#{event_id}",
      "source_count" => 1,
      "geo_confidence" => 0.9,
      "area_priority" => 80,
      "score_reason_codes" => ["fixture"]
    }
  end

  defp deep_merge(left, right) do
    Map.merge(left, right, fn _key, left_value, right_value ->
      if is_map(left_value) and is_map(right_value) do
        deep_merge(left_value, right_value)
      else
        right_value
      end
    end)
  end
end
