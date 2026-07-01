defmodule StonksBackend.Jobs.SchedulerRunner do
  @moduledoc "Supervised scheduler loop that enqueues due recurring Oban jobs."
  use GenServer

  alias StonksBackend.{Jobs, Settings}
  alias StonksBackend.Jobs.Scheduler

  require Logger

  @default_tick_seconds 60
  @minimum_tick_seconds 10
  @maximum_tick_seconds 3_600

  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)

    if is_nil(name) do
      GenServer.start_link(__MODULE__, opts)
    else
      GenServer.start_link(__MODULE__, opts, name: name)
    end
  end

  def run_once(opts \\ []) do
    opts
    |> scheduler_opts()
    |> Scheduler.schedule_due_jobs()
  end

  @impl GenServer
  def init(opts) do
    state = %{
      enabled?: scheduler_enabled?(opts),
      interval_ms: tick_seconds(opts) * 1_000,
      enqueue_fun: Keyword.get(opts, :enqueue_fun, &Jobs.enqueue/3),
      settings: Keyword.get(opts, :settings),
      now_fun: Keyword.get(opts, :now_fun, &DateTime.utc_now/0)
    }

    if state.enabled? do
      Process.send_after(self(), :tick, initial_delay_ms(opts))
    end

    {:ok, state}
  end

  @impl GenServer
  def handle_info(:tick, state) do
    started_at = System.monotonic_time()

    scheduled_ids =
      try do
        run_once(
          settings: state.settings,
          enqueue_fun: state.enqueue_fun,
          now: state.now_fun.()
        )
      rescue
        exception ->
          Logger.error("elixir_recurring_scheduler_failed error=#{Exception.message(exception)}")

          []
      end

    if scheduled_ids != [] do
      elapsed_ms =
        started_at
        |> System.convert_time_unit(:native, :millisecond)
        |> then(fn started_ms ->
          System.monotonic_time(:millisecond) - started_ms
        end)

      Logger.info(
        "elixir_recurring_scheduler_scheduled count=#{length(scheduled_ids)} elapsed_ms=#{elapsed_ms}"
      )
    end

    Process.send_after(self(), :tick, state.interval_ms)
    {:noreply, state}
  end

  defp scheduler_opts(opts) do
    [
      settings: Keyword.get(opts, :settings),
      enqueue_fun: Keyword.get(opts, :enqueue_fun, &Jobs.enqueue/3),
      now: Keyword.get(opts, :now, DateTime.utc_now())
    ]
  end

  defp scheduler_enabled?(opts) do
    case Keyword.fetch(opts, :enabled?) do
      {:ok, enabled?} -> Settings.truthy?(enabled?)
      :error -> setting(opts, :worker_scheduler_enabled, true) |> Settings.truthy?()
    end
  end

  defp tick_seconds(opts) do
    opts
    |> setting(:worker_scheduler_tick_seconds, @default_tick_seconds)
    |> int_value(@default_tick_seconds)
    |> max(@minimum_tick_seconds)
    |> min(@maximum_tick_seconds)
  end

  defp initial_delay_ms(opts) do
    opts
    |> Keyword.get(:initial_delay_ms, 0)
    |> int_value(0)
    |> max(0)
  end

  defp setting(opts, key, default) do
    opts
    |> Keyword.get(:settings)
    |> case do
      nil -> Settings.get(key, default)
      settings when is_map(settings) -> Map.get(settings, key, default)
      settings when is_list(settings) -> Keyword.get(settings, key, default)
      _settings -> default
    end
  end

  defp int_value(value, _default) when is_integer(value), do: value

  defp int_value(value, default) when is_binary(value) do
    case Integer.parse(String.trim(value)) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  defp int_value(_, default), do: default
end
