# Public launch review

Review baseline: `42947ec` (2026-09-14). This is a source/configuration review,
not a completed security scan or authorization to change repository visibility.

## Before making the repository public

1. **Keep the displayed evaluation suite together.** The 17 tasks shown on the
   site include the 31 evaluation files as public material. Keep existing paths,
   digests and historical results. No private companion is required for this
   suite. Historical "hidden" means candidate-workspace isolation, not secrecy
   after publication. Future private holdouts require separately versioned tasks.
2. **Audit everything that becomes public.** Scan all branches/tags and history
   for credentials, transcripts, personal/customer data and internal URLs;
   inspect releases and Actions artifacts too. Rotate any exposed credentials.
   No dedicated full-history secret scan has been completed in this review.
3. **Verify redistribution rights.** Root metadata and LICENSE say Apache-2.0;
   README explicitly preserves third-party fixture/baseline licensing. Inventory
   each source and generated baseline's origin, license and required notices.
   A root license alone is not evidence that every included fixture is cleared.
4. **Prepare public contribution controls.** Confirm required CI and maintainer
   approval on main, stale-approval dismissal, and fork workflow approval policy.
   Keep private grading and credentials out of fork-triggered CI. The current
   CI uses pull_request with read-only contents permission; preserve that boundary.
   Enable a monitored private vulnerability-reporting channel and document it
   before launch. Assign a conduct-reporting contact before adopting a code of
   conduct; do not publish a policy with an unmonitored address.
5. **Make the standalone checkout reproducible.** Test the README setup and
   public baseline checks from a fresh fork without workspace credentials or
   sibling repositories. The converter-regression workflow checks out extensions
   and bench and must remain usable with the public suite after publication.

## Consolidation and cleanup

- CONTRIBUTING.md is the contribution-policy source; README links to it.
  Issue and PR templates make the issue-first review policy visible without
  introducing another bot or a new required CI job.
- Keep current guides for harness, measurement design, measurement runs and
  provider login; they address distinct jobs. Link rather than merge them into
  a large README.
- Review docs/design.md: its Deliberate limits section still describes the first
  CRUD fixture and says there is no leaderboard. Label historical design sections
  and distinguish the repository evaluator from the separately hosted results UI.
- Review docs/superpowers/plans/2026-09-05-drf-flask.md for decisions worth retaining
  in maintained docs before archiving the implementation plan. Do not remove
  fixtures or frozen baselines as cleanup; they are reproducibility evidence.
- .gitignore now excludes .env.* with an explicit !.env.example exception. Local .worktrees-unused/ in
  the existing bench checkout is untracked, not published repository content;
  inspect ownership before removing it.
- Keep public result JSON and source hashes traceable to exact benchmark revisions.
  The public site lives in sanka-public, so source publication and website
  deployment are separate release steps.

## Contribution policy choice

Issue-first is this project's policy, not a universal GitHub requirement.
Contributors may reuse an existing issue. Substantial changes need scope agreement
before implementation; small fixes need a linked issue but no advance agreement.
Maintainers may defer unlinked PRs. Use Closes #123 only when the PR resolves the
issue, and Refs #123 for partial work. No CLA, DCO bot, automatic closure bot or
new mandatory status check is introduced by this preparation.

References:
- https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue
- https://github.com/scikit-learn/scikit-learn/blob/main/CONTRIBUTING.md
- https://github.com/EleutherAI/lm-evaluation-harness/blob/main/docs/CONTRIBUTING.md
