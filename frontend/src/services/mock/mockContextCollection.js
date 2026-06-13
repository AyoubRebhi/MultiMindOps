/* ============================================================================
   mockContextCollection.js — output of the Repository Context Analysis step
   (Section 3). The agent inspects the repo and reports categorized findings:
   languages, frameworks, dependencies, build tools and containerization status.
   MOCK ONLY — nothing is scanned.
   ========================================================================== */

export const mockContextCollection = {
  repository: 'github.com/cloudforge/customer-portal-api',
  filesScanned: 214,
  analyzedAt: '2026-06-13T08:01:00Z',

  // Categorized findings → rendered as a grid of cards
  categories: [
    {
      key: 'languages',
      title: 'Languages',
      icon: 'fa-code',
      items: [
        { name: 'Java', detail: '94% · 18,420 LOC', icon: 'fa-java', brand: true },
        { name: 'SQL', detail: '4% · Flyway migrations', icon: 'fa-database' },
        { name: 'Shell', detail: '2% · build scripts', icon: 'fa-terminal' },
      ],
    },
    {
      key: 'frameworks',
      title: 'Frameworks',
      icon: 'fa-layer-group',
      items: [
        { name: 'Spring Boot', detail: '3.5.0', icon: 'fa-leaf' },
        { name: 'Spring Web (MVC)', detail: 'REST controllers', icon: 'fa-globe' },
        { name: 'Spring Data JPA', detail: 'Hibernate 6', icon: 'fa-database' },
        { name: 'Spring Actuator', detail: 'health & metrics', icon: 'fa-heart-pulse' },
      ],
    },
    {
      key: 'dependencies',
      title: 'Dependencies',
      icon: 'fa-cubes',
      items: [
        { name: 'spring-boot-starter-web', detail: 'compile', icon: 'fa-cube' },
        { name: 'spring-boot-starter-data-jpa', detail: 'compile', icon: 'fa-cube' },
        { name: 'postgresql', detail: 'runtime · 42.7.3', icon: 'fa-database' },
        { name: 'flyway-core', detail: 'compile · 10.x', icon: 'fa-cube' },
        { name: 'lombok', detail: 'provided', icon: 'fa-cube' },
      ],
    },
    {
      key: 'buildTools',
      title: 'Build Tools',
      icon: 'fa-screwdriver-wrench',
      items: [
        { name: 'Maven', detail: '3.9.6', icon: 'fa-cube' },
        { name: 'Maven Wrapper', detail: 'mvnw present', icon: 'fa-wrench' },
        { name: 'JaCoCo', detail: 'coverage report', icon: 'fa-chart-pie' },
        { name: 'Spotless', detail: 'format check', icon: 'fa-broom' },
      ],
    },
  ],

  // Containerization status → its own status card
  containerization: {
    status: 'ready',
    dockerfilePresent: true,
    multiStage: true,
    baseImage: 'eclipse-temurin:21-jre-alpine',
    exposedPort: 8080,
    healthcheck: '/actuator/health',
    dockerignorePresent: true,
    checks: [
      { label: 'Dockerfile present', ok: true },
      { label: 'Multi-stage build', ok: true },
      { label: '.dockerignore present', ok: true },
      { label: 'Non-root runtime user', ok: true },
      { label: 'Image tag strategy (SHA)', ok: false },
    ],
  },
};

export default mockContextCollection;
