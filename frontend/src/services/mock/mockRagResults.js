/* ============================================================================
   mockRagResults.js — output of the Knowledge Base Retrieval step (Section 4).
   Simulates a HybridRAG query against the devsecops_kb collection: the most
   similar workflow examples, the retrieved chunks with similarity scores, and
   the knowledge sources they came from. MOCK ONLY — no embeddings, no Qdrant.
   ========================================================================== */

export const mockRagResults = {
  query:
    'GitHub Actions workflow: Spring Boot + Maven build, Docker image, push to ECR, deploy to ECS Fargate',
  collection: 'devsecops_kb',
  embeddingModel: 'text-embedding-3-small',
  vectorDims: 1536,
  retrievalMs: 312,
  topScore: 0.94,
  chunksRetrieved: 7,

  // Retrieved workflow examples (the headline cards)
  examples: [
    {
      id: 'kb-ci-014',
      rank: 1,
      title: 'Spring Boot + Docker → GitHub Actions',
      source: 'actions/starter-workflows',
      similarity: 0.94,
      tags: ['spring-boot', 'docker', 'maven'],
      snippet:
        'jobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/setup-java@v4\n        with:\n          distribution: temurin\n          java-version: "21"',
    },
    {
      id: 'kb-ci-027',
      rank: 2,
      title: 'Java + AWS ECS Deployment',
      source: 'aws-actions/amazon-ecs-deploy-task-definition',
      similarity: 0.91,
      tags: ['aws', 'ecs', 'fargate'],
      snippet:
        '- name: Deploy to Amazon ECS\n  uses: aws-actions/amazon-ecs-deploy-task-definition@v2\n  with:\n    cluster: ${{ env.ECS_CLUSTER }}\n    wait-for-service-stability: true',
    },
    {
      id: 'kb-ci-031',
      rank: 3,
      title: 'Maven + GitHub Actions cache',
      source: 'internal/devsecops-handbook',
      similarity: 0.88,
      tags: ['maven', 'cache', 'ci'],
      snippet:
        '- uses: actions/setup-java@v4\n  with:\n    distribution: temurin\n    java-version: "21"\n    cache: maven',
    },
  ],

  // Lower-level retrieved chunks (the "retrieval detail" list)
  chunks: [
    { id: 'chunk-1042', score: 0.94, source: 'starter-workflows/ci/maven.yml', tokens: 186 },
    { id: 'chunk-2271', score: 0.91, source: 'aws-actions/ecs-deploy/README.md', tokens: 142 },
    { id: 'chunk-0387', score: 0.88, source: 'devsecops-handbook/ci-cd.md', tokens: 203 },
    { id: 'chunk-1190', score: 0.83, source: 'docker/build-push-action/usage.md', tokens: 158 },
    { id: 'chunk-0654', score: 0.79, source: 'aws-actions/configure-aws-credentials', tokens: 121 },
  ],

  // Knowledge sources the chunks were drawn from
  sources: [
    { name: 'GitHub Starter Workflows', icon: 'fa-github', brand: true, documents: 24 },
    { name: 'AWS Actions Docs', icon: 'fa-aws', brand: true, documents: 11 },
    { name: 'Internal DevSecOps Handbook', icon: 'fa-book', documents: 38 },
    { name: 'Docker CI Best Practices', icon: 'fa-docker', brand: true, documents: 9 },
  ],
};

export default mockRagResults;
