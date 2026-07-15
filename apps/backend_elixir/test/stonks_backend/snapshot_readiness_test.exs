defmodule StonksBackend.SnapshotReadinessTest do
  use ExUnit.Case, async: true

  alias StonksBackend.SnapshotReadiness

  @now ~U[2026-07-14 10:00:00Z]

  test "reports ready, degraded, and unavailable from the published home snapshot" do
    root = temp_root!()

    write_snapshot!(
      root,
      @now |> DateTime.add(-60, :second),
      @now |> DateTime.add(60, :second),
      @now |> DateTime.add(120, :second)
    )

    assert %{status: "ready", reason: "fresh", version: 42, age_seconds: 60} = current(root)

    write_snapshot!(
      root,
      @now |> DateTime.add(-120, :second),
      @now |> DateTime.add(-60, :second),
      @now |> DateTime.add(60, :second)
    )

    assert %{status: "degraded", reason: "stale", version: 42} = current(root)

    write_snapshot!(
      root,
      @now |> DateTime.add(-180, :second),
      @now |> DateTime.add(-120, :second),
      @now |> DateTime.add(-60, :second)
    )

    assert %{status: "unavailable", reason: "hard_expired", version: 42} = current(root)
  end

  test "reports unavailable for missing, malformed, mismatched, and unsafe content" do
    missing_root = temp_root!()
    assert %{status: "unavailable", reason: "snapshot_missing"} = current(missing_root)

    malformed_root = temp_root!()
    File.mkdir_p!(Path.join(malformed_root, "latest"))
    File.write!(Path.join([malformed_root, "latest", "manifest.json"]), "not-json")
    assert %{status: "unavailable", reason: "snapshot_invalid"} = current(malformed_root)

    mismatch_root = temp_root!()

    write_snapshot!(
      mismatch_root,
      DateTime.add(@now, -60),
      DateTime.add(@now, 60),
      DateTime.add(@now, 120),
      snapshot_version: 41
    )

    assert %{status: "unavailable", reason: "version_mismatch"} = current(mismatch_root)

    unsafe_root = temp_root!()
    write_manifest!(unsafe_root, "public/../../etc/passwd")
    assert %{status: "unavailable", reason: "manifest_invalid"} = current(unsafe_root)
  end

  test "reports degraded when a current snapshot exposes unavailable live data" do
    root = temp_root!()

    write_snapshot!(
      root,
      @now |> DateTime.add(-60, :second),
      @now |> DateTime.add(60, :second),
      @now |> DateTime.add(120, :second),
      warnings: [
        %{
          "code" => "live_data_unavailable",
          "message" => "No current source-backed data is available for this view.",
          "severity" => "warning"
        }
      ]
    )

    assert %{status: "degraded", reason: "content_unavailable", version: 42} = current(root)
  end

  test "reports degraded when a current snapshot still contains a static seed source" do
    root = temp_root!()

    write_snapshot!(
      root,
      @now |> DateTime.add(-60, :second),
      @now |> DateTime.add(60, :second),
      @now |> DateTime.add(120, :second),
      data: %{
        "instruments" => [
          %{"id" => "AAPL", "source_key" => "local_static_seed", "status" => "active"}
        ]
      }
    )

    assert %{status: "degraded", reason: "content_unavailable", version: 42} = current(root)
  end

  defp current(root), do: SnapshotReadiness.current(root: root, now: @now)

  defp temp_root! do
    root =
      Path.join(System.tmp_dir!(), "snapshot-readiness-#{System.unique_integer([:positive])}")

    File.mkdir_p!(root)
    on_exit(fn -> File.rm_rf!(root) end)
    root
  end

  defp write_snapshot!(root, generated_at, stale_after, hard_expires_at, opts \\ []) do
    write_manifest!(root, "public/v42/en/home.json")
    snapshot_path = Path.join([root, "v42", "en", "home.json"])
    File.mkdir_p!(Path.dirname(snapshot_path))

    File.write!(
      snapshot_path,
      Jason.encode!(%{
        "snapshot_version" => Keyword.get(opts, :snapshot_version, 42),
        "generated_at" => DateTime.to_iso8601(generated_at),
        "stale_after" => DateTime.to_iso8601(stale_after),
        "hard_expires_at" => DateTime.to_iso8601(hard_expires_at),
        "data" => Keyword.get(opts, :data, %{}),
        "warnings" => Keyword.get(opts, :warnings, [])
      })
    )
  end

  defp write_manifest!(root, home_path) do
    path = Path.join([root, "latest", "manifest.json"])
    File.mkdir_p!(Path.dirname(path))

    File.write!(
      path,
      Jason.encode!(%{
        "current_version" => 42,
        "generated_at" => "2026-07-14T09:59:00Z",
        "objects" => %{"home" => %{"en" => home_path}}
      })
    )
  end
end
