# Go evaluator dependency cache

Locks copied verbatim from sankaHQ/extensions at
`10fb419e67b9f524406d999d4e3883494c3be8ce`,
`packages/sanka-extension-python-to-golang/src/sanka_extension_python_to_golang/locks/fiber-sqlite/`.
Apache-2.0; these are destination dependencies, not Sanka CLI/extension release pins.
They are supplied to both model arms and prepare the evaluator cache. No download or build has run.
Read versions from go.mod; a campaign selecting different versions needs new locks,
new image digests, and fresh Go control qualification. Never update the old CLI pins.
