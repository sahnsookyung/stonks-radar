defmodule StonksBackendWeb.Router do
  use StonksBackendWeb, :router

  pipeline :api do
    plug :accepts, ["json"]
    plug StonksBackendWeb.Plugs.SecurityHeaders
  end

  scope "/api", StonksBackendWeb do
    pipe_through :api

    scope "/public" do
      get "/health", PublicController, :health
      get "/snapshot-manifest-proxy", PublicController, :snapshot_manifest_proxy
      get "/trump-disclosures/summary", PublicController, :trump_disclosures_summary
      get "/filings", PublicController, :filings
      get "/transactions", PublicController, :transactions
      get "/entities/:ticker/insiders", PublicController, :entity_insiders
      get "/market/history", PublicController, :market_history
      get "/search", PublicController, :search
    end

    scope "/auth" do
      get "/google/config", AuthController, :google_config
      get "/google/start", AuthController, :google_start
      get "/google/callback", AuthController, :google_callback
      post "/login", AuthController, :login
      post "/logout", AuthController, :logout
      get "/me", AuthController, :me
    end

    scope "/admin" do
      get "/dashboard", AdminController, :dashboard
      get "/provider-budgets", AdminController, :provider_budgets
      post "/provider-budgets/:budget_id/kill-switch", AdminController, :kill_switch
      get "/sources", AdminController, :sources
      post "/sources", AdminController, :create_source
      get "/instruments/search", AdminController, :instrument_search
      get "/instruments/review-requests", AdminController, :instrument_review_requests

      post "/instruments/review-requests/:request_id",
           AdminController,
           :update_instrument_review_request

      get "/instruments/:instrument_id", AdminController, :instrument_detail
      post "/instruments/refresh", AdminController, :refresh_instruments
      post "/ingest/url", AdminController, :ingest_url
      post "/summaries/url", AdminController, :summarize_url
      post "/ingest/file", AdminController, :ingest_file
      get "/source-documents/:document_id", AdminController, :source_document
      post "/source-facts/:fact_id/review", AdminController, :review_fact
      get "/events/candidates", AdminController, :event_candidates
      post "/events/:event_id/review", AdminController, :review_event
      post "/snapshots/build", AdminController, :snapshots_build
      get "/snapshots/candidates", AdminController, :snapshots_candidates
      post "/snapshots/publish", AdminController, :snapshots_publish
      post "/snapshots/rollback", AdminController, :snapshots_rollback
      post "/release-controls/quarantine", AdminController, :quarantine_release
      post "/jobs/:job_id/replay", AdminController, :replay_job
      post "/corrections", AdminController, :create_correction
      get "/audit-log", AdminController, :audit_log
      post "/snapshots/build-now-local", AdminController, :snapshots_build_now_local
      post "/snapshots/build-seed-local", AdminController, :snapshots_build_seed_local
    end

    scope "/instruments" do
      get "/search", InstrumentsController, :search
      post "/resolve", InstrumentsController, :resolve
      get "/:instrument_id", InstrumentsController, :detail
      post "/review-requests", InstrumentsController, :create_review_request
    end

    scope "/internal" do
      post "/news/email-alerts", InternalController, :receive_news_email_alert
    end
  end
end
