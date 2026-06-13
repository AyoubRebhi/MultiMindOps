/* ============================================================================
   mockWorkflowYaml.js — the GitHub Actions workflow produced by the Workflow
   Generation Agent (Section 5), rendered by <GitHubWorkflowViewer />. This is
   the hardened, "final" version of .github/workflows/deploy.yml. MOCK ONLY.
   ========================================================================== */

export const workflowFilename = '.github/workflows/deploy.yml';

export const mockWorkflowYaml = `name: Build & Deploy to AWS ECS

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  id-token: write

env:
  AWS_REGION: eu-west-1
  ECR_REPOSITORY: customer-portal-api
  ECS_CLUSTER: customer-portal-cluster
  ECS_SERVICE: customer-portal-service

jobs:
  build:
    name: Build & Test
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up JDK 21
        uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: "21"
          cache: maven

      - name: Build with Maven
        run: ./mvnw -B clean verify

      - name: Upload JAR artifact
        uses: actions/upload-artifact@v4
        with:
          name: app-jar
          path: target/*.jar

  deploy:
    name: Build Image & Deploy
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: \${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: \${{ env.AWS_REGION }}

      - name: Login to Amazon ECR
        id: ecr
        uses: aws-actions/amazon-ecr-login@v2

      - name: Build & push Docker image
        env:
          REGISTRY: \${{ steps.ecr.outputs.registry }}
          IMAGE_TAG: \${{ github.sha }}
        run: |
          docker build -t $REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
          docker push $REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG

      - name: Deploy to Amazon ECS
        uses: aws-actions/amazon-ecs-deploy-task-definition@v2
        with:
          cluster: \${{ env.ECS_CLUSTER }}
          service: \${{ env.ECS_SERVICE }}
          wait-for-service-stability: true
`;

export const mockWorkflowMeta = {
  filename: workflowFilename,
  triggers: ['push → main', 'workflow_dispatch'],
  jobs: 2,
  steps: 11,
  runners: ['ubuntu-latest'],
  generatedAt: '2026-06-13T08:03:00Z',
};

export default mockWorkflowYaml;
