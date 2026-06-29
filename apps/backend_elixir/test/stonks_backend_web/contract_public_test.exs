defmodule StonksBackendWeb.ContractPublicTest do
  use StonksBackendWeb.ContractCase, async: true

  @moduletag :contract

  @public_endpoint_headers %{
    "access-control-allow-credentials" => "true",
    "access-control-allow-origin" => "http://localhost:5173",
    "content-type" => {:contains, "application/json"},
    "permissions-policy" => "interest-cohort=()",
    "referrer-policy" => "strict-origin-when-cross-origin",
    "x-content-type-options" => "nosniff",
    "x-frame-options" => "DENY"
  }

  @rows [
    %{
      matrix_id: "public.health",
      method: :get,
      path: "/api/public/health",
      status: 200,
      json_subset: %{
        "status" => "ok",
        "service" => "stonks-radar-api",
        "public_read_path" => "snapshot-first"
      },
      json_keys: ["time"],
      response_headers: @public_endpoint_headers,
      absent_response_headers: ["set-cookie"],
      response_cookies: :none
    },
    %{
      matrix_id: "public.snapshot_manifest_proxy",
      method: :get,
      path: "/api/public/snapshot-manifest-proxy",
      status: 200,
      json_subset: %{
        "manifest_url" => "/public/latest/manifest.json",
        "mode" => "local_oci"
      },
      response_headers: @public_endpoint_headers,
      absent_response_headers: ["set-cookie"],
      response_cookies: :none
    }
  ]

  for row <- @rows do
    test "#{row.matrix_id} preserves the DB-free public compatibility contract" do
      row = unquote(Macro.escape(row))
      assert_contract(row)
    end
  end
end
