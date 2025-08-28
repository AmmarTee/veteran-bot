# Multi-stage build for Next.js UI
FROM node:18-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* pnpm-lock.yaml* yarn.lock* ./
RUN \
  if [ -f yarn.lock ]; then yarn --frozen-lockfile; \
  elif [ -f package-lock.json ]; then npm ci; \
  elif [ -f pnpm-lock.yaml ]; then npm i -g pnpm && pnpm i --frozen-lockfile; \
  else npm i; fi

FROM node:18-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Debug: verify files and config before build
RUN ls -la && \
  echo "----- tsconfig.json -----" && cat tsconfig.json || true && \
  echo "----- jsconfig.json -----" && cat jsconfig.json || true && \
  echo "----- lib/ -----" && ls -la lib || true && \
  echo "----- src/lib/ -----" && ls -la src/lib || true && \
  echo "----- app/lib/ -----" && ls -la app/lib || true
RUN npm run build

FROM node:18-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN apk add --no-cache curl && adduser -D -H -u 1001 appuser && chown -R appuser:appuser /app
USER appuser
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD curl -fsS http://localhost:3000/healthz || exit 1
CMD ["npm", "start"]
