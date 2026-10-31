# Built from the repository root (docker-compose.yml sets the context): the
# frontend is an npm workspace, and its lockfile is the root's.

# Stage 1: install dependencies and build the app
FROM node:24-alpine AS builder
WORKDIR /app

# Dependencies first, for caching
COPY package.json package-lock.json ./
COPY frontend/package.json ./frontend/
RUN npm ci --workspace frontend --include-workspace-root=false

COPY frontend ./frontend
# Next.js inlines NEXT_PUBLIC_* into the browser bundle when it builds, so the
# backend's address is a build argument: setting it when the container starts
# changes nothing.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build --workspace frontend

# Stage 2: production runner
FROM node:24-alpine AS runner
# curl for the healthcheck
RUN apk add --no-cache curl
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=builder /app/package.json /app/package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/frontend/package.json /app/frontend/next.config.ts ./frontend/
COPY --from=builder /app/frontend/public ./frontend/public
COPY --from=builder /app/frontend/.next ./frontend/.next

WORKDIR /app/frontend
EXPOSE 3000

# Healthcheck to ensure the UI is responsive
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:${PORT:-3000} || exit 1

CMD ["npm", "start"]
