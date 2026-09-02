.PHONY: sync format lint typecheck test check baselines docker-baselines report

sync:
	uv sync --frozen --extra fixture --group dev

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy

test:
	uv run python -m pytest

check: lint typecheck test
	uv run sanka-bench validate

# task-id:candidate-name pairs; baselines live at baselines/<task>/<candidate>/
BASELINE_TASKS = 001 002 003 004 005 006 007 008 009 010 011
BASELINES_001 = noop compatibility-bridge claude-code-alone claude-code-with-sanka native-reference sanka-native
BASELINES_002 = noop compatibility-bridge claude-code-alone claude-code-with-sanka native-reference sanka-native
BASELINES_003 = noop compatibility-bridge claude-code-alone claude-code-with-sanka native-reference sanka-native
BASELINES_004 = noop compatibility-bridge native-reference sanka-native
BASELINES_005 = noop compatibility-bridge native-reference sanka-native
BASELINES_006 = noop compatibility-bridge native-reference sanka-native
BASELINES_007 = noop compatibility-bridge native-reference sanka-native
BASELINES_008 = noop compatibility-bridge native-reference sanka-native
BASELINES_009 = noop compatibility-bridge native-reference sanka-native
BASELINES_010 = noop compatibility-bridge native-reference sanka-native
BASELINES_011 = noop compatibility-bridge native-reference sanka-native

define BASELINE_RULES
.PHONY: baselines-$(1) docker-baselines-$(1)

baselines-$(1):
	@for name in $$(BASELINES_$(1)); do \
		uv run sanka-bench evaluate --runner local --task tasks/drf-fastapi/drf-fastapi-$(1) --candidate baselines/drf-fastapi-$(1)/$$$$name --output reports/drf-fastapi-$(1)-$$$$name.json || exit 1; \
	done

docker-baselines-$(1):
	@for name in $$(BASELINES_$(1)); do \
		uv run sanka-bench evaluate --runner docker --task tasks/drf-fastapi/drf-fastapi-$(1) --candidate baselines/drf-fastapi-$(1)/$$$$name --output reports/drf-fastapi-$(1)-$$$$name-docker.json || exit 1; \
	done
endef

$(foreach task,$(BASELINE_TASKS),$(eval $(call BASELINE_RULES,$(task))))

baselines: $(addprefix baselines-,$(BASELINE_TASKS))

docker-baselines: $(addprefix docker-baselines-,$(BASELINE_TASKS))

report:
	uv run sanka-bench report
