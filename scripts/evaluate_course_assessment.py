import argparse
import json
from pathlib import Path

from academic_agents.assessment import AssessmentAgent
from academic_agents.assessment_workflow import AcademicAssessmentWorkflow
from academic_agents.verification import VerificationAgent
from assessment.evaluation import (
    evaluate_assessment_workflow,
    load_assessment_evaluation_suite,
)
from assessment.question_bank import load_question_bank


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate adaptive question selection, grading and BKT."
    )
    parser.add_argument("question_bank_path")
    parser.add_argument("cases_path")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    bank = load_question_bank(arguments.question_bank_path)
    suite = load_assessment_evaluation_suite(arguments.cases_path)
    workflow = AcademicAssessmentWorkflow(
        assessment_agent=AssessmentAgent(),
        verification_agent=VerificationAgent(chat_model=None),
    )
    report = evaluate_assessment_workflow(workflow, bank, suite)
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
