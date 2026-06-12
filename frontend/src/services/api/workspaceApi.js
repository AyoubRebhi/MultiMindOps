/* ============================================================================
   workspaceApi.js — workspace read/create/update. MOCK ONLY.
   ========================================================================== */
import {
  mockWorkspace,
  mockWorkspaceActivity,
} from '@/services/mock/mockWorkspace';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const workspaceApi = {
  /** GET /workspace */
  async get() {
    // if (!USE_MOCK) return apiClient.get('/workspace');
    return mockResponse(mockWorkspace);
  },

  /** GET /workspace/activity */
  async getActivity() {
    // if (!USE_MOCK) return apiClient.get('/workspace/activity');
    return mockResponse(mockWorkspaceActivity);
  },

  /** POST /workspace — onboarding workspace creation. */
  async create(payload) {
    // if (!USE_MOCK) return apiClient.post('/workspace', payload);
    return mockResponse({
      id: `ws-${Date.now()}`,
      plan: 'Team',
      createdAt: new Date().toISOString(),
      ...payload,
    });
  },

  /** PATCH /workspace */
  async update(payload) {
    // if (!USE_MOCK) return apiClient.patch('/workspace', payload);
    return mockResponse({ ...mockWorkspace, ...payload });
  },
};

export default workspaceApi;
