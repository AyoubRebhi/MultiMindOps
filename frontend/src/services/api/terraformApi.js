/* ============================================================================
   terraformApi.js — Terraform / IaC concerns: artifacts of type "terraform",
   plus the infrastructure summary the Infrastructure page consumes.
   ========================================================================== */
import { mockArtifacts } from '@/services/mock/mockArtifacts';
import { mockInfrastructure } from '@/services/mock/mockInfrastructure';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const terraformApi = {
  /** GET /terraform/artifacts — Terraform-type artifacts only. */
  async listArtifacts() {
    // if (!USE_MOCK) return apiClient.get('/terraform/artifacts');
    return mockResponse(mockArtifacts.filter((a) => a.type === 'terraform'));
  },

  /** GET /infrastructure/summary — provisioned resources + cost breakdown. */
  async getInfrastructureSummary() {
    // if (!USE_MOCK) return apiClient.get('/infrastructure/summary');
    return mockResponse(mockInfrastructure);
  },
};

export default terraformApi;
