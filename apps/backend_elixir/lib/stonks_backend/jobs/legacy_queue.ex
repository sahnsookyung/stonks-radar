defmodule StonksBackend.Jobs.LegacyQueue do
  @moduledoc """
  Read-only compatibility helpers for migrating legacy `job_queue` rows into Oban.

  The legacy table remains audit/history. These helpers defensively read whatever
  compatible columns exist and map rows to Oban worker arguments without mutating
  `job_queue`.
  """

  alias StonksBackend.Sql

  @nonterminal_statuses ["queued", "running", "retry_wait", "quota_wait"]
  @default_nonterminal_limit 500
  @max_nonterminal_limit 1_000
  @optional_columns [
    "id",
    "job_type",
    "job_group",
    "priority",
    "status",
    "idempotency_key",
    "payload",
    "provider_key",
    "source_id",
    "depends_on_job_id",
    "run_after"
  ]

  def nonterminal_statuses, do: @nonterminal_statuses
  def default_nonterminal_limit, do: @default_nonterminal_limit

  def read_nonterminal_rows(limit \\ @default_nonterminal_limit) do
    columns = job_queue_columns()
    limit = normalize_limit(limit)

    if required_columns?(columns, ["id", "job_type", "status"]) do
      Sql.all(nonterminal_query(columns), [@nonterminal_statuses, limit])
    else
      []
    end
  end

  def read_row(legacy_id) do
    columns = job_queue_columns()

    if required_columns?(columns, ["id", "job_type"]) do
      Sql.one(row_query(columns), [legacy_id])
    end
  end

  def to_enqueue(row) when is_map(row) do
    row = stringify_keys(row)

    with job_type when is_binary(job_type) and job_type != "" <- text(row["job_type"]) do
      payload = normalize_payload(row["payload"])

      opts =
        [
          queue: text(row["job_group"]) || StonksBackend.Jobs.queue_for(job_type),
          priority: int(row["priority"], 5),
          idempotency_key: text(row["idempotency_key"]) || text(row["id"]) || job_type,
          provider_key: text(row["provider_key"]) || text(payload["provider_key"]),
          source_id: text(row["source_id"]) || text(payload["source_id"]),
          depends_on_job_id:
            StonksBackend.Jobs.normalize_reference_id(text(row["depends_on_job_id"])),
          run_after: text(row["run_after"]),
          legacy_job_id: text(row["id"])
        ]
        |> Enum.reject(fn {_key, value} -> value in [nil, ""] end)

      {:ok, {job_type, payload, opts}}
    else
      _ -> {:error, :missing_job_type}
    end
  end

  def to_enqueue(_), do: {:error, :invalid_legacy_row}

  def nonterminal_query(columns, _limit \\ @default_nonterminal_limit) do
    """
    select #{select_clause(columns)}
    from job_queue
    where status = any($1)
    order by #{order_clause(columns)}
    limit $2
    """
  end

  def row_query(columns) do
    """
    select #{select_clause(columns)}
    from job_queue
    where id = $1
    limit 1
    """
  end

  defp job_queue_columns do
    """
    select column_name
    from information_schema.columns
    where table_name = 'job_queue'
      and table_schema = current_schema()
    """
    |> Sql.all()
    |> Enum.map(& &1["column_name"])
  end

  defp required_columns?(columns, required), do: Enum.all?(required, &(&1 in columns))

  defp select_clause(columns) do
    @optional_columns
    |> Enum.filter(&(&1 in columns))
    |> Enum.map(&column_projection/1)
    |> Enum.join(", ")
  end

  defp column_projection("id"), do: "id::text as id"
  defp column_projection("source_id"), do: "source_id::text as source_id"
  defp column_projection("depends_on_job_id"), do: "depends_on_job_id::text as depends_on_job_id"
  defp column_projection(column), do: column

  defp order_clause(columns) do
    [
      if("priority" in columns, do: "priority asc"),
      if("created_at" in columns, do: "created_at asc"),
      "id asc"
    ]
    |> Enum.reject(&is_nil/1)
    |> Enum.join(", ")
  end

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

  defp text(nil), do: nil

  defp text(value) when is_binary(value) do
    case String.trim(value) do
      "" -> nil
      trimmed -> trimmed
    end
  end

  defp text(value), do: to_string(value)

  defp int(value, _default) when is_integer(value), do: value

  defp int(value, default) when is_binary(value) do
    case Integer.parse(value) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  defp int(_, default), do: default

  defp normalize_limit(value) do
    value
    |> int(@default_nonterminal_limit)
    |> max(1)
    |> min(@max_nonterminal_limit)
  end
end
