/* ============================================================================
   types/workflowAnalysis.js — strongly-typed contract for the Workflow Analysis
   Dashboard (/workflows/:projectId/analysis).

   This is a JSX codebase, so "interfaces" are expressed as JSDoc @typedefs.
   They give editors full IntelliSense + type-checking on the aggregated
   analysis payload WITHOUT introducing TypeScript (a second toolchain).

   The shape mirrors the single aggregated backend response the page consumes:

     GET /api/workflows/{projectId}/analysis  ->  WorkflowAnalysis

   One request, one object, distributed to the five panels. No per-panel calls.
   ========================================================================== */

/**
 * Terminal/active state of the workflow analysis run.
 * @typedef {'RUNNING' | 'DONE' | 'FAILED'} WorkflowAnalysisStatus
 */

/* ── Section A — Context header ───────────────────────────────────────────── */
/**
 * @typedef {Object} ProjectInfo
 * @property {string}  id            Project id (echoes the route :projectId).
 * @property {string}  name          Human project name.
 * @property {string}  repositoryUrl Full repository URL.
 * @property {string} [branch]       Analyzed branch (default branch if omitted).
 * @property {string} [logoIcon]     FontAwesome class for the project glyph.
 * @property {boolean}[brandIcon]    Whether logoIcon is a fa-brands glyph.
 */

/* ── Customer Portal panel (business-readable) ────────────────────────────── */
/**
 * @typedef {Object} CustomerPortal
 * @property {string}   overview       One-paragraph project overview.
 * @property {string}   systemPurpose  What the system is for, in plain language.
 * @property {string}   inferredDomain Business domain inferred from the repo.
 * @property {string[]} actors         Identified users/actors of the system.
 * @property {string}   description    Extended high-level description.
 */

/* ── Code Analysis panel (technical) ──────────────────────────────────────── */
/**
 * @typedef {Object} TechItem
 * @property {string}  name       Display name (e.g. "Spring Boot").
 * @property {string} [version]   Detected version, if any.
 * @property {string} [icon]      FontAwesome class.
 * @property {boolean}[brand]     Whether icon is a fa-brands glyph.
 */
/**
 * @typedef {Object} CodeAnalysis
 * @property {TechItem[]} languages
 * @property {TechItem[]} frameworks
 * @property {TechItem[]} libraries
 * @property {string[]}   packageManagers   e.g. ["Maven", "npm"].
 * @property {string[]}   buildTools         e.g. ["Gradle", "Vite"].
 * @property {RepoCharacteristic[]} repositoryCharacteristics
 */
/**
 * @typedef {Object} RepoCharacteristic
 * @property {string}  label  e.g. "Lines of Code", "Dockerfile present".
 * @property {string}  value  Display value ("12,480", "Yes").
 * @property {string} [icon]  FontAwesome class.
 * @property {boolean}[ok]    Optional boolean signal (drives check/cross icon).
 */

/* ── Architecture Intelligence panel ──────────────────────────────────────── */
/**
 * @typedef {'MONOLITH' | 'MICROSERVICES' | 'SERVERLESS' | 'HYBRID' | string} ArchitectureModel
 */
/**
 * @typedef {Object} Architecture
 * @property {string}            architectureType    Free-text classification.
 * @property {ArchitectureModel} model               Monolith/Microservices/...
 * @property {number}           [confidence]         0–100 match confidence.
 * @property {string[]}          observations        Architectural observations.
 * @property {string}            suggestedPattern     Recommended pattern.
 * @property {string[]}          scalingAssumptions   Scaling assumptions.
 * @property {string}            deploymentStrategy   Recommended deploy strategy.
 */

/* ── Infrastructure Recommendation panel ──────────────────────────────────── */
/**
 * @typedef {Object} InfraRecommendation
 * @property {string}  service  Recommended service/resource (e.g. "AWS ECS Fargate").
 * @property {string}  reason   Why it is recommended.
 * @property {string} [icon]    FontAwesome class.
 */
/**
 * @typedef {Object} InfrastructureRecommendations
 * @property {InfraRecommendation[]} awsServices    Headline AWS service picks.
 * @property {InfraRecommendation[]} compute
 * @property {InfraRecommendation[]} storage
 * @property {InfraRecommendation[]} networking
 * @property {InfraRecommendation[]} observability
 */

/* ── Security & Containerization panel ────────────────────────────────────── */
/**
 * @typedef {'critical' | 'high' | 'medium' | 'low'} Severity
 */
/**
 * @typedef {Object} SecurityRisk
 * @property {string}   id
 * @property {Severity} severity
 * @property {string}   title
 * @property {string}  [detail]
 * @property {string}  [category]
 */
/**
 * @typedef {Object} SecurityAnalysis
 * @property {number}        [score]           0–100 posture score.
 * @property {string}        [grade]           Letter grade (A–F).
 * @property {string}        [summary]         One-line posture summary.
 * @property {SecurityRisk[]} risks            Security risks/findings.
 * @property {string[]}       recommendations  Security recommendations.
 * @property {string[]}       hardening        Hardening recommendations.
 */
/**
 * @typedef {Object} Containerization
 * @property {string}   dockerSuitability  e.g. "High — cleanly containerizable".
 * @property {string[]} findings           Containerization findings.
 * @property {string[]} imageStrategy      Image strategy recommendations
 *                                         (multi-stage, distroless, slim, ...).
 * @property {string}  [notes]             Optional extra notes.
 */

/* ── Aggregated response (the single object the page fetches) ──────────────── */
/**
 * @typedef {Object} WorkflowAnalysis
 * @property {ProjectInfo}                   projectInfo
 * @property {CustomerPortal}                customerPortal
 * @property {CodeAnalysis}                  codeAnalysis
 * @property {Architecture}                  architecture
 * @property {InfrastructureRecommendations} infrastructureRecommendations
 * @property {SecurityAnalysis}              securityAnalysis
 * @property {Containerization}              containerization
 * @property {WorkflowAnalysisStatus}        status
 * @property {string}                        lastUpdated  ISO-8601 timestamp.
 * @property {?string}                      [error]       Failure message when FAILED.
 */

// This module intentionally exports nothing at runtime; it exists for JSDoc
// types. The empty export keeps it an ES module so `import './...'` is valid.
export {};
