import datetime
from uuid import uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from academic_agents.assessment import AssessmentAgentError
from assessment.bkt import classify_mastery
from database.models import (
    AssessmentAttemptModel,
    LearnerConceptMasteryModel,
    UserModel,
)
from schemas.assessment import (
    AssessmentQuestion,
    AssessmentStartRequest,
    AssessmentStartResponse,
    AssessmentSubmitResponse,
    BKTParameters,
    ConceptMasteryResponse,
    CourseMasteryResponse,
    PublicAssessmentQuestion,
)
from services.automation_service import ClosedLoopAutomationService


class AssessmentNotFoundError(LookupError):
    pass


class AssessmentConflictError(RuntimeError):
    pass


class AssessmentVerificationError(RuntimeError):
    pass


def _public_question(question: AssessmentQuestion) -> PublicAssessmentQuestion:
    return PublicAssessmentQuestion(
        question_id=question.question_id,
        concept_id=question.concept_id,
        concept_name=question.concept_name,
        question_type=question.question_type,
        difficulty=question.difficulty,
        prompt=question.prompt,
        options=question.options,
        citation=question.citation,
    )


class AcademicAssessmentService:
    def __init__(self, db: Session, runtime) -> None:
        if (
            runtime.assessment_workflow is None
            or runtime.question_bank_registry is None
        ):
            raise AssessmentVerificationError(
                "Assessment runtime chưa được cấu hình."
            )
        self.db = db
        self.runtime = runtime
        self.workflow = runtime.assessment_workflow
        self.question_banks = runtime.question_bank_registry

    def start(
        self,
        request: AssessmentStartRequest,
        *,
        user_id: int,
    ) -> AssessmentStartResponse:
        bank = self.question_banks.get(
            request.course_id,
            request.course_version,
        )
        mastery_rows = (
            self.db.query(LearnerConceptMasteryModel)
            .filter(
                LearnerConceptMasteryModel.user_id == user_id,
                LearnerConceptMasteryModel.course_id == request.course_id,
                LearnerConceptMasteryModel.course_version
                == request.course_version,
            )
            .all()
        )
        mastery_by_concept = {
            row.concept_id: row.mastery_probability
            for row in mastery_rows
        }
        attempt_counts = dict(
            self.db.query(
                AssessmentAttemptModel.question_id,
                func.count(AssessmentAttemptModel.id),
            )
            .filter(
                AssessmentAttemptModel.user_id == user_id,
                AssessmentAttemptModel.course_id == request.course_id,
                AssessmentAttemptModel.course_version
                == request.course_version,
            )
            .group_by(AssessmentAttemptModel.question_id)
            .all()
        )
        result = self.workflow.select_question(
            bank,
            mastery_by_concept=mastery_by_concept,
            attempt_count_by_question=attempt_counts,
            target_concept_id=request.concept_id,
        )
        if result.verification_status != "PASS" or result.selection is None:
            raise AssessmentVerificationError(
                "Verification Agent từ chối câu hỏi đánh giá."
            )

        selection = result.selection
        question = selection.question
        attempt = AssessmentAttemptModel(
            attempt_id=str(uuid4()),
            user_id=user_id,
            course_id=bank.course_id,
            course_version=bank.course_version,
            question_id=question.question_id,
            concept_id=question.concept_id,
            concept_name=question.concept_name,
            question_snapshot={
                "question": question.model_dump(mode="json"),
                "bkt": bank.bkt.model_dump(mode="json"),
            },
            status="PENDING",
            mastery_before=selection.mastery_before,
        )
        self.db.add(attempt)
        try:
            self.db.commit()
            self.db.refresh(attempt)
        except Exception:
            self.db.rollback()
            raise

        return AssessmentStartResponse(
            attempt_id=attempt.attempt_id,
            course_id=attempt.course_id,
            course_version=attempt.course_version,
            question=_public_question(question),
            mastery_before=selection.mastery_before,
            selection_reason=selection.reason,
            agent_trace=result.agent_trace,
        )

    def submit(
        self,
        attempt_id: str,
        *,
        selected_option_id: str,
        user_id: int,
        today: datetime.date | None = None,
    ) -> AssessmentSubmitResponse:
        attempt = (
            self.db.query(AssessmentAttemptModel)
            .filter(
                AssessmentAttemptModel.attempt_id == attempt_id,
                AssessmentAttemptModel.user_id == user_id,
            )
            .with_for_update()
            .first()
        )
        if attempt is None:
            raise AssessmentNotFoundError("Không tìm thấy lượt đánh giá.")
        if attempt.status != "PENDING":
            raise AssessmentConflictError("Lượt đánh giá đã được nộp.")

        question = AssessmentQuestion.model_validate(
            attempt.question_snapshot["question"]
        )
        parameters = BKTParameters.model_validate(
            attempt.question_snapshot["bkt"]
        )
        # Serialize mastery updates per learner so two concurrent submissions
        # cannot overwrite each other on PostgreSQL.
        (
            self.db.query(UserModel)
            .filter(UserModel.id == user_id)
            .with_for_update()
            .first()
        )
        mastery = (
            self.db.query(LearnerConceptMasteryModel)
            .filter(
                LearnerConceptMasteryModel.user_id == user_id,
                LearnerConceptMasteryModel.course_id == attempt.course_id,
                LearnerConceptMasteryModel.course_version
                == attempt.course_version,
                LearnerConceptMasteryModel.concept_id == attempt.concept_id,
            )
            .with_for_update()
            .first()
        )
        prior = (
            mastery.mastery_probability
            if mastery is not None
            else parameters.p_initial
        )
        result = self.workflow.grade_answer(
            question,
            selected_option_id=selected_option_id,
            mastery_before=prior,
            bkt_parameters=parameters,
        )
        if (
            result.verification_status != "PASS"
            or result.grade is None
            or result.mastery_after is None
        ):
            raise AssessmentVerificationError(
                "Verification Agent từ chối kết quả chấm."
            )
        updated = result.mastery_after
        if mastery is None:
            mastery = LearnerConceptMasteryModel(
                user_id=user_id,
                course_id=attempt.course_id,
                course_version=attempt.course_version,
                concept_id=attempt.concept_id,
                concept_name=attempt.concept_name,
                mastery_probability=updated,
                attempt_count=1,
                correct_count=int(result.grade.is_correct),
                last_question_id=attempt.question_id,
            )
            self.db.add(mastery)
        else:
            mastery.mastery_probability = updated
            mastery.attempt_count += 1
            mastery.correct_count += int(result.grade.is_correct)
            mastery.last_question_id = attempt.question_id

        attempt.status = "COMPLETED"
        attempt.selected_option_id = result.grade.submitted_option_id
        attempt.is_correct = result.grade.is_correct
        attempt.mastery_before = prior
        attempt.mastery_after = updated
        attempt.feedback = result.grade.feedback
        attempt.completed_at = datetime.datetime.utcnow()
        automation = ClosedLoopAutomationService(
            self.db,
            self.runtime,
        ).handle_mastery_updated(
            attempt=attempt,
            user_id=user_id,
            is_correct=result.grade.is_correct,
            mastery_before=prior,
            mastery_after=updated,
            today=today,
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        level = classify_mastery(
            updated,
            mastery_threshold=parameters.mastery_threshold,
        )
        next_action = {
            "weak": "review_concept",
            "developing": "continue_practice",
            "mastered": "concept_mastered",
        }[level]
        return AssessmentSubmitResponse(
            attempt_id=attempt.attempt_id,
            course_id=attempt.course_id,
            course_version=attempt.course_version,
            concept_id=attempt.concept_id,
            concept_name=attempt.concept_name,
            is_correct=result.grade.is_correct,
            correct_option_id=result.grade.correct_option_id,
            feedback=result.grade.feedback,
            mastery_before=prior,
            mastery_after=updated,
            mastery_level=level,
            next_action=next_action,
            verification_status="PASS",
            agent_trace=result.agent_trace,
            automation=automation,
        )

    def get_mastery(
        self,
        *,
        user_id: int,
        course_id: str,
        course_version: str,
    ) -> CourseMasteryResponse:
        bank = self.question_banks.get(course_id, course_version)
        rows = (
            self.db.query(LearnerConceptMasteryModel)
            .filter(
                LearnerConceptMasteryModel.user_id == user_id,
                LearnerConceptMasteryModel.course_id == course_id,
                LearnerConceptMasteryModel.course_version == course_version,
            )
            .all()
        )
        row_by_concept = {row.concept_id: row for row in rows}
        concept_names = {
            question.concept_id: question.concept_name
            for question in bank.questions
        }
        concepts = []
        for concept_id, concept_name in sorted(concept_names.items()):
            row = row_by_concept.get(concept_id)
            probability = (
                row.mastery_probability if row else bank.bkt.p_initial
            )
            concepts.append(
                ConceptMasteryResponse(
                    concept_id=concept_id,
                    concept_name=concept_name,
                    mastery_probability=probability,
                    mastery_level=classify_mastery(
                        probability,
                        mastery_threshold=bank.bkt.mastery_threshold,
                    ),
                    attempt_count=row.attempt_count if row else 0,
                    correct_count=row.correct_count if row else 0,
                    updated_at=row.updated_at if row else None,
                )
            )
        return CourseMasteryResponse(
            course_id=course_id,
            course_version=course_version,
            concepts=concepts,
        )


__all__ = [
    "AcademicAssessmentService",
    "AssessmentAgentError",
    "AssessmentConflictError",
    "AssessmentNotFoundError",
    "AssessmentVerificationError",
]
