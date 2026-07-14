defmodule StonksBackend.PrivateMarketDataCache do
  @moduledoc "Supervised, bounded cache for member-private provider responses."

  use GenServer

  @table :stonks_backend_private_market_data_cache
  @max_entries 2_000
  @cleanup_ms 60_000

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  def fetch(key, ttl_ms, fetch_fun) when is_function(fetch_fun, 0) do
    now = System.monotonic_time(:millisecond)

    case :ets.lookup(@table, key) do
      [{^key, expires_at, value}] when expires_at > now -> {:ok, value, :hit}
      _ -> cache_fetch(key, now + ttl_ms, fetch_fun)
    end
  rescue
    ArgumentError ->
      cache_fetch(key, System.monotonic_time(:millisecond) + ttl_ms, fetch_fun)
  end

  def delete_user(user_id) do
    if Process.whereis(__MODULE__),
      do: GenServer.call(__MODULE__, {:delete_user, to_string(user_id)})

    :ok
  end

  @impl true
  def init(_opts) do
    :ets.new(@table, [:named_table, :public, :set, read_concurrency: true])
    schedule_cleanup()
    {:ok, %{}}
  end

  @impl true
  def handle_call({:delete_user, user_id}, _from, state) do
    :ets.select_delete(@table, [{{{:"$1", :_, :_}, :_, :_}, [{:==, :"$1", user_id}], [true]}])
    {:reply, :ok, state}
  end

  def handle_call({:put, key, expires_at, value}, _from, state) do
    cleanup()
    trim()
    :ets.insert(@table, {key, expires_at, value})
    {:reply, :ok, state}
  end

  @impl true
  def handle_info(:cleanup, state) do
    cleanup()
    schedule_cleanup()
    {:noreply, state}
  end

  defp cache_fetch(key, expires_at, fetch_fun) do
    case fetch_fun.() do
      {:ok, value} ->
        if Process.whereis(__MODULE__) do
          GenServer.call(__MODULE__, {:put, key, expires_at, value})
        else
          safe_put(key, expires_at, value)
        end

        {:ok, value, :miss}

      error ->
        error
    end
  end

  defp safe_put(key, expires_at, value) do
    :ets.insert(@table, {key, expires_at, value})
  rescue
    ArgumentError -> :ok
  end

  defp cleanup do
    now = System.monotonic_time(:millisecond)
    :ets.select_delete(@table, [{{:_, :"$1", :_}, [{:"=<", :"$1", now}], [true]}])
  rescue
    ArgumentError -> 0
  end

  defp trim do
    overflow = (:ets.info(@table, :size) || 0) - @max_entries + 1

    if overflow > 0 do
      @table
      |> :ets.tab2list()
      |> Enum.sort_by(fn {_key, expires_at, _value} -> expires_at end)
      |> Enum.take(overflow)
      |> Enum.each(fn {key, _expires_at, _value} -> :ets.delete(@table, key) end)
    end
  end

  defp schedule_cleanup, do: Process.send_after(self(), :cleanup, @cleanup_ms)
end
