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
    assert result.snapshot_version == 1
    assert result.destination == Path.join([artifact_root, "candidates", "v1", "public"])

    assert Path.join(result.destination, "latest/manifest.json") |> File.exists?()
    assert Path.join(result.destination, "v1/en/corrections.json") |> File.exists?()

    manifest =
      result.destination
      |> Path.join("latest/manifest.json")
      |> File.read!()
      |> Jason.decode!()

    assert manifest["objects"]["corrections"]["en"] == "public/v1/en/corrections.json"

    snapshot =
      result.destination
      |> Path.join("v1/en/corrections.json")
      |> File.read!()
      |> Jason.decode!()

    assert snapshot["snapshot_version"] == 1
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
