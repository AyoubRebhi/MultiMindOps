# MultiMinds AI — Frontend Foundation

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
│   ├── common/         StatusBadge, RoleBadge, StatsCard, Card, Modal, Avatar,
│   │                   MemberAvatarGroup, ActivityTimeline, Stepper, AreaChart, …
│   ├── layout/         Sidebar (role-aware), TopNavbar, PageHeader, Breadcrumbs
│   ├── projects/       ProjectCard
│   ├── workflow/       WorkflowCard, TimelineCard, WorkflowTimeline,
│   │                   WorkflowPhaseHeader, PhaseStatusCard, RealtimeLogViewer,
│   │                   DockerfileEditor, DockerCorrectionPanel, BuildResultCard,
│   │                   PlanSelectionCard, TerraformFileViewer/FileTabs,
│   │                   TerraformResourceSummary, Terraform{Validation,Execution,
│   │                   Error}Panel, TerraformEditorWorkspace, TerraformDeploymentResult
│   ├── architecture/   ArchitecturePlanCard
│   ├── infrastructure/ InfrastructureSummaryCard, ResourceTable
│   ├── artifacts/      ArtifactCard
│   ├── workspace/      WorkspaceCard
│   ├── users/          UserCard
│   ├── invitations/    InvitationCard, InviteUserModal
│   └── aws/            AwsCredentialCard
├── pages/
│   ├── auth/           SignIn, SignUp, ForgotPassword, ResetPassword
│   ├── onboarding/     WorkspaceSetupPage (stepper)
│   ├── invite/         InvitationLandingPage, CompleteRegistrationPage
│   ├── admin/          AdminDashboard, UserManagement, Invitations, AwsCredentials
│   ├── workflow/       ProjectAnalysisPage, PlanningPage, DockerPhasePage,
│   │                   TerraformPhasePage, WorkflowPhasePlaceholder
│   └── (platform)      Dashboard(+Router), Projects, ProjectDetails, Workflows,
│                       Architecture, Infrastructure, Artifacts, Settings, NotFound
├── layouts/            PlatformLayout, AuthLayout (split), OnboardingLayout
├── routes/             AppRoutes (lazy-loaded route tree)
├── services/
│   ├── api/            project/workflow/artifact/terraform/architecture/dashboard
│   │                   + auth/workspace/user/invitation/awsCredentials Api,
│   │                   client (Axios), mockAdapter
│   └── mock/           mock* fixtures
├── hooks/              useAsync, useAuth, useProjects, useWorkflows, useUsers,
│                       useInvitations, useWorkspace, useAwsCredentials, …
├── context/            ThemeContext, AuthContext (mock session + role)
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

| Path                       | Shell        | Page                         |
| -------------------------- | ------------ | ---------------------------- |
| `/auth/signin`             | AuthLayout   | Sign In                      |
| `/auth/signup`             | AuthLayout   | Sign Up (Admin)              |
| `/auth/forgot-password`    | AuthLayout   | Forgot Password              |
| `/auth/reset-password`     | AuthLayout   | Reset Password               |
| `/onboarding/workspace`    | Onboarding   | Workspace Setup (stepper)    |
| `/invite/:token`           | Onboarding   | Invitation Landing           |
| `/invite/:token/complete`  | Onboarding   | Complete Registration        |
| `/`                        | Platform     | Dashboard (Admin / DevOps)   |
| `/projects` · `/projects/:id` | Platform  | Projects / Project Details   |
| `/workflows`               | Platform     | Workflows (list + Run CTA)   |
| `/workflows/analysis`      | Platform     | Project Analysis Results     |
| `/workflows/planning`      | Platform     | Planning phase (plan select) |
| `/workflows/docker`        | Platform     | Docker phase (build + fix)   |
| `/workflows/terraform`     | Platform     | Terraform phase (gen→apply)  |
| `/workflows/validation` · `/plan` | Platform | Phase placeholders        |
| `/members`                 | Platform     | User Management (Admin)      |
| `/invitations`             | Platform     | Invitations (Admin)          |
| `/aws-credentials`         | Platform     | AWS Credentials (Admin)      |
| `/artifacts`               | Platform     | Artifacts (DevOps)           |
| `/infrastructure` · `/architecture` | Platform | Infrastructure / Architecture |
| `/settings`                | Platform     | Settings                     |

## Auth & roles (mock)

`AuthContext` holds a **mock** session — no JWT, no real auth, no route guards
(out of scope this phase). It seeds an authenticated **Admin** so the app is
explorable immediately, persists the role to `localStorage`, and drives the
**role-aware sidebar** (`ROLE_NAV` in `utils/constants.js`):

- **ADMIN** → Dashboard · Projects · Workflows · **Members · Invitations · AWS Credentials** · Settings
- **DEVOPS_ENGINEER** → Dashboard · Projects · Workflows · **Artifacts · Infrastructure** · Settings

Switch experiences without a backend via **Sign In → "Enter as Admin / Engineer"**
or the top-bar user menu **"Switch to … view"**.

**Secrets:** AWS secret/session values are never stored or shown in plaintext —
only the last 4 characters can ever be revealed (`AwsCredentialCard`).

## Workflow execution (mock)

The live-run experience at `/workflows/*` is built on a **reusable phase
architecture** so future phases drop straight in. Every phase page is:
`WorkflowTimeline` (top-center, states: not_started · running · completed ·
failed) → `WorkflowPhaseHeader` → numbered `PhaseStatusCard` sections → a
bottom-right "Proceed" CTA.

The journey, all mock-data driven:

```
Run Workflow → Analysis results → Planning (pick a plan) → Docker
            → Dockerfile (Approve/Edit/Reject) → Build logs (streamed)
            → Corrector (on failure) → Build result → next phase
```

- **Analysis** (`/workflows/analysis`) — Code Analysis + Security Guard agent
  output (stack, services, score ring, findings).
- **Planning** (`/workflows/planning`) — planning agent result + 3 side-by-side
  `PlanSelectionCard`s (Low Cost / **Balanced** / High Performance); one select.
- **Docker** (`/workflows/docker`) — `DockerfileEditor` (lightweight Dockerfile
  syntax highlighting, Approve/Edit/Reject) → `RealtimeLogViewer` that **simulates
  a websocket build feed** by replaying scripted log events with Start/Pause/Clear.
  The first build *intentionally fails* so the `DockerCorrectionPanel` (error
  summary + side-by-side diff + Approve/Modify/Reject Fix) gets to shine; the
  rebuild succeeds and `BuildResultCard` shows the image details.
- **Terraform** (`/workflows/terraform`) — six sections: generated `.tf` files
  (file cards + tabbed `TerraformFileViewer` with HCL highlighting, View/Download/
  Edit) → `TerraformResourceSummary` review + Approve/Edit/Reject → validation
  (`fmt/init/validate` via the log viewer; first run fails with findings) →
  execution (`plan/apply`; first run fails → `TerraformErrorPanel`) →
  `TerraformEditorWorkspace` (original vs current diff, apply-fix/edit/save,
  Revalidate/Retry) → `TerraformDeploymentResult` (infra summary ✓ or failure
  detail). Re-running validation/execution after the fix succeeds.

Mock data: `mockAnalysisResults`, `mockSecurityResults`, `mockPlans`,
`mockDockerfile`, `mockDockerBuildLogs`, `mockDockerCorrection`,
`mockTerraformFiles/Resources/ValidationLogs/ExecutionLogs/ValidationErrors/`
`ExecutionErrors/Results`. Services: `analysisApi`, `planningApi`, `dockerApi`,
`terraformGenerationApi`, `terraformValidationApi`, `terraformExecutionApi`.
**Nothing is really built or applied** — no Docker, no Terraform, no AWS, no
sockets; every build/validate/apply outcome is driven by an attempt counter.

## Responsiveness

- **Desktop (≥992px):** full fixed sidebar; auth pages are split-screen.
- **Tablet/Mobile (<992px):** sidebar collapses into an off-canvas drawer
  (hamburger in the top bar, backdrop to dismiss, auto-closes on navigation);
  auth pages drop the branding panel and go single-column.

## Out of scope (by design, this phase)

UI only — no real API calls, no JWT/authentication, no authorization guards, no
email sending, no AWS credential storage, no business logic. Everything runs on
mock data and is wired so the backend connects later with no page/component
changes.
