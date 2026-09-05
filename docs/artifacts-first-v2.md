# Artifacts-first v2 treatment

`execution.sanka_workflow: artifacts-first-v2` supplies reviewed partial generated
Flask files to both Sanka configurations even when native readiness is zero. Readiness
and manual gaps stay unchanged and visible; placeholders earn no grading credit.
The model-only arm receives the same task and budgets without Sanka artifacts.
FastAPI retains its existing readiness threshold and extension admission checks.

The Skills arm installs the pinned project Skill, verifies its content digest,
and includes the exact text in the initial prompt. `sanka-skill.json` records
`delivery: inline-prompt-v1`; the saved prompt contains the delivered content.
This guarantees content delivery, not that the model follows the instructions.
The CLI-only arm receives no Skill content. Skill prompt tokens count in usage.

The original availability-v1 and artifacts-first-v1 remain selectable. A new
workflow, extension wheel or Skill digest requires a new immutable run; do not
reuse prior candidates or retry quality failures into the new comparison.
Experimental toolchain pins, including locally built wheel hashes, participate
in each cell's input digest even when the unpublished version number is unchanged.

Keep FastAPI and Flask results separate. Report whole-task pass@1, input/cache/
output tokens, estimated provider cost with its exact price card, generation and
evaluation time, tool calls, generated-file retention, and successful-task
throughput. Include failures and setup costs. Supplied partial code is not proof
of a speed or accuracy benefit; those claims require the scored comparison.
