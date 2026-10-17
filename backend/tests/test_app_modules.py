"""Unit tests for EvoFlow App v2 modules.

Covers:
- app_engine.render_plan / validate_parameters / extract_undefined_params
- app_extractor.extract_parameters_from_plan / create_app_from_task
- app_generator.generate_app_from_plan

Run: cd backend && python -m pytest tests/test_app_modules.py -v
"""

import pytest

from evoflow.collab.app_engine import (
    extract_undefined_params,
    render_plan,
    validate_parameters,
)
from evoflow.collab.app_extractor import (
    create_app_from_task,
    extract_parameters_from_plan,
)
from evoflow.collab.app_generator import generate_app_from_plan


# ────────────────────────────── render_plan ──────────────────────────────


class TestRenderPlan:
    def test_basic_substitution(self):
        app_def = {
            "goal_template": "Analyze {{topic}} in {{year}}",
            "steps": [
                {"name": "Research {{topic}}", "goal": "Find info about {{topic}}"},
                {"name": "Report", "goal": "Write report for {{year}}"},
            ],
            "validation_template": ["Must cover {{topic}}"],
            "flowchart_mermaid": "graph TD; A-->B",
        }
        params = {"topic": "AI coding", "year": "2024"}
        result = render_plan(app_def, params)

        assert result["goal"] == "Analyze AI coding in 2024"
        assert result["steps"][0]["name"] == "Research AI coding"
        assert result["steps"][0]["goal"] == "Find info about AI coding"
        assert result["steps"][1]["goal"] == "Write report for 2024"
        assert result["validation"] == ["Must cover AI coding"]
        assert result["flowchart_mermaid"] == "graph TD; A-->B"
        assert result["open_questions"] == "\u65e0"

    def test_missing_param_kept_as_placeholder(self):
        app_def = {
            "goal_template": "Analyze {{topic}}",
            "steps": [],
            "validation_template": [],
            "flowchart_mermaid": "",
        }
        result = render_plan(app_def, {})
        assert result["goal"] == "Analyze {{topic}}"

    def test_empty_app_def(self):
        result = render_plan({}, {})
        assert result["goal"] == ""
        assert result["steps"] == []
        assert result["validation"] == []

    def test_param_value_with_special_chars(self):
        app_def = {
            "goal_template": "Process {{path}}",
            "steps": [],
            "validation_template": [],
            "flowchart_mermaid": "",
        }
        params = {"path": "C:/dev/file.py"}
        result = render_plan(app_def, params)
        assert result["goal"] == "Process C:/dev/file.py"

    def test_param_not_in_content(self):
        """Extra params that don't appear in content are simply ignored."""
        app_def = {
            "goal_template": "No placeholders here",
            "steps": [],
            "validation_template": [],
            "flowchart_mermaid": "",
        }
        result = render_plan(app_def, {"unused": "value"})
        assert result["goal"] == "No placeholders here"


# ──────────────────────── extract_undefined_params ────────────────────────


class TestExtractUndefinedParams:
    def test_finds_all_placeholders(self):
        app_def = {
            "goal_template": "Analyze {{topic}}",
            "steps": [{"name": "Research {{topic}}", "goal": "Use {{tool}}"}],
            "validation_template": ["Check {{topic}}"],
            "flowchart_mermaid": "",
        }
        params = extract_undefined_params(app_def)
        assert params == ["tool", "topic"]  # sorted alphabetically

    def test_no_placeholders(self):
        app_def = {
            "goal_template": "No params",
            "steps": [{"name": "Step 1", "goal": "Do thing"}],
            "validation_template": [],
            "flowchart_mermaid": "",
        }
        assert extract_undefined_params(app_def) == []

    def test_dedup(self):
        app_def = {
            "goal_template": "{{topic}} and {{topic}}",
            "steps": [],
            "validation_template": ["{{topic}}"],
            "flowchart_mermaid": "",
        }
        assert extract_undefined_params(app_def) == ["topic"]


# ─────────────────────────── validate_parameters ──────────────────────────


class TestValidateParameters:
    def test_valid(self):
        app_def = {
            "goal_template": "Analyze {{topic}}",
            "steps": [],
            "validation_template": [],
            "flowchart_mermaid": "",
            "parameters": [
                {"name": "topic", "key": "topic", "required": True, "type": "text"}
            ],
        }
        is_valid, missing, undefined = validate_parameters(app_def, {"topic": "AI"})
        assert is_valid
        assert missing == []
        assert undefined == []

    def test_missing_required(self):
        app_def = {
            "goal_template": "Analyze {{topic}}",
            "steps": [],
            "validation_template": [],
            "flowchart_mermaid": "",
            "parameters": [
                {"name": "topic", "key": "topic", "required": True}
            ],
        }
        is_valid, missing, undefined = validate_parameters(app_def, {})
        assert not is_valid
        assert "topic" in missing

    def test_optional_missing_ok(self):
        app_def = {
            "goal_template": "Analyze {{topic}}",
            "steps": [],
            "validation_template": [],
            "flowchart_mermaid": "",
            "parameters": [
                {"name": "topic", "key": "topic", "required": False}
            ],
        }
        is_valid, missing, _ = validate_parameters(app_def, {})
        assert is_valid
        assert missing == []

    def test_undefined_placeholder(self):
        """Undefined {{param}} is reported but no longer blocks validity."""
        app_def = {
            "goal_template": "Analyze {{topic}} and {{unknown}}",
            "steps": [],
            "validation_template": [],
            "flowchart_mermaid": "",
            "parameters": [
                {"name": "topic", "key": "topic", "required": True}
            ],
        }
        is_valid, _, undefined = validate_parameters(app_def, {"topic": "AI"})
        assert not is_valid  # undefined placeholders block execution
        assert "unknown" in undefined

    def test_default_fills_required(self):
        app_def = {
            "goal_template": "Analyze {{topic}}",
            "steps": [],
            "validation_template": [],
            "flowchart_mermaid": "",
            "parameters": [
                {"name": "topic", "required": True, "default": "AI"}
            ],
        }
        is_valid, missing, _ = validate_parameters(app_def, {})
        assert is_valid
        assert missing == []

    def test_blank_string_treated_as_missing(self):
        app_def = {
            "goal_template": "Analyze {{topic}}",
            "steps": [],
            "validation_template": [],
            "flowchart_mermaid": "",
            "parameters": [{"name": "topic", "required": True}],
        }
        is_valid, missing, _ = validate_parameters(app_def, {"topic": "  "})
        assert not is_valid
        assert "topic" in missing

    def test_render_applies_defaults(self):
        from evoflow.collab.app_engine import render_plan

        app_def = {
            "goal_template": "Analyze {{topic}}",
            "steps": [],
            "validation_template": [],
            "flowchart_mermaid": "",
            "parameters": [{"name": "topic", "default": "AI", "required": True}],
        }
        assert render_plan(app_def, {})["goal"] == "Analyze AI"

    def test_fallback_name_to_key(self):
        """Parameters without 'key' field fall back to 'name'."""
        app_def = {
            "goal_template": "Analyze {{topic}}",
            "steps": [],
            "validation_template": [],
            "flowchart_mermaid": "",
            "parameters": [
                {"name": "topic", "required": True}  # no "key" field
            ],
        }
        is_valid, missing, _ = validate_parameters(app_def, {"topic": "AI"})
        assert is_valid
        assert missing == []


# ──────────────────────── extract_parameters_from_plan ────────────────────


class TestExtractParametersFromPlan:
    def test_extracts_product_name(self):
        goal = 'Analyze "ChatGPT" competitive landscape'
        steps = [
            {"name": "Research ChatGPT", "goal": "Find data about ChatGPT"},
            {"name": "Report", "goal": "Write analysis for ChatGPT"},
        ]
        rendered, params = extract_parameters_from_plan(goal, steps)

        assert len(params) >= 1
        assert rendered["param_count"] == len(params)
        # The goal should have placeholder(s) now
        assert "{{" in rendered["goal_template"]

    def test_extracts_numbers(self):
        goal = "Analyze top 10 products in 2024"
        steps = [
            {"name": "Select 10 products", "goal": "Pick top 10"},
        ]
        rendered, params = extract_parameters_from_plan(goal, steps)
        assert len(params) >= 1
        assert "{{" in rendered["goal_template"]

    def test_max_params_limit(self):
        goal = '"ChatGPT" "Claude" "Gemini" "Copilot" "Cursor" "Devin" 2024'
        steps = [{"name": f"Analyze product", "goal": "Do research"}]
        _, params = extract_parameters_from_plan(goal, steps, max_params=3)
        assert len(params) <= 3

    def test_no_extractable_values(self):
        goal = "Do some research"
        steps = [{"name": "Step", "goal": "Do the thing"}]
        rendered, params = extract_parameters_from_plan(goal, steps)
        assert len(params) == 0
        assert rendered["goal_template"] == goal  # unchanged

    def test_empty_input(self):
        rendered, params = extract_parameters_from_plan("", [])
        assert len(params) == 0
        assert rendered["goal_template"] == ""

    def test_replacement_in_steps(self):
        goal = 'Analyze "ChatGPT"'
        steps = [
            {"name": "Research ChatGPT", "goal": "Find ChatGPT data",
             "inputs": "", "outputs": "", "acceptance": "", "instruction": ""},
        ]
        rendered, _ = extract_parameters_from_plan(goal, steps)
        # The product name should be replaced in step fields too
        assert "ChatGPT" not in rendered["steps"][0]["name"]
        assert "{{" in rendered["steps"][0]["name"]


# ─────────────────────────── create_app_from_task ─────────────────────────


class TestCreateAppFromTask:
    def test_basic(self):
        app = create_app_from_task(
            task_id="Task_test123",
            task_name="Competitive Analysis",
            task_description="Analyze competitors",
            plan_goal='Analyze "ChatGPT" landscape',
            plan_steps=[{"name": "Research", "goal": "Find data"}],
            execution_mode="workflow",
        )
        assert app["source"] == "from_task"
        assert app["source_task_id"] == "Task_test123"
        assert app["status"] == "draft"
        assert app["execution_mode"] == "workflow"
        assert app["id"].startswith("App_")
        assert app["usage_count"] == 0
        assert "from-task" in app["tags"]

    def test_no_extract(self):
        app = create_app_from_task(
            task_id="Task_test",
            task_name="Test",
            task_description="",
            plan_goal="Simple goal",
            plan_steps=[{"name": "S1", "goal": "G1"}],
            auto_extract=False,
        )
        assert len(app["parameters"]) == 0
        assert app["goal_template"] == "Simple goal"

    def test_name_sanitization(self):
        app = create_app_from_task(
            task_id="T1",
            task_name="Task: Do Something",
            task_description="",
            plan_goal="goal",
            plan_steps=[],
        )
        assert app["name"] == "Do Something"


# ─────────────────────────── generate_app_from_plan ────────────────────────


class TestGenerateAppFromPlan:
    def test_basic_generation(self):
        goal = 'Analyze "ChatGPT" competitive landscape in 2024'
        steps = [
            {"name": "Research ChatGPT", "goal": "Find ChatGPT data",
             "assigned_agent": "researcher", "depends_on": []},
            {"name": "Write report", "goal": "Compile findings",
             "assigned_agent": "writer", "depends_on": ["1"]},
        ]
        app = generate_app_from_plan(
            goal=goal,
            steps=steps,
            name="竞品分析报告",
        )
        assert app["source"] == "generated"
        assert app["status"] == "draft"
        assert app["name"] == "竞品分析报告"
        assert app["id"].startswith("App_")
        assert app["usage_count"] == 0
        assert app["execution_mode"] == "workflow"
        assert "generated" in app["tags"]
        # Should have extracted some parameters
        assert len(app["parameters"]) >= 1
        # goal_template should contain placeholders
        assert "{{" in app["goal_template"]

    def test_no_extraction(self):
        goal = "Simple goal"
        steps = [{"name": "Step", "goal": "Do thing"}]
        app = generate_app_from_plan(
            goal=goal,
            steps=steps,
            name="Simple",
            auto_extract=False,
        )
        assert len(app["parameters"]) == 0
        assert app["goal_template"] == goal
        assert "auto-parameterized" not in app["tags"]

    def test_custom_category_and_icon(self):
        app = generate_app_from_plan(
            goal="goal",
            steps=[],
            name="Test",
            icon="🔍",
            category="research",
        )
        assert app["icon"] == "🔍"
        assert app["category"] == "research"

    def test_lead_supervised_mode(self):
        app = generate_app_from_plan(
            goal="goal",
            steps=[],
            name="Test",
            execution_mode="lead_supervised",
        )
        assert app["execution_mode"] == "lead_supervised"

    def test_auto_description(self):
        app = generate_app_from_plan(
            goal='Analyze "ChatGPT"',
            steps=[{"name": "S1", "goal": "G1"}],
            name="Test App",
        )
        assert "Test App" in app["description"]
        assert "parameter" in app["description"].lower()

    def test_max_params_limit(self):
        goal = '"ChatGPT" "Claude" "Gemini" "Copilot" "Cursor" "Devin" 2024'
        steps = [{"name": "Analyze", "goal": "Do research"}]
        app = generate_app_from_plan(goal, steps, "Test", max_params=2)
        assert len(app["parameters"]) <= 2

    def test_custom_tags_merged(self):
        app = generate_app_from_plan(
            goal="goal",
            steps=[],
            name="Test",
            tags=["custom-tag"],
        )
        assert "custom-tag" in app["tags"]
        assert "generated" in app["tags"]

    def test_empty_plan(self):
        app = generate_app_from_plan(
            goal="",
            steps=[],
            name="Empty",
        )
        assert app["goal_template"] == ""
        assert len(app["parameters"]) == 0
