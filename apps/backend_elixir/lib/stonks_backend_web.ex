defmodule StonksBackendWeb do
  def controller do
    quote do
      use Phoenix.Controller,
        formats: [:json],
        layouts: []

      import Plug.Conn
      alias StonksBackendWeb.Router.Helpers, as: Routes
    end
  end

  def router do
    quote do
      use Phoenix.Router, helpers: true
      import Plug.Conn
      import Phoenix.Controller
    end
  end

  defmacro __using__(which) when is_atom(which) do
    apply(__MODULE__, which, [])
  end
end
