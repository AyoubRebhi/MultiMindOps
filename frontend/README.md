# CloudForge AI — Frontend Foundation

React frontend for the **AI Cloud Engineering Platform**. This is a *foundation
phase* build: a scalable, component-driven, route-based UI that runs entirely on
**mock data** and is wired so the real backend can be connected later with
minimal changes.

> Converted from the NexusAI HTML/CSS/JS template — the design system (dark/light
> theming, cards, dashboard shell) was ported into React; all interactivity was
> reimplemented with React state/hooks (no jQuery / Bootstrap JS / AOS).

## Stack

- **React 18** + **Vite** (functional components & hooks)
- **React Router v6** (code-split routes)
- **Axios** — configured client, *prepared only* (no real calls yet)
- **Context API** for theme/state (no Redux)
- **Bootstrap 5 CSS** (grid/utilities) + **Font Awesome** (icons) + ported theme

## Getting started

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

Other scripts: `npm run build`, `npm run preview`, `npm run lint`.

## Project structure

```
src/
├── assets/styles/      theme.css (ported design system) + app.css (additions)
├── components/
│   ├── common/         StatusBadge, StatsCard, Card, ProgressBar, AreaChart, …
│   ├── layout/         Sidebar, TopNavbar, PageHeader, Breadcrumbs, ContentContainer
│   ├── projects/       ProjectCard
│   ├── workflow/        WorkflowCard, TimelineCard
│   ├── architecture/   ArchitecturePlanCard
│   ├── infrastructure/ InfrastructureSummaryCard, ResourceTable
│   └── artifacts/      ArtifactCard
├── pages/              Dashboard, Projects, ProjectDetails, Workflows,
│                       Architecture, Infrastructure, Settings, NotFound
├── layouts/            PlatformLayout (sidebar + topbar shell)
├── routes/             AppRoutes (lazy-loaded route tree)
├── services/
│   ├── api/            projectApi, workflowApi, artifactApi, terraformApi,
│   │                   architectureApi, dashboardApi, client (Axios), mockAdapter
│   └── mock/           mock* fixtures
├── hooks/              useAsync, useProjects, useWorkflows, useArtifacts,
│                       useTheme, useClickOutside
├── context/            ThemeContext
├── utils/              constants, formatters
└── App.jsx
```

## Mock data → real API

Pages never import mock files directly — they call **hooks** → **service
modules** → mock data:

```
page → useProjects() → projectApi.list() → mockResponse(mockProjects)
```

To switch on the backend later:

1. Set `VITE_USE_MOCK=false` and `VITE_API_BASE_URL` in `.env` (see `.env.example`).
2. In each `services/api/*.js`, uncomment the `apiClient` line and remove the
   mock branch. No page or component changes required.

## Routes

| Path             | Page             |
| ---------------- | ---------------- |
| `/`              | Dashboard        |
| `/projects`      | Projects         |
| `/projects/:id`  | Project Details  |
| `/workflows`     | Workflows        |
| `/architecture`  | Architecture     |
| `/infrastructure`| Infrastructure   |
| `/settings`      | Settings         |

## Responsiveness

- **Desktop (≥992px):** full fixed sidebar.
- **Tablet/Mobile (<992px):** sidebar collapses into an off-canvas drawer
  (hamburger in the top bar, backdrop to dismiss, auto-closes on navigation).

## Out of scope (by design, this phase)

No real API calls, no authentication, no business logic, no hardcoded workflow
execution. This is the structural foundation only.
