defmodule StonksBackend.SnapshotReadiness do
  @moduledoc "Public, provider-neutral readiness derived from the published home snapshot."

  alias StonksBackend.Snapshots

  @manifest_path Path.join(["latest", "manifest.json"])
  @unavailable_payload %{
    version: nil,
    generated_at: nil,
    stale_after: nil,
    hard_expires_at: nil,
    age_seconds: nil,
    status: "unavailable",
    reason: "snapshot_unavailable"
  }

  def current(opts \\ []) do
    root = Keyword.get(opts, :root, Snapshots.published_root())
    now = Keyword.get(opts, :now, DateTime.utc_now())

    with {:ok, manifest} <- read_json(Path.join(root, @manifest_path)),
         {:ok, version} <- positive_integer(manifest["current_version"]),
         {:ok, relative_path} <- home_path(manifest),
         {:ok, snapshot_path} <- safe_snapshot_path(root, relative_path),
         {:ok, snapshot} <- read_json(snapshot_path),
         :ok <- matching_version(snapshot["snapshot_version"], version),
         {:ok, generated_at} <- parse_datetime(snapshot["generated_at"]),
         {:ok, stale_after} <- parse_datetime(snapshot["stale_after"]),
         {:ok, hard_expires_at} <- parse_datetime(snapshot["hard_expires_at"]),
         :ok <- validate_window(generated_at, stale_after, hard_expires_at) do
      status_payload(version, generated_at, stale_after, hard_expires_at, now)
    else
      {:error, :missing} -> unavailable("snapshot_missing")
      {:error, :unsafe_path} -> unavailable("manifest_invalid")
      {:error, :invalid_window} -> unavailable("snapshot_invalid")
      {:error, :invalid} -> unavailable("snapshot_invalid")
      {:error, :invalid_version} -> unavailable("version_mismatch")
    end
  rescue
    _ -> unavailable("snapshot_invalid")
  end

  defp status_payload(version, generated_at, stale_after, hard_expires_at, now) do
    base = %{
      version: version,
      generated_at: DateTime.to_iso8601(generated_at),
      stale_after: DateTime.to_iso8601(stale_after),
      hard_expires_at: DateTime.to_iso8601(hard_expires_at),
      age_seconds: max(DateTime.diff(now, generated_at, :second), 0)
    }

    cond do
      DateTime.compare(now, hard_expires_at) != :lt ->
        Map.merge(base, %{status: "unavailable", reason: "hard_expired"})

      DateTime.compare(now, stale_after) != :lt ->
        Map.merge(base, %{status: "degraded", reason: "stale"})

      true ->
        Map.merge(base, %{status: "ready", reason: "fresh"})
    end
  end

  defp unavailable(reason), do: %{@unavailable_payload | reason: reason}

  defp read_json(path) do
    case File.read(path) do
      {:ok, body} ->
        case Jason.decode(body) do
          {:ok, value} when is_map(value) -> {:ok, value}
          _ -> {:error, :invalid}
        end

      {:error, :enoent} ->
        {:error, :missing}

      {:error, _reason} ->
        {:error, :invalid}
    end
  end

  defp home_path(%{"objects" => %{"home" => locales}}) when is_map(locales) do
    case locales["en"] || locales["ko"] do
      path when is_binary(path) and path != "" -> {:ok, path}
      _ -> {:error, :invalid}
    end
  end

  defp home_path(_manifest), do: {:error, :invalid}

  defp safe_snapshot_path(root, path) do
    relative = String.replace_prefix(path, "public/", "")
    expanded_root = Path.expand(root)
    expanded_path = Path.expand(relative, expanded_root)

    if expanded_path != expanded_root and String.starts_with?(expanded_path, expanded_root <> "/") do
      {:ok, expanded_path}
    else
      {:error, :unsafe_path}
    end
  end

  defp positive_integer(value) when is_integer(value) and value > 0, do: {:ok, value}

  defp positive_integer(value) when is_binary(value) do
    case Integer.parse(value) do
      {integer, ""} when integer > 0 -> {:ok, integer}
      _ -> {:error, :invalid_version}
    end
  end

  defp positive_integer(_value), do: {:error, :invalid_version}

  defp matching_version(value, expected) do
    case positive_integer(value) do
      {:ok, ^expected} -> :ok
      _ -> {:error, :invalid_version}
    end
  end

  defp parse_datetime(value) when is_binary(value) do
    case DateTime.from_iso8601(value) do
      {:ok, datetime, _offset} -> {:ok, datetime}
      _ -> {:error, :invalid}
    end
  end

  defp parse_datetime(_value), do: {:error, :invalid}

  defp validate_window(generated_at, stale_after, hard_expires_at) do
    if DateTime.compare(generated_at, stale_after) == :lt and
         DateTime.compare(stale_after, hard_expires_at) == :lt do
      :ok
    else
      {:error, :invalid_window}
    end
  end
end
