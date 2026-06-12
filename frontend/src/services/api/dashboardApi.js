/* ============================================================================
   dashboardApi.js — aggregated metrics for the Dashboard landing page.
   ========================================================================== */
import {
  mockDashboardStats,
  mockDeploymentsTrend,
  mockActivityFeed,
} from '@/services/mock/mockDashboard';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const dashboardApi = {
  /** GET /dashboard/summary */
  async getSummary() {
    // if (!USE_MOCK) return apiClient.get('/dashboard/summary');
    return mockResponse({
      stats: mockDashboardStats,
      trend: mockDeploymentsTrend,
      activity: mockActivityFeed,
    });
  },
};

export default dashboardApi;
