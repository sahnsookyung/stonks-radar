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
  @public_no_store_headers Map.put(@public_endpoint_headers, "cache-control", "no-store")
  @market_license_limited_headers Map.merge(@public_no_store_headers, %{
                                    "x-market-data-source" => "license-limited"
                                  })

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
      matrix_id: "public.status.db_free_shape",
      method: :get,
      path: "/api/public/status",
      status: 200,
      json_subset: %{
        "status" => "ok",
        "public_pages_depend_on_backend" => false,
        "snapshot_storage" => "local_oci"
      },
      json_keys: ["metrics"],
      response_headers: @public_no_store_headers,
      absent_response_headers: ["set-cookie"],
      response_cookies: :none
    },
    %{
      matrix_id: "public.provider_status.db_free_shape",
      method: :get,
      path: "/api/public/provider-status",
      status: 200,
      json_subset: %{"status" => "ok"},
      json_keys: ["market_data_providers"],
      response_headers: @public_no_store_headers,
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
    },
    %{
      matrix_id: "public.search.missing_query_validation",
      method: :get,
      path: "/api/public/search",
      status: 422,
      json_subset: %{
        "detail" => [
          %{"loc" => ["query", "q"], "msg" => "Field required", "type" => "value_error"}
        ]
      },
      response_headers: @public_no_store_headers,
      absent_response_headers: ["set-cookie"],
      response_cookies: :none
    },
    %{
      matrix_id: "public.search.short_query_validation",
      method: :get,
      path: "/api/public/search?q=A",
      status: 422,
      json_subset: %{
        "detail" => [
          %{
            "loc" => ["query", "q"],
            "msg" => "String should have at least 2 characters",
            "type" => "value_error"
          }
        ]
      },
      response_headers: @public_no_store_headers,
      absent_response_headers: ["set-cookie"],
      response_cookies: :none
    },
    %{
      matrix_id: "public.market_history.license_limited_fallback",
      method: :get,
      path: "/api/public/market/history?symbols=AAPL&start=2026-01-01&end=2026-01-03",
      status: 200,
      json_subset: %{
        "status" => "license_limited",
        "display_mode" => "public",
        "series" => [%{"symbol" => "AAPL", "points" => []}]
      },
      response_headers: @market_license_limited_headers,
      absent_response_headers: ["set-cookie"],
      response_cookies: :none
    },
    %{
      matrix_id: "public.market_history.inverted_window_validation",
      method: :get,
      path: "/api/public/market/history?symbols=AAPL&start=2026-01-03&end=2026-01-01",
      status: 400,
      json_subset: %{"detail" => "start date must be before end date"},
      response_headers: @public_no_store_headers,
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
