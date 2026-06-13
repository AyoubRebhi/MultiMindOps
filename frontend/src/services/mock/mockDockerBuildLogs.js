/* ============================================================================
   mockDockerBuildLogs.js — scripted build output streamed line-by-line by the
   <RealtimeLogViewer /> to *simulate* a websocket build feed. No real Docker
   build ever runs.

   Two scripts:
     • failingBuildLogs  — first attempt, fails on the missing build dependency
                           (caused by the defects in the generated Dockerfile)
     • successBuildLogs  — rebuild after the corrector's fix is approved
   Each entry: { level, text }. `level` maps to a color in the log viewer:
   info | cmd | warn | error | success.
   ========================================================================== */

export const failingBuildLogs = [
  { level: 'cmd', text: '$ docker build -t customer-portal:latest .' },
  { level: 'info', text: 'Sending build context to Docker daemon  24.81MB' },
  { level: 'info', text: 'Step 1/11 : FROM node:18-alpine AS build' },
  { level: 'info', text: ' ---> a1b2c3d4e5f6' },
  { level: 'info', text: 'Step 2/11 : WORKDIR /app' },
  { level: 'info', text: 'Step 3/11 : COPY package*.json ./' },
  { level: 'info', text: 'Step 4/11 : RUN npm install' },
  { level: 'warn', text: 'npm warn deprecated inflight@1.0.6: this module is not supported' },
  { level: 'info', text: 'added 412 packages, and audited 413 packages in 11s' },
  { level: 'info', text: 'Step 5/11 : COPY . .' },
  { level: 'info', text: 'Step 6/11 : RUN npm run build' },
  { level: 'info', text: '> customer-portal@1.0.0 build' },
  { level: 'info', text: '> vite build' },
  { level: 'error', text: 'sh: vite: not found' },
  { level: 'error', text: 'npm ERR! code ELIFECYCLE' },
  { level: 'error', text: 'npm ERR! errno 127' },
  { level: 'error', text: "The command '/bin/sh -c npm run build' returned a non-zero code: 127" },
  { level: 'error', text: '✖ Build failed — see Docker Corrector below' },
];

export const successBuildLogs = [
  { level: 'cmd', text: '$ docker build -t customer-portal:latest .' },
  { level: 'info', text: 'Sending build context to Docker daemon  24.81MB' },
  { level: 'info', text: 'Step 1/13 : FROM node:18-alpine AS build' },
  { level: 'info', text: 'Step 3/13 : COPY package*.json ./' },
  { level: 'info', text: 'Step 4/13 : RUN npm ci' },
  { level: 'info', text: 'added 412 packages, and audited 413 packages in 9s' },
  { level: 'info', text: 'Step 6/13 : RUN npm run build' },
  { level: 'info', text: '> vite build' },
  { level: 'info', text: 'vite v5.2.0 building for production...' },
  { level: 'info', text: '✓ 318 modules transformed' },
  { level: 'info', text: 'dist/index.html                  0.74 kB' },
  { level: 'info', text: 'dist/assets/index-9f3c2a.js    182.40 kB │ gzip: 58.9 kB' },
  { level: 'success', text: '✓ built in 6.18s' },
  { level: 'info', text: 'Step 8/13 : FROM node:18-alpine AS runtime' },
  { level: 'info', text: 'Step 10/13 : RUN npm ci --omit=dev' },
  { level: 'info', text: 'added 96 packages in 3s' },
  { level: 'info', text: 'Step 12/13 : USER node' },
  { level: 'info', text: 'Step 13/13 : CMD ["node", "dist/server.js"]' },
  { level: 'success', text: 'Successfully built sha256:9f3c2a8b7d61' },
  { level: 'success', text: 'Successfully tagged customer-portal:latest' },
  { level: 'success', text: '✔ Build completed in 42s' },
];

export default { failingBuildLogs, successBuildLogs };
