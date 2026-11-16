# Product interface

The interface centers on three actions: start a repository review, follow its progress and
read the findings. It uses a restrained light theme, a persistent review-history sidebar and
responsive navigation.

New review presents two steps: choose a Git repository, local folder or saved source, then
write a review brief. Focus presets help users begin. Branch selection, team mode and patch
proposals are available under Review options. The source and brief remain fixed during preparation.

Review pages initially show the report, three summary measures and the current status.
Findings, Team and Activity are separate tabs. The team graph is loaded only when needed.
Agent details, tool payloads, cost accounting, model breakdowns and trace identifiers are
available on demand. Model selection and the explicit billable connectivity test live in
Workspace settings.

The frontend separates transport (lib/api.ts), review submission (lib/reviews.ts), workspace
and live-review state (hooks), and presentational components. Inputs use visible or accessible
labels; modal drawers use native dialogs with focus restoration and Escape support. The
layout includes narrow-screen navigation and reduced-motion support.

## Browser checks

With the application running at localhost:3000:

    cd frontend
    npm ci
    npx playwright install chromium
    npm run test:e2e

Browser tests intercept every API request using test-only fixtures. They never submit a real
model request or alter production review history. They cover connection, progressive disclosure,
Git branches, local folders, saved sources, model allocation, completed reports, agent errors,
details, mobile layout and dialog behavior. Screenshots are saved under frontend/test-results.
To test a different local deployment set UI_BASE_URL.
