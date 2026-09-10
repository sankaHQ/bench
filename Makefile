.PHONY: sync sanka-toolchain format lint typecheck test test-unit test-suite check baselines docker-baselines report

CONTAINER_ENGINE ?= docker
TEST_WORKERS ?= 2
ifeq ($(strip $(TEST_WORKERS)),)
$(error TEST_WORKERS must be 1, 2, 3, or 4)
endif
ifneq ($(filter $(TEST_WORKERS),1 2 3 4),$(TEST_WORKERS))
$(error TEST_WORKERS must be 1, 2, 3, or 4)
endif

sync:
	uv sync --frozen --python 3.12 --extra fixture --group dev

# Create one isolated CLI environment per new campaign, outside the evaluator venv.
sanka-toolchain:
	test -n "$(RUN_DIR)"
	test ! -e "$(RUN_DIR)/toolchain"
	uv venv --python 3.12 "$(RUN_DIR)/toolchain"
	uv pip install --python "$(RUN_DIR)/toolchain/bin/python" -r requirements-sanka.txt
	"$(RUN_DIR)/toolchain/bin/sanka" --version

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy

test:
	$(MAKE) -j$(TEST_WORKERS) test-suite

test-unit:
	uv run python -m pytest --ignore-glob='tests/test_evaluator*.py' --durations=10 --junitxml=reports/tests-unit.xml

check: lint typecheck test
	uv run sanka-bench validate

# task-id:candidate-name pairs; baselines live at baselines/<task>/<candidate>/
BASELINE_TASKS = 001 002 003 004 005 006 007 008 009 010 011
BASELINES_001 = noop compatibility-bridge native-reference sanka-native
BASELINES_002 = noop compatibility-bridge native-reference sanka-native
BASELINES_003 = noop compatibility-bridge native-reference sanka-native
BASELINES_004 = noop compatibility-bridge native-reference sanka-native
BASELINES_005 = noop compatibility-bridge native-reference sanka-native
BASELINES_006 = noop compatibility-bridge native-reference sanka-native
BASELINES_007 = noop compatibility-bridge native-reference sanka-native
BASELINES_008 = noop compatibility-bridge native-reference sanka-native
BASELINES_009 = noop compatibility-bridge native-reference sanka-native
BASELINES_010 = noop compatibility-bridge native-reference sanka-native
BASELINES_011 = noop compatibility-bridge native-reference sanka-native

define BASELINE_RULES
.PHONY: baselines-$(1) docker-baselines-$(1) test-evaluator-$(1)

test-evaluator-$(1):
	uv run python -m pytest tests/test_evaluator$(if $(filter 001,$(1)),,_$(1)).py --durations=5 --junitxml=reports/tests-evaluator-$(1).xml

baselines-$(1):
	@for name in $$(BASELINES_$(1)); do \
		uv run sanka-bench evaluate --runner local --task tasks/drf-fastapi/drf-fastapi-$(1) --candidate baselines/drf-fastapi-$(1)/$$$$name --output reports/drf-fastapi-$(1)-$$$$name.json || exit 1; \
	done

docker-baselines-$(1):
	@for name in $$(BASELINES_$(1)); do \
		uv run sanka-bench evaluate --runner docker --container-engine $$(CONTAINER_ENGINE) --task tasks/drf-fastapi/drf-fastapi-$(1) --candidate baselines/drf-fastapi-$(1)/$$$$name --output reports/drf-fastapi-$(1)-$$$$name-docker.json || exit 1; \
	done
endef

$(foreach task,$(BASELINE_TASKS),$(eval $(call BASELINE_RULES,$(task))))

test-suite: test-unit $(addprefix test-evaluator-,$(BASELINE_TASKS))

baselines: $(addprefix baselines-,$(BASELINE_TASKS))

docker-baselines: $(addprefix docker-baselines-,$(BASELINE_TASKS))

report:
	uv run sanka-bench report

# Flask tasks use the same bounded per-task CI jobs as FastAPI.
FLASK_TASKS = 001 002 003 004 005 006

define FLASK_RULES
.PHONY: test-evaluator-flask-$(1) baselines-flask-$(1) docker-baselines-flask-$(1)
test-evaluator-flask-$(1):
	uv run python -m pytest tests/test_evaluator_flask.py -k drf-flask-$(1) --durations=5 --junitxml=reports/tests-evaluator-flask-$(1).xml
baselines-flask-$(1):
	@for name in noop compatibility-bridge native-reference $(if $(filter 004,$(1)),missing-audit); do \
		uv run sanka-bench evaluate --runner local --task tasks/drf-flask/drf-flask-$(1) --candidate baselines/drf-flask-$(1)/$$$$name --output reports/drf-flask-$(1)-$$$$name.json || exit 1; \
	done
docker-baselines-flask-$(1):
	@for name in noop compatibility-bridge native-reference $(if $(filter 004,$(1)),missing-audit); do \
		uv run sanka-bench evaluate --runner docker --container-engine $$(CONTAINER_ENGINE) --task tasks/drf-flask/drf-flask-$(1) --candidate baselines/drf-flask-$(1)/$$$$name --output reports/drf-flask-$(1)-$$$$name-docker.json || exit 1; \
	done
endef
$(foreach task,$(FLASK_TASKS),$(eval $(call FLASK_RULES,$(task))))
test-suite: $(addprefix test-evaluator-flask-,$(FLASK_TASKS))
baselines: $(addprefix baselines-flask-,$(FLASK_TASKS))
docker-baselines: $(addprefix docker-baselines-flask-,$(FLASK_TASKS))
