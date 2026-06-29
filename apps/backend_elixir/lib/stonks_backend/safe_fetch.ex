defmodule StonksBackend.SafeFetch do
  @moduledoc "Production fetch boundary. The fetch-sandbox remains authoritative for v1."

  def fetch_url(_url, _opts \\ []) do
    {:error, :fetch_sandbox_contract_required}
  end
end
