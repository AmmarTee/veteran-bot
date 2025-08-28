FROM node:18-bullseye-slim
WORKDIR /app
COPY package.json package-lock.json* yarn.lock* pnpm-lock.yaml* ./
RUN \
  if [ -f yarn.lock ]; then yarn --frozen-lockfile --production; \
  elif [ -f package-lock.json ]; then npm ci --omit=dev; \
  elif [ -f pnpm-lock.yaml ]; then npm i -g pnpm && pnpm i --frozen-lockfile --prod; \
  else npm i --omit=dev; fi
COPY . .
ENV NODE_ENV=production
USER node
CMD ["npm", "start"]
