defmodule StonksBackend.InstrumentCache do
  @moduledoc "Supervised bounded ETS owner for cross-request instrument caches."

  use GenServer

  @index_table :stonks_backend_instrument_index_cache
  @provider_table :stonks_backend_instrument_provider_cache
  @max_provider_entries 2_000
  @cleanup_interval_ms 60_000

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  def fetch_index(ttl_ms, builder) when is_function(builder, 0) do
    now = System.monotonic_time(:millisecond)

    case lookup(@index_table, :local_index, now) do
      {:ok, entries} ->
        {entries, :hit}

      :miss ->
        entries = builder.()
        put(@index_table, :local_index, now + ttl_ms, entries)
        {entries, :miss}
    end
  end

  def invalidate_index do
    safe_delete(@index_table, :local_index)
    :ok
  end

  def put_provider(key, expires_at, value) do
    if Process.whereis(__MODULE__) do
      GenServer.call(__MODULE__, {:put_provider, key, expires_at, value})
    else
      put(@provider_table, key, expires_at, value)
    end
  end

  def cleanup do
    if Process.whereis(__MODULE__), do: GenServer.call(__MODULE__, :cleanup), else: :ok
  end

  def stats do
    %{
      index_entries: table_size(@index_table),
      provider_entries: table_size(@provider_table)
    }
  end

  @impl true
  def init(_opts) do
    ensure_table(@index_table)
    ensure_table(@provider_table)
    schedule_cleanup()
    {:ok, %{}}
  end

  @impl true
  def handle_call({:put_provider, key, expires_at, value}, _from, state) do
    cleanup_table(@provider_table)
    trim_provider_table()
    :ets.insert(@provider_table, {key, expires_at, value})
    {:reply, :ok, state}
  end

  def handle_call(:cleanup, _from, state) do
    cleanup_tables()
    {:reply, :ok, state}
  end

  @impl true
  def handle_info(:cleanup, state) do
    cleanup_tables()
    schedule_cleanup()
    {:noreply, state}
  end

  defp lookup(table, key, now) do
    case :ets.lookup(table, key) do
      [{^key, expires_at, value}] when expires_at > now -> {:ok, value}
      [{^key, _expires_at, _value}] -> safe_delete(table, key) && :miss
      _ -> :miss
    end
  rescue
    ArgumentError -> :miss
  end

  defp put(table, key, expires_at, value) do
    :ets.insert(table, {key, expires_at, value})
    :ok
  rescue
    ArgumentError -> :cache_unavailable
  end

  defp ensure_table(table) do
    case :ets.whereis(table) do
      :undefined ->
        :ets.new(table, [
          :named_table,
          :public,
          :set,
          read_concurrency: true,
          write_concurrency: true
        ])

      existing ->
        existing
    end
  end

  defp cleanup_tables do
    cleanup_table(@index_table)
    cleanup_table(@provider_table)
  end

  defp cleanup_table(table) do
    now = System.monotonic_time(:millisecond)
    :ets.select_delete(table, [{{:_, :"$1", :_}, [{:"=<", :"$1", now}], [true]}])
  rescue
    ArgumentError -> 0
  end

  defp trim_provider_table do
    overflow = table_size(@provider_table) - @max_provider_entries + 1

    if overflow > 0 do
      @provider_table
      |> :ets.tab2list()
      |> Enum.sort_by(fn {_key, expires_at, _value} -> expires_at end)
      |> Enum.take(overflow)
      |> Enum.each(fn {key, _expires_at, _value} -> :ets.delete(@provider_table, key) end)
    end
  end

  defp safe_delete(table, key) do
    :ets.delete(table, key)
    true
  rescue
    ArgumentError -> false
  end

  defp table_size(table) do
    case :ets.info(table, :size) do
      :undefined -> 0
      size -> size
    end
  end

  defp schedule_cleanup, do: Process.send_after(self(), :cleanup, @cleanup_interval_ms)
end
