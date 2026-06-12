/* ============================================================================
   userApi.js — workspace members management. MOCK ONLY.
   Mutations resolve with the would-be next state so the UI can update
   optimistically without a backend.
   ========================================================================== */
import { mockUsers } from '@/services/mock/mockUsers';
import { mockResponse, mockError } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const userApi = {
  /** GET /workspace/members */
  async list() {
    // if (!USE_MOCK) return apiClient.get('/workspace/members');
    return mockResponse(mockUsers);
  },

  /** GET /workspace/members/:id */
  async getById(id) {
    // if (!USE_MOCK) return apiClient.get(`/workspace/members/${id}`);
    const user = mockUsers.find((u) => u.id === id);
    return user ? mockResponse(user) : mockError(`Member "${id}" not found`);
  },

  /** PATCH /workspace/members/:id — generic update (role, profile…). */
  async update(id, changes) {
    // if (!USE_MOCK) return apiClient.patch(`/workspace/members/${id}`, changes);
    const user = mockUsers.find((u) => u.id === id);
    return mockResponse({ ...user, ...changes });
  },

  /** POST /workspace/members/:id/block */
  async block(id) {
    return this.update(id, { status: 'blocked' });
  },

  /** POST /workspace/members/:id/unblock */
  async unblock(id) {
    return this.update(id, { status: 'active' });
  },

  /** DELETE /workspace/members/:id */
  async remove(id) {
    // if (!USE_MOCK) return apiClient.delete(`/workspace/members/${id}`);
    return mockResponse({ id, removed: true });
  },
};

export default userApi;
