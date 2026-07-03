defmodule StonksBackend.SnapshotsTest do
  use ExUnit.Case, async: false

  alias StonksBackend.Snapshots

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
    assert snapshot["content_hash"] =~ "sha256:"
    assert snapshot["stale_after"] != snapshot["generated_at"]
    assert :ok = Snapshots.validate_snapshot_tree(result.destination)
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

  test "candidate build enriches news claims, windows, and configured ticker facets", %{
    published_root: root,
    artifact_root: artifact_root
  } do
    now = DateTime.utc_now()
    recent = DateTime.add(now, -2, :hour)
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
    refute Enum.any?(index["data"]["events"], &(&1["id"] == "stale_source_discovery"))

    assert %{
             "title" => "Rocket Lab source links for RKLB filings and company updates",
             "summary" => summary,
             "item_kind" => "source_discovery",
             "claim_level" => "source_only",
             "evidence_match_status" => "weak_match"
           } = Enum.find(index["data"]["events"], &(&1["id"] == "rklb_launch_window_seed"))

    assert summary =~ "not a verified launch-window event"

    assert %{"count" => 0} =
             Enum.find(index["data"]["filters"]["tickers"], &(&1["key"] == "AMD"))

    ticker =
      result.destination
      |> Path.join("v2/en/news/tickers/RKLB.json")
      |> File.read!()
      |> Jason.decode!()

    assert ticker["data"]["coverage_window"] == "7d"
    assert Enum.map(ticker["data"]["events"], & &1["id"]) == ["rklb_launch_window_seed"]
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
