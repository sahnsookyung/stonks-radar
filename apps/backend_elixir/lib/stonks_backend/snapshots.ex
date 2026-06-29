defmodule StonksBackend.Snapshots do
  @moduledoc "Snapshot candidate/publish compatibility for the local OCI volume model."

  alias StonksBackend.{Repo, Settings, Sql}

  @manifest_filename "manifest.json"
  @latest_manifest_path Path.join(["latest", @manifest_filename])
  @public_manifest_key "public/latest/manifest.json"
  @json_file_glob "**/*.json"
  @default_publish_max_files 50_000
  @default_publish_max_bytes 2_000_000_000
  @prohibited_public_fields [
    "api_key",
    "full_article_text",
    "private_note",
    "prompt_text",
    "raw_html",
    "restricted_source_text",
    "secret"
  ]
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
    "sector_page" => "sector_snapshot.schema.json",
    "source_status" => "source_status_snapshot.schema.json"
  }

  def published_root, do: Settings.get(:published_snapshot_dir, "apps/web/public/public")
  def artifact_root, do: Settings.get(:snapshot_artifact_dir, "artifacts/snapshots")
  def manifest_path, do: @latest_manifest_path
  def public_manifest_key, do: @public_manifest_key
  def public_manifest_url, do: "/#{@public_manifest_key}"
  def published_manifest_path, do: Path.join(published_root(), @latest_manifest_path)

  def candidate_root(version),
    do: Path.join([artifact_root(), "candidates", "v#{version}", "public"])

  def build_local_seed do
    root = published_root()
    {:ok, %{files: json_files(root), uploaded: false, destination: root, snapshot_version: 1}}
  end

  def build_candidate(payload \\ %{}) do
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
    case parse_positive_int(version) do
      {:ok, version} -> publish(version)
      :error -> {:error, "snapshot_publish requires positive snapshot_version"}
    end
  end

  def publish_from_payload(_), do: {:error, "snapshot_publish requires snapshot_version"}

  def refresh(payload \\ %{}) do
    with {:ok, result} <- build_candidate(payload),
         {:ok, published} <- publish(result.snapshot_version) do
      {:ok, published}
    end
  end

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
         {:ok, manifest} <- Jason.decode(content) do
      generated_at = manifest["generated_at"]

      age_minutes =
        DateTime.diff(DateTime.utc_now(), stat.mtime |> DateTime.from_naive!("Etc/UTC"), :second) /
          60

      %{generated_at: generated_at, age_minutes: age_minutes}
    else
      _ -> nil
    end
  end

  defp next_snapshot_version do
    (Sql.scalar("select coalesce(max(snapshot_version), 0) + 1 from publication_manifest", [], 1) ||
       1)
    |> to_int()
  end

  defp record_manifest(candidate_root, version, status, generated_by) do
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
      values ($1, cast($2 as jsonb), $3, $4, $5, cast($6 as timestamptz), $7, $8)
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
            $1, $2, $3, $4, $5, $6, $7, $8, cast($9 as timestamptz),
            cast($10 as timestamptz), cast($11 as timestamptz), cast($12 as jsonb), $13, $14
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

  defp mark_published(version) do
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
           :ok <- validate_snapshot_schema_placeholder(snapshot),
           :ok <- assert_no_public_raw_private(snapshot, path) do
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

  defp validate_snapshot_schema_placeholder(snapshot) do
    if Map.has_key?(@schema_by_object_type, snapshot["object_type"]) do
      :ok
    else
      {:error, "Unknown snapshot object_type: #{inspect(snapshot["object_type"])}"}
    end
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

  defp snapshot_recordable?(snapshot) do
    Enum.all?(["locale", "object_type", "object_key", "schema_version", "generated_at"], fn key ->
      is_binary(snapshot[key]) and snapshot[key] != ""
    end)
  end

  defp assert_no_public_raw_private(value, path) when is_map(value) do
    Enum.reduce_while(value, :ok, fn {key, nested}, :ok ->
      if String.downcase(to_string(key)) in @prohibited_public_fields do
        {:halt, {:error, "#{path} contains prohibited public field #{key}"}}
      else
        case assert_no_public_raw_private(nested, path) do
          :ok -> {:cont, :ok}
          {:error, reason} -> {:halt, {:error, reason}}
        end
      end
    end)
  end

  defp assert_no_public_raw_private(value, path) when is_list(value) do
    Enum.reduce_while(value, :ok, fn nested, :ok ->
      case assert_no_public_raw_private(nested, path) do
        :ok -> {:cont, :ok}
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
  end

  defp assert_no_public_raw_private(_value, _path), do: :ok

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
end
