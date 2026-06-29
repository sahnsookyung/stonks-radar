defmodule StonksBackend.Application do
  @moduledoc false
  use Application

  @impl true
  def start(_type, _args) do
    children =
      [
        repo_child(),
        {Phoenix.PubSub, name: StonksBackend.PubSub},
        {Finch, name: StonksBackend.Finch},
        oban_child(),
        StonksBackendWeb.Endpoint
      ]
      |> Enum.reject(&is_nil/1)

    opts = [strategy: :one_for_one, name: StonksBackend.Supervisor]
    Supervisor.start_link(children, opts)
  end

  @impl true
  def config_change(changed, _new, removed) do
    StonksBackendWeb.Endpoint.config_change(changed, removed)
    :ok
  end

  defp oban_child do
    config = Application.get_env(:stonks_backend, Oban)

    case Keyword.get(config, :queues) do
      false -> nil
      _ -> {Oban, config}
    end
  end

  defp repo_child do
    if Application.get_env(:stonks_backend, :start_repo, true), do: StonksBackend.Repo
  end
end
