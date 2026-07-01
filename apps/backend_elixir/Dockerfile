FROM elixir:1.20-otp-29-alpine AS build

RUN apk add --no-cache build-base git
WORKDIR /app/apps/backend_elixir

ENV MIX_ENV=prod
RUN mix local.hex --force && mix local.rebar --force

COPY apps/backend_elixir/mix.exs apps/backend_elixir/mix.lock* ./
RUN mix deps.get --only prod

COPY packages/schemas/snapshots /app/packages/schemas/snapshots
COPY packages/shared-config /app/packages/shared-config
COPY apps/backend_elixir ./
RUN mkdir -p priv/news_sources
COPY apps/api/src/frw_api/services/news/ticker_watchlist.generated.json priv/news_sources/ticker_watchlist.generated.json
COPY config/tracked_entities.json priv/news_sources/tracked_entities.json
RUN mix deps.compile && mix compile && mix release

FROM alpine:3.24 AS app
RUN apk add --no-cache libstdc++ ncurses-libs openssl \
    && addgroup -S stonks \
    && adduser -S -G stonks -h /app -s /sbin/nologin stonks
WORKDIR /app
COPY --from=build --chown=stonks:stonks /app/apps/backend_elixir/_build/prod/rel/stonks_backend ./
COPY --from=build --chown=stonks:stonks /app/packages/schemas /app/packages/schemas
COPY --from=build --chown=stonks:stonks /app/packages/shared-config /app/packages/shared-config

ENV HOME=/app
USER stonks
CMD ["bin/stonks_backend", "start"]
