/* ============================================================================
   terraformGenerationApi.js — the Terraform Generation Agent output: the
   generated .tf files and the resource summary they would create. MOCK ONLY.
   ========================================================================== */
import { mockTerraformFiles } from '@/services/mock/mockTerraformFiles';
import { mockTerraformResources } from '@/services/mock/mockTerraformResources';
import { mockResponse } from './mockAdapter';
// import apiClient, { USE_MOCK } from './client';

export const terraformGenerationApi = {
  /** GET /projects/:projectId/terraform/files */
  async getFiles() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/terraform/files`);
    return mockResponse(mockTerraformFiles);
  },

  /** GET /projects/:projectId/terraform/resources */
  async getResources() {
    // if (!USE_MOCK) return apiClient.get(`/projects/${projectId}/terraform/resources`);
    return mockResponse(mockTerraformResources);
  },
};

export default terraformGenerationApi;
