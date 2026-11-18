# Product interface

The interface centers on three actions: start a repository review, follow its progress and
read the findings. It uses a white and graphite palette with restrained violet accents,
a searchable review-history sidebar, and responsive navigation.

New review presents two steps: choose a Git repository, local folder or saved source, then
edit a review brief. An actionable general-review brief is selected by default; correctness,
security, performance, and edge-case presets help narrow the work. Branch selection, team mode and patch
proposals are available under Review options. The source and brief remain fixed during preparation.

Review pages initially show the report, three summary measures and the current status.
Findings are ordered by severity and can be filtered by severity and searched by title,
description, or file path. Source evidence is visible on the first finding. Markdown export
includes the full report, source revision, evidence, uncertainty, open questions, and proposed
patches, independently of the current filters. Code fences expand to preserve embedded backticks.
Running reviews show actual completed-specialist counts, execution steps, and active roles.
Review again restores the source type, repository location, branch, and brief; registered
workspaces reopen in the saved-source tab.
Findings, Team and Activity are separate tabs. The team graph is loaded only when needed.
The graph follows live snapshots and recorded activity: reviewing specialists have pulsing
status dots and animated connections, while queued, waiting, completed and stopped specialists
retain distinct states. Motion pauses on a disconnected stream and ends with the review.
Cards show execution counts and their latest recorded action; selecting a specialist opens
its work. The graph supports dragging, zooming, fitting the team and focusing active specialists,
preserving arranged positions and the viewport across activity updates. Team assembly shows
the coordinator until actual specialists are created; larger teams branch on both sides of
the coordinator to keep their cards readable. Reduced-motion preferences suppress
the pulses and connection animation.
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
details, filtering, exports, repeat reviews, history search, mobile layout and dialog behavior.
Graph checks stream snapshots and events through the real SSE reader to cover live activity,
position retention, keyboard inspection, completion, disconnects, assembly and reduced motion.
Screenshots are saved under frontend/test-results.
To test a different local deployment set UI_BASE_URL.
