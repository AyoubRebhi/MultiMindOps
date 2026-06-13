/* ============================================================================
   mockDockerfile.js — the AI-generated Dockerfile for the demo project, plus
   the corrected version the Docker Corrector Agent proposes after the first
   (intentionally failing) build. MOCK ONLY.

   The "generated" Dockerfile carries a couple of deliberate defects so the
   Docker Corrector flow has something real to fix:
     • `npm install` (non-deterministic) instead of `npm ci`
     • runtime stage ships ALL node_modules (no prod-only prune)
     • EXPOSE 8080 while the BFF actually binds 3000  → port mismatch
     • runs as root, no NODE_ENV
   ========================================================================== */

export const mockGeneratedDockerfile = `# syntax=docker/dockerfile:1
# ---- Build stage ---------------------------------------------------------
FROM node:18-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

# ---- Runtime stage -------------------------------------------------------
FROM node:18-alpine AS runtime
WORKDIR /app

COPY --from=build /app/dist ./dist
COPY --from=build /app/node_modules ./node_modules

EXPOSE 8080
CMD ["node", "dist/server.js"]
`;

export const mockCorrectedDockerfile = `# syntax=docker/dockerfile:1
# ---- Build stage ---------------------------------------------------------
FROM node:18-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- Runtime stage -------------------------------------------------------
FROM node:18-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app

COPY --from=build /app/dist ./dist
COPY --from=build /app/package*.json ./
RUN npm ci --omit=dev

EXPOSE 3000
USER node
CMD ["node", "dist/server.js"]
`;

export const mockDockerfileMeta = {
  projectId: 'prj-002',
  service: 'customer-portal',
  baseImage: 'node:18-alpine',
  strategy: 'Multi-stage (build → slim runtime)',
  generatedBy: 'Docker Agent',
  status: 'generated',
};

export default mockGeneratedDockerfile;
