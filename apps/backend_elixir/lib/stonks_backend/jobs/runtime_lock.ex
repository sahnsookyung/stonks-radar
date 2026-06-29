defmodule StonksBackend.Jobs.RuntimeLock do
  @moduledoc "Database-backed provider/source/global running-limit lock."

  alias StonksBackend.Sql

  @default_lease_seconds 900
  @retry_seconds 30
  @max_lease_seconds 86_400
  @valid_scope_types ["global", "provider", "source"]

  def default_lease_seconds, do: @default_lease_seconds
  def retry_in_seconds, do: @retry_seconds

  def acquire(scope_type, scope_key, owner, lease_seconds \\ @default_lease_seconds) do
    owner = to_string(owner)
    lease_seconds = normalize_lease_seconds(lease_seconds)

    case scope(scope_type, scope_key) do
      %{"scope_type" => normalized_type, "scope_key" => normalized_key} ->
        Sql.scalar(
          """
          insert into job_runtime_lock(scope_type, scope_key, owner, lease_expires_at)
          values ($1, $2, $3, now() + ($4 || ' seconds')::interval)
          on conflict (scope_type, scope_key)
          do update set owner = excluded.owner,
                        lease_expires_at = excluded.lease_expires_at,
                        updated_at = now()
          where job_runtime_lock.lease_expires_at <= now()
             or job_runtime_lock.owner = excluded.owner
          returning owner
          """,
          [normalized_type, normalized_key, owner, lease_seconds]
        ) == owner

      nil ->
        false
    end
  end

  def acquire_many(scopes, owner, lease_seconds \\ @default_lease_seconds) do
    scopes = scopes |> normalize_scopes() |> lock_order()
    lease_seconds = normalize_lease_seconds(lease_seconds)

    Enum.reduce_while(scopes, {:ok, []}, fn scope, {:ok, acquired} ->
      if acquire(scope["scope_type"], scope["scope_key"], owner, lease_seconds) do
        {:cont, {:ok, [scope | acquired]}}
      else
        release_many(acquired, owner)
        {:halt, {:error, {:locked, scope}}}
      end
    end)
    |> case do
      {:ok, acquired} -> {:ok, Enum.reverse(acquired)}
      other -> other
    end
  end

  def release(scope_type, scope_key, owner) do
    scope_type = normalize_scope_type(scope_type)
    scope_key = normalize_scope_key(scope_type, scope_key)

    Sql.execute(
      "delete from job_runtime_lock where scope_type = $1 and scope_key = $2 and owner = $3",
      [scope_type, scope_key, to_string(owner)]
    )
  end

  def release_many(scopes, owner) do
    scopes
    |> normalize_scopes()
    |> Enum.each(fn scope -> release(scope["scope_type"], scope["scope_key"], owner) end)

    :ok
  end

  def release_owner(owner) do
    Sql.execute("delete from job_runtime_lock where owner = $1", [to_string(owner)])
  end

  def purge_expired do
    Sql.execute("delete from job_runtime_lock where lease_expires_at <= now()", [])
  end

  def scopes_from_args(%{} = args) do
    case Map.get(args, "runtime_locks") || Map.get(args, :runtime_locks) do
      nil -> derive_scopes(args)
      scopes -> normalize_scopes(scopes)
    end
  end

  def scopes_from_args(_), do: []

  def normalize_scopes(scopes) when is_list(scopes) do
    scopes
    |> Enum.flat_map(&normalize_scope/1)
    |> Enum.uniq_by(fn scope -> {scope["scope_type"], scope["scope_key"]} end)
  end

  def normalize_scopes(nil), do: []
  def normalize_scopes(scope), do: normalize_scopes([scope])

  def stale?(lease_expires_at, now \\ DateTime.utc_now())

  def stale?(nil, _now), do: false

  def stale?(lease_expires_at, now) do
    with {:ok, lease_dt} <- to_datetime(lease_expires_at),
         {:ok, now_dt} <- to_datetime(now) do
      DateTime.compare(lease_dt, now_dt) in [:lt, :eq]
    else
      _ -> false
    end
  end

  defp derive_scopes(args) do
    payload = Map.get(args, "payload") || Map.get(args, :payload) || %{}

    [
      scope(
        "provider",
        Map.get(args, "provider_key") || Map.get(args, :provider_key) || payload["provider_key"]
      ),
      scope(
        "source",
        Map.get(args, "source_id") || Map.get(args, :source_id) || payload["source_id"]
      ),
      maybe_snapshot_global_scope(args),
      maybe_global_scope(args, payload)
    ]
    |> Enum.reject(&is_nil/1)
  end

  defp maybe_snapshot_global_scope(args) do
    job_type = Map.get(args, "job_type") || Map.get(args, :job_type)

    if snapshot_job_type?(job_type) do
      scope("global", "snapshots")
    end
  end

  defp maybe_global_scope(args, payload) do
    flag = Map.get(args, "global_lock") || Map.get(args, :global_lock) || payload["global_lock"]

    if truthy?(flag) do
      scope_key =
        Map.get(args, "global_lock_key") ||
          Map.get(args, :global_lock_key) ||
          payload["global_lock_key"] ||
          "global"

      scope("global", scope_key)
    end
  end

  defp normalize_scope({scope_type, scope_key}),
    do: normalize_scope(%{scope_type: scope_type, scope_key: scope_key})

  defp normalize_scope(%{} = scope) do
    scope_type =
      Map.get(scope, "scope_type") || Map.get(scope, :scope_type) || Map.get(scope, "type") ||
        Map.get(scope, :type)

    scope_key =
      Map.get(scope, "scope_key") || Map.get(scope, :scope_key) || Map.get(scope, "key") ||
        Map.get(scope, :key)

    case scope(scope_type, scope_key) do
      nil -> []
      normalized -> [normalized]
    end
  end

  defp normalize_scope(_), do: []

  defp scope(scope_type, scope_key) do
    scope_type = normalize_scope_type(scope_type)
    scope_key = normalize_scope_key(scope_type, scope_key)

    if scope_type in @valid_scope_types and scope_key not in [nil, ""] do
      %{"scope_type" => scope_type, "scope_key" => scope_key}
    end
  end

  defp normalize_scope_type(scope_type) when is_atom(scope_type), do: Atom.to_string(scope_type)

  defp normalize_scope_type(scope_type) when is_binary(scope_type),
    do: String.downcase(scope_type)

  defp normalize_scope_type(_), do: ""

  defp normalize_scope_key("global", nil), do: "global"
  defp normalize_scope_key("global", ""), do: "global"
  defp normalize_scope_key(_scope_type, nil), do: nil

  defp normalize_scope_key(_scope_type, scope_key) when is_binary(scope_key),
    do: String.trim(scope_key)

  defp normalize_scope_key(_scope_type, scope_key), do: to_string(scope_key)

  defp lock_order(scopes) do
    Enum.sort_by(scopes, fn scope -> {scope_rank(scope["scope_type"]), scope["scope_key"]} end)
  end

  defp scope_rank("global"), do: 0
  defp scope_rank("provider"), do: 1
  defp scope_rank("source"), do: 2
  defp scope_rank(_), do: 3

  defp snapshot_job_type?(job_type) when is_binary(job_type),
    do: String.starts_with?(job_type, "snapshot") or job_type == "news.publish_snapshots"

  defp snapshot_job_type?(_), do: false

  defp normalize_lease_seconds(value) when is_integer(value),
    do: value |> max(1) |> min(@max_lease_seconds)

  defp normalize_lease_seconds(value) when is_binary(value) do
    case Integer.parse(value) do
      {integer, ""} -> normalize_lease_seconds(integer)
      _ -> @default_lease_seconds
    end
  end

  defp normalize_lease_seconds(_), do: @default_lease_seconds

  defp truthy?(value) when is_binary(value),
    do: String.downcase(value) in ["1", "true", "yes", "on"]

  defp truthy?(value), do: value in [true, 1]

  defp to_datetime(%DateTime{} = dt), do: {:ok, dt}
  defp to_datetime(%NaiveDateTime{} = dt), do: DateTime.from_naive(dt, "Etc/UTC")

  defp to_datetime(value) when is_binary(value) do
    with {:error, :invalid_datetime} <- parse_datetime(value),
         {:error, :invalid_datetime} <- parse_naive_datetime(value) do
      {:error, :invalid_datetime}
    end
  end

  defp to_datetime(_), do: {:error, :invalid_datetime}

  defp parse_datetime(value) do
    case DateTime.from_iso8601(value) do
      {:ok, dt, _offset} -> {:ok, dt}
      _ -> {:error, :invalid_datetime}
    end
  end

  defp parse_naive_datetime(value) do
    case NaiveDateTime.from_iso8601(value) do
      {:ok, dt} -> DateTime.from_naive(dt, "Etc/UTC")
      _ -> {:error, :invalid_datetime}
    end
  end
end
