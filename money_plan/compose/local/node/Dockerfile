FROM docker.io/node:26.5-bookworm-slim

WORKDIR /app

# Node 25+ no longer ships corepack, so install pnpm directly.
RUN npm install -g pnpm@10.30.2 && npm cache clean --force

COPY ./package.json ./pnpm-lock.yaml /app/

RUN pnpm install --frozen-lockfile && pnpm store prune

ENV PATH=./node_modules/.bin/:$PATH
