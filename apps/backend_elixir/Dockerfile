FROM elixir:1.20-otp-29-alpine AS build

RUN apk add --no-cache build-base git
WORKDIR /app/apps/backend_elixir

ENV MIX_ENV=prod
RUN mix local.hex --force && mix local.rebar --force

COPY apps/backend_elixir/mix.exs apps/backend_elixir/mix.lock* ./
RUN mix deps.get --only prod

COPY apps/backend_elixir ./
RUN mix deps.compile && mix compile && mix release

FROM alpine:3.20 AS app
RUN apk add --no-cache libstdc++ openssl ncurses-libs
WORKDIR /app
COPY --from=build /app/apps/backend_elixir/_build/prod/rel/stonks_backend ./

ENV HOME=/app
CMD ["bin/stonks_backend", "start"]
