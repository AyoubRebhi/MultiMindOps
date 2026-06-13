/* ============================================================================
   mockSchemaValidationErrors.js — findings reported by the failing schema
   validation (Section 6), rendered as a findings table (severity / line /
   issue / suggested fix). Plus a short note for the manual fix. MOCK ONLY.
   ========================================================================== */

export const mockSchemaValidationErrors = [
  {
    id: 'WFV-001',
    severity: 'high',
    line: 47,
    rule: 'missing-runs-on',
    issue: 'Job "deploy" is missing the required "runs-on" key.',
    suggestedFix: 'Add `runs-on: ubuntu-latest` to the deploy job.',
  },
  {
    id: 'WFV-002',
    severity: 'medium',
    line: 21,
    rule: 'missing-job-name',
    issue: 'Job "build" has no display "name".',
    suggestedFix: 'Add `name: Build & Test` to the build job for readable logs.',
  },
  {
    id: 'WFV-003',
    severity: 'high',
    line: 58,
    rule: 'invalid-step',
    issue: 'Step #7 has neither a "uses" nor a "run" key.',
    suggestedFix: 'Give the step a `run:` command or a `uses:` action reference.',
  },
];

/** Short note for the manual correction (the viewer opens in edit mode). */
export const validationFix = {
  note: 'Add the missing `runs-on` and job `name`, and give step #7 a `run`/`uses` key, then re-run validation.',
};

export default mockSchemaValidationErrors;
