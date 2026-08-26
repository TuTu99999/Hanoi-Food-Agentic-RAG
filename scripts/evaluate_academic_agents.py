import argparse
import asyncio
import json
from pathlib import Path

from academic_agents.evaluation import (
    evaluate_academic_agent_workflow,
    load_agent_evaluation_cases,
)
from academic_agents.runtime import AcademicAgentRuntime
from core.config import settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate academic agent routing, tool selection and constraints."
        )
    )
    parser.add_argument("cases_path")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    runtime = None
    try:
        cases = load_agent_evaluation_cases(arguments.cases_path)
        runtime = AcademicAgentRuntime.from_settings(settings)
        report = evaluate_academic_agent_workflow(runtime.workflow, cases)
    finally:
        if runtime is not None:
            asyncio.run(runtime.aclose())

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
