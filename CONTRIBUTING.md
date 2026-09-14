# Contributing to Sanka Migration Bench

Sanka Bench welcomes bug reports, documentation fixes, new migration tasks and
improvements to the evaluator and agent harness. Every candidate must face the
same grading contract, including candidates produced by Sanka.

## Start with an issue

1. Search the [issues](https://github.com/sankaHQ/bench/issues) and open PRs first.
   Reuse an existing issue when it describes the same problem.
2. Open an issue before submitting a PR. Describe the problem, expected behavior,
   proposed scope and how the change can be checked. For a bug, include a minimal
   reproduction, repository revision, task ID and relevant environment details.
3. For new tasks, providers, dependencies or changes to grading, scoring or
   isolation, wait for a maintainer to agree on the approach before implementing.
   Small documentation fixes still need a linked issue, but need no advance
   scope approval.
4. Fork the repository, create a focused branch and open a PR against `main`.
   Put `Closes #123` in the PR description when it resolves that issue, or
   `Refs #123` when it addresses only part of it. A comment on the issue alone
   does not replace a linked PR description.

Maintainers triage issues before substantive PR review. PRs without a linked
issue may be returned for an issue first. Agreement on scope is not a promise
of acceptance. Draft PRs are welcome for implementation feedback after triage.

## Set up and check your change

Follow the [README setup](README.md#start-with-one-local-evaluation), using
Python 3.12 and the frozen dependency lock. Start with the smallest relevant check:

```bash
make lint typecheck
make test-unit
# If changing the corresponding evaluator or fixture:
make test-evaluator-008
make test-evaluator-flask-002
# Full local validation, with bounded concurrency:
make check TEST_WORKERS=1
```

Run affected positive and negative baseline controls for evaluator changes.
CI also checks container baselines. Do not launch paid model campaigns just to
submit a PR; explain which checks ran, which did not, and why. Never weaken a
failing test to improve a reported score.

## Benchmark changes need evidence

- New tasks: explain the behavior existing tasks miss; provide source provenance,
  redistribution rights, public examples, a target contract and positive/negative
  controls. Grading files for the current open suite belong beside their tasks.
  Discuss future private holdouts privately with maintainers; they are separate
  from the public suite.
- Evaluator fixes: show a minimal incorrect verdict and a regression check.
  State whether existing scores need regrading under a new evaluator revision.
- Provider or harness changes: test tool use, isolation, termination and usage
  accounting. Keep credentials and model access optional for ordinary tests.
- Results: record exact revisions, task coverage, model/configuration, budgets,
  grading outcomes and measurement completeness. Retain failures. Distinguish
  reruns and regrading from original pass@1 results.

Keep raw transcripts, credentials, customer data and per-run workspaces out of
commits and issue attachments. Share only scrubbed reproductions and evidence.
Use the [measurement rules](docs/measurement-runs.md) for recorded campaigns.

## Review and acceptance

Keep one problem per PR. Explain the behavior change and relevant checks, and
update documentation when the public contract changes. Maintainers review
correctness, reproducibility, benchmark neutrality and maintenance cost; passing
CI alone does not guarantee acceptance. Address feedback and keep the PR linked
to its issue. Maintainers merge after required checks and approval pass.

AI-assisted contributions follow the same process. You are responsible for
understanding the diff, validating it and checking generated evidence. Sanka's
internal bot workflow is for its own agents; external contributors use normal
forks and PRs and do not need internal credentials.

Be respectful and keep discussion focused on the work. Preserve third-party
license and attribution notices. The repository is licensed under
[Apache-2.0](LICENSE); only submit material you have permission to contribute.

## Security reports

Do not post exploitable security details, credentials or private grading material
in public issues. Use GitHub's private vulnerability reporting when enabled on
the repository's Security tab. If it is unavailable, request a private reporting
channel without including sensitive details. Maintainers must establish that
channel before public launch.
