import argparse
import json
from pathlib import Path

from automation.evaluation import (
    evaluate_automation_policy,
    load_automation_evaluation_cases,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the deterministic closed-loop replan policy."
    )
    parser.add_argument("cases_path")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    cases = load_automation_evaluation_cases(arguments.cases_path)
    report = evaluate_automation_policy(cases)
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
