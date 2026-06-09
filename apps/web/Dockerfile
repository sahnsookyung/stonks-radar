FROM node:22-alpine AS build
WORKDIR /app
RUN apk add --no-cache python3 tzdata
COPY package.json package-lock*.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/shared-types/package.json packages/shared-types/package.json
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/apps/web/dist /srv
EXPOSE 80
CMD ["caddy", "file-server", "--root", "/srv", "--listen", ":80"]
