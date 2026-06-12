import { Suspense, lazy } from 'react';
import { Routes, Route } from 'react-router-dom';
import PlatformLayout from '@/layouts/PlatformLayout';
import AuthLayout from '@/layouts/AuthLayout';
import OnboardingLayout from '@/layouts/OnboardingLayout';
import LoadingSpinner from '@/components/common/LoadingSpinner';

/*
 * Routes are code-split with React.lazy. Three shells:
 *   - AuthLayout       → /auth/* (split-screen sign in/up, password reset)
 *   - OnboardingLayout → /onboarding/* and /invite/* (workspace setup, accept)
 *   - PlatformLayout   → the authenticated app (sidebar + top bar)
 * Add new authenticated pages under the PlatformLayout block and the role nav
 * in utils/constants.js (ROLE_NAV).
 */

// Auth
const SignInPage = lazy(() => import('@/pages/auth/SignInPage'));
const SignUpPage = lazy(() => import('@/pages/auth/SignUpPage'));
const ForgotPasswordPage = lazy(() => import('@/pages/auth/ForgotPasswordPage'));
const ResetPasswordPage = lazy(() => import('@/pages/auth/ResetPasswordPage'));

// Onboarding / invitation
const WorkspaceSetupPage = lazy(() => import('@/pages/onboarding/WorkspaceSetupPage'));
const InvitationLandingPage = lazy(() => import('@/pages/invite/InvitationLandingPage'));
const CompleteRegistrationPage = lazy(() => import('@/pages/invite/CompleteRegistrationPage'));

// Platform
const DashboardRouter = lazy(() => import('@/pages/Dashboard/DashboardRouter'));
const Projects = lazy(() => import('@/pages/Projects/Projects'));
const ProjectDetails = lazy(() => import('@/pages/ProjectDetails/ProjectDetails'));
const Workflows = lazy(() => import('@/pages/Workflows/Workflows'));
const Architecture = lazy(() => import('@/pages/Architecture/Architecture'));
const Infrastructure = lazy(() => import('@/pages/Infrastructure/Infrastructure'));
const Artifacts = lazy(() => import('@/pages/Artifacts/Artifacts'));
const Settings = lazy(() => import('@/pages/Settings/Settings'));

// Admin
const UserManagementPage = lazy(() => import('@/pages/admin/UserManagementPage'));
const InvitationsPage = lazy(() => import('@/pages/admin/InvitationsPage'));
const AwsCredentialsPage = lazy(() => import('@/pages/admin/AwsCredentialsPage'));

const NotFound = lazy(() => import('@/pages/NotFound/NotFound'));

export default function AppRoutes() {
  return (
    <Suspense fallback={<LoadingSpinner center label="Loading…" />}>
      <Routes>
        {/* Auth */}
        <Route element={<AuthLayout />}>
          <Route path="auth/signin" element={<SignInPage />} />
          <Route path="auth/signup" element={<SignUpPage />} />
          <Route path="auth/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="auth/reset-password" element={<ResetPasswordPage />} />
        </Route>

        {/* Onboarding + invitation acceptance */}
        <Route element={<OnboardingLayout />}>
          <Route path="onboarding/workspace" element={<WorkspaceSetupPage />} />
          <Route path="invite/:token" element={<InvitationLandingPage />} />
          <Route path="invite/:token/complete" element={<CompleteRegistrationPage />} />
        </Route>

        {/* Authenticated platform */}
        <Route element={<PlatformLayout />}>
          <Route index element={<DashboardRouter />} />
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:id" element={<ProjectDetails />} />
          <Route path="workflows" element={<Workflows />} />
          <Route path="architecture" element={<Architecture />} />
          <Route path="infrastructure" element={<Infrastructure />} />
          <Route path="artifacts" element={<Artifacts />} />
          <Route path="members" element={<UserManagementPage />} />
          <Route path="invitations" element={<InvitationsPage />} />
          <Route path="aws-credentials" element={<AwsCredentialsPage />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
