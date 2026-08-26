import argparse
import json
from pathlib import Path

from academic_agents.planning import PlanningAgent
from academic_agents.planning_workflow import AcademicPlanningWorkflow
from academic_agents.verification import VerificationAgent
from planning.evaluation import (
    evaluate_planning_workflow,
    load_planning_evaluation_cases,
)
from planning.learning_map import load_learning_map


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate mastery-aware planning and constraints."
    )
    parser.add_argument("learning_map_path")
    parser.add_argument("cases_path")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    learning_map = load_learning_map(arguments.learning_map_path)
    cases = load_planning_evaluation_cases(arguments.cases_path)
    workflow = AcademicPlanningWorkflow(
        planning_agent=PlanningAgent(),
        verification_agent=VerificationAgent(chat_model=None),
    )
    report = evaluate_planning_workflow(workflow, learning_map, cases)
    serialized = report.model_dump(mode="json")
    if arguments.output:
        output_path = arguments.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(serialized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(serialized, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
