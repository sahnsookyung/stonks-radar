defmodule StonksBackend.Jobs do
  @moduledoc "Oban-backed durable job interface with legacy `job_queue` compatibility."

  alias StonksBackend.Jobs.{LegacyQueue, RuntimeLock}
  alias StonksBackend.Jobs.Workers.GenericWorker
  alias StonksBackend.Sql

  @legacy_uuid_re ~r/\A[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\z/i
  @allowed_queues ~w(snapshots market_data news instruments disclosures maintenance default)
  @default_admin_status_limit 20
  @max_admin_status_limit 100

  def enqueue(job_type, payload, opts \\ []) do
    job_type = to_string(job_type)
    queue = opts |> Keyword.get(:queue, queue_for(job_type)) |> normalize_queue()
    priority = opts |> Keyword.get(:priority, 5) |> normalize_priority()
    args = worker_args(job_type, payload, Keyword.merge(opts, queue: queue, priority: priority))

    worker_opts =
      [
        queue: queue_to_atom(queue),
        priority: priority,
        unique: [
          period: :infinity,
          keys: [:job_type, :idempotency_key],
          states: [:available, :scheduled, :executing]
        ]
      ]
      |> put_scheduled_at(Keyword.get(opts, :scheduled_at) || Keyword.get(opts, :run_after))

    changeset =
      GenericWorker.new(
        args,
        worker_opts
      )

    case Oban.insert(changeset) do
      {:ok, job} -> {:ok, external_id(job.id)}
      {:error, %Ecto.Changeset{} = changeset} -> {:error, changeset}
      other -> other
    end
  end

  def replay(external_id) do
    with {:ok, parsed} <- parse_external_id(external_id) do
      replay_parsed(parsed)
    end
  end

  defp replay_parsed({:oban, id}) do
    with true <- id > 0,
         {:ok, _job} <- Oban.retry_job(id) do
      {:ok, "oban:#{id}"}
    else
      _ -> {:error, :not_found}
    end
  end

  defp replay_parsed({:legacy, legacy_id}) do
    case LegacyQueue.read_row(legacy_id) do
      nil ->
        {:error, :not_found}

      row ->
        enqueue_legacy_row(row)
    end
  end

  def parse_external_id("oban:" <> raw_id) do
    with {id, ""} <- Integer.parse(raw_id),
         true <- id > 0 do
      {:ok, {:oban, id}}
    else
      _ -> {:error, :invalid_job_id}
    end
  end

  def parse_external_id("legacy:" <> legacy_id) do
    if Regex.match?(@legacy_uuid_re, legacy_id) do
      {:ok, {:legacy, String.downcase(legacy_id)}}
    else
      {:error, :invalid_job_id}
    end
  end

  def parse_external_id(_), do: {:error, :invalid_job_id}

  def accepted_replay_id?(external_id), do: match?({:ok, _}, parse_external_id(external_id))

  def normalize_reference_id(value) when is_integer(value) and value > 0, do: external_id(value)

  def normalize_reference_id(value) when is_binary(value) do
    value = String.trim(value)

    case parse_external_id(value) do
      {:ok, {:oban, id}} ->
        external_id(id)

      {:ok, {:legacy, legacy_id}} ->
        "legacy:#{legacy_id}"

      {:error, :invalid_job_id} ->
        cond do
          Regex.match?(@legacy_uuid_re, value) ->
            "legacy:#{String.downcase(value)}"

          true ->
            case Integer.parse(value) do
              {id, ""} when id > 0 -> external_id(id)
              _ -> nil
            end
        end
    end
  end

  def normalize_reference_id(_), do: nil

  def migrate_legacy_nonterminal_jobs(limit \\ LegacyQueue.default_nonterminal_limit()) do
    LegacyQueue.read_nonterminal_rows(limit)
    |> Enum.map(&enqueue_legacy_row/1)
  end

  def replay_legacy_nonterminal_jobs, do: migrate_legacy_nonterminal_jobs()

  def legacy_row_to_enqueue(row), do: LegacyQueue.to_enqueue(row)

  def worker_args(job_type, payload, opts \\ []) do
    job_type = to_string(job_type)
    payload = normalize_payload(payload)

    queue =
      opts
      |> Keyword.get(:queue, Keyword.get(opts, :job_group, queue_for(job_type)))
      |> normalize_queue()

    priority = opts |> Keyword.get(:priority, 5) |> normalize_priority()
    idempotency_key = opts |> Keyword.get(:idempotency_key, job_type) |> to_string()

    %{
      "job_type" => job_type,
      "payload" => payload,
      "idempotency_key" => idempotency_key,
      "job_group" => queue,
      "priority" => priority
    }
    |> put_optional("provider_key", Keyword.get(opts, :provider_key) || payload["provider_key"])
    |> put_optional("source_id", Keyword.get(opts, :source_id) || payload["source_id"])
    |> put_optional(
      "depends_on_job_id",
      normalize_reference_id(
        Keyword.get(opts, :depends_on_job_id) || payload["depends_on_job_id"]
      )
    )
    |> put_optional("legacy_job_id", Keyword.get(opts, :legacy_job_id))
    |> put_optional("global_lock", Keyword.get(opts, :global_lock) || payload["global_lock"])
    |> put_optional(
      "global_lock_key",
      Keyword.get(opts, :global_lock_key) || payload["global_lock_key"]
    )
    |> put_runtime_locks(Keyword.get(opts, :runtime_locks))
  end

  def admin_status(limit \\ @default_admin_status_limit) do
    limit = normalize_limit(limit, @default_admin_status_limit, @max_admin_status_limit)

    oban =
      Sql.all(
        """
        select id, worker as job_type, state as status, queue as job_group,
               attempted_at as locked_at, inserted_at as created_at, errors
        from oban_jobs
        order by inserted_at desc
        limit $1
        """,
        [limit]
      )
      |> Enum.map(fn row ->
        %{
          "id" => external_id(row["id"]),
          "job_type" => row["job_type"],
          "status" => row["status"],
          "job_group" => row["job_group"],
          "last_error_message" => last_error(row["errors"]),
          "created_at" => row["created_at"]
        }
      end)

    legacy =
      Sql.all(
        """
        select id, job_type, status, job_group, last_error_message, created_at
        from job_queue
        where status = 'dead_letter'
        order by created_at desc
        limit $1
        """,
        [limit]
      )
      |> Enum.map(&Map.update!(&1, "id", fn id -> "legacy:#{id}" end))

    Enum.take(oban ++ legacy, limit)
  end

  def external_id(id) when is_integer(id) and id > 0, do: "oban:#{id}"
  def external_id(id) when is_binary(id), do: "oban:#{id}"

  def queue_for(job_type) do
    job_type = to_string(job_type)

    cond do
      String.starts_with?(job_type, "snapshot") or job_type == "news.publish_snapshots" ->
        :snapshots

      String.starts_with?(job_type, "news.") ->
        :news

      String.starts_with?(job_type, "market_data.") ->
        :market_data

      job_type == "instrument_search_index_update" ->
        :instruments

      String.contains?(job_type, "disclosure") ->
        :disclosures

      true ->
        :default
    end
  end

  defp last_error(nil), do: nil
  defp last_error([]), do: nil
  defp last_error(errors) when is_list(errors), do: errors |> List.last() |> Map.get("message")
  defp last_error(_), do: nil

  defp enqueue_legacy_row(row) do
    case LegacyQueue.to_enqueue(row) do
      {:ok, {job_type, payload, opts}} -> enqueue(job_type, payload, opts)
      {:error, reason} -> {:error, reason}
    end
  end

  defp put_runtime_locks(args, nil) do
    scopes = RuntimeLock.scopes_from_args(args)

    if scopes == [] do
      args
    else
      Map.put(args, "runtime_locks", scopes)
    end
  end

  defp put_runtime_locks(args, scopes) do
    Map.put(args, "runtime_locks", RuntimeLock.normalize_scopes(scopes))
  end

  defp put_optional(map, _key, nil), do: map
  defp put_optional(map, _key, ""), do: map
  defp put_optional(map, key, value), do: Map.put(map, key, value)

  defp normalize_payload(nil), do: %{}
  defp normalize_payload(payload) when is_map(payload), do: stringify_keys(payload)

  defp normalize_payload(payload) when is_binary(payload) do
    case Jason.decode(payload) do
      {:ok, decoded} when is_map(decoded) -> stringify_keys(decoded)
      {:ok, decoded} -> %{"value" => decoded}
      _ -> %{"value" => payload}
    end
  end

  defp normalize_payload(payload), do: %{"value" => payload}

  defp stringify_keys(map) when is_map(map) do
    Map.new(map, fn {key, value} -> {to_string(key), stringify_nested(value)} end)
  end

  defp stringify_nested(value) when is_map(value), do: stringify_keys(value)
  defp stringify_nested(value) when is_list(value), do: Enum.map(value, &stringify_nested/1)
  defp stringify_nested(value), do: value

  defp normalize_queue(queue) when is_atom(queue),
    do: queue |> Atom.to_string() |> normalize_queue()

  defp normalize_queue(queue) when is_binary(queue) do
    queue = String.trim(queue)
    if queue in @allowed_queues, do: queue, else: "default"
  end

  defp normalize_queue(_), do: "default"

  defp queue_to_atom(queue) when is_binary(queue), do: String.to_existing_atom(queue)

  defp put_scheduled_at(opts, value) do
    case normalize_scheduled_at(value) do
      nil -> opts
      scheduled_at -> Keyword.put(opts, :scheduled_at, scheduled_at)
    end
  end

  defp normalize_scheduled_at(nil), do: nil
  defp normalize_scheduled_at(%DateTime{} = scheduled_at), do: scheduled_at

  defp normalize_scheduled_at(%NaiveDateTime{} = scheduled_at),
    do: DateTime.from_naive!(scheduled_at, "Etc/UTC")

  defp normalize_scheduled_at(value) when is_binary(value) do
    value = String.trim(value)

    with :error <- parse_datetime(value),
         :error <- parse_naive_datetime(value) do
      nil
    else
      {:ok, scheduled_at} -> scheduled_at
    end
  end

  defp normalize_scheduled_at(_), do: nil

  defp parse_datetime(value) do
    case DateTime.from_iso8601(value) do
      {:ok, scheduled_at, _offset} -> {:ok, scheduled_at}
      _ -> :error
    end
  end

  defp parse_naive_datetime(value) do
    case NaiveDateTime.from_iso8601(value) do
      {:ok, scheduled_at} -> {:ok, DateTime.from_naive!(scheduled_at, "Etc/UTC")}
      _ -> :error
    end
  end

  defp normalize_priority(value), do: value |> to_int(5) |> max(0) |> min(9)

  defp normalize_limit(value, default, max_limit) do
    value
    |> to_int(default)
    |> max(1)
    |> min(max_limit)
  end

  defp to_int(value, _default) when is_integer(value), do: value

  defp to_int(value, default) when is_binary(value) do
    case Integer.parse(value) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  defp to_int(_, default), do: default
end
