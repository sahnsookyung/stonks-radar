defmodule StonksBackend.Snapshots do
  @moduledoc "Snapshot candidate/publish compatibility for the local OCI volume model."

  alias StonksBackend.{Repo, Settings, Sql}
  alias StonksBackend.Snapshots.SchemaResolver

  @manifest_filename "manifest.json"
  @latest_manifest_path Path.join(["latest", @manifest_filename])
  @public_manifest_key "public/latest/manifest.json"
  @schema_dir "packages/schemas/snapshots"
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

  def build_local_seed do
    root = published_root()
    {:ok, %{files: json_files(root), uploaded: false, destination: root, snapshot_version: 1}}
  end

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

    with :ok <- require_manifest(published_root()),
         {:ok, seed_manifest} <- read_snapshot(published_manifest_path()),
         {:ok, files, manifest} <-
           write_template_snapshot_tree(candidate_root, seed_manifest, version, generated_at),
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

  defp write_template_snapshot_tree(candidate_root, seed_manifest, version, generated_at) do
    manifest = %{
      "current_version" => version,
      "generated_at" => iso8601(generated_at),
      "locales" => seed_manifest["locales"] || [],
      "objects" => %{}
    }

    context = %{
      corrections: corrections(),
      generated_at: generated_at,
      hard_expires_at: DateTime.add(generated_at, 7, :day),
      stale_after: DateTime.add(generated_at, 12, :hour),
      version: version
    }

    (seed_manifest["objects"] || %{})
    |> Enum.reject(fn {object_key, _locale_paths} ->
      prohibited_public_object_key?(object_key)
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
      with {:ok, snapshot} <- seed_snapshot(source_path, context),
           {:ok, relative} <-
             versioned_snapshot_relative_path(context.version, locale, source_path),
           snapshot <- apply_template_runtime_data(snapshot, object_key, locale, context),
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

  defp seed_snapshot(source_path, context) do
    with {:ok, relative} <- manifest_snapshot_relative_path(source_path),
         seed_path = Path.join(published_root(), relative),
         {:ok, snapshot} <- read_snapshot(seed_path) do
      {:ok,
       snapshot
       |> Map.put("snapshot_version", context.version)
       |> Map.put("generated_at", iso8601(context.generated_at))
       |> Map.put("stale_after", iso8601(context.stale_after))
       |> Map.put("hard_expires_at", iso8601(context.hard_expires_at))
       |> Map.put("corrections", context.corrections)
       |> Map.put_new("warnings", [])
       |> Map.put_new("source_policy_versions", [])}
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
         _locale,
         context
       ) do
    update_in(snapshot, ["data"], fn data ->
      data
      |> ensure_map()
      |> maybe_put_existing("generated_label", iso8601(context.generated_at))
      |> update_snapshot_health(context)
      |> StonksBackend.Shorts.enrich_home_snapshot_data()
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

  defp apply_template_runtime_data(snapshot, _object_key, _locale, _context), do: snapshot

  defp maybe_enrich_yield_curves(data) do
    case StonksBackend.YieldCurves.enrich_home_snapshot_data(data) do
      {:ok, enriched_data} -> enriched_data
    end
  end

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
           :ok <- assert_not_prohibited_public_snapshot(snapshot, path),
           :ok <- assert_no_public_raw_private(snapshot, path),
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
