from schemas.assessment import (
    AssessmentGrade,
    AssessmentQuestion,
    AssessmentQuestionBank,
    AssessmentSelection,
)


class AssessmentAgentError(ValueError):
    pass


class AssessmentAgent:
    """Select adaptive questions and grade curated multiple-choice answers."""

    @staticmethod
    def _target_difficulty(mastery: float) -> int:
        if mastery < 0.35:
            return 1
        if mastery < 0.55:
            return 2
        if mastery < 0.75:
            return 3
        if mastery < 0.9:
            return 4
        return 5

    def select_question(
        self,
        bank: AssessmentQuestionBank,
        *,
        mastery_by_concept: dict[str, float],
        attempt_count_by_question: dict[str, int],
        target_concept_id: str | None = None,
    ) -> AssessmentSelection:
        candidates = bank.questions
        if target_concept_id is not None:
            candidates = [
                question
                for question in candidates
                if question.concept_id == target_concept_id
            ]
            if not candidates:
                raise AssessmentAgentError(
                    "Concept chưa có câu hỏi trong ngân hàng của môn."
                )

        concept_ids = sorted({question.concept_id for question in candidates})
        selected_concept = min(
            concept_ids,
            key=lambda concept_id: (
                mastery_by_concept.get(concept_id, bank.bkt.p_initial),
                concept_id,
            ),
        )
        mastery = mastery_by_concept.get(
            selected_concept,
            bank.bkt.p_initial,
        )
        target_difficulty = self._target_difficulty(mastery)
        concept_questions = [
            question
            for question in candidates
            if question.concept_id == selected_concept
        ]
        selected = min(
            concept_questions,
            key=lambda question: (
                attempt_count_by_question.get(question.question_id, 0),
                abs(question.difficulty - target_difficulty),
                question.question_id,
            ),
        )
        return AssessmentSelection(
            question=selected,
            mastery_before=mastery,
            reason=(
                f"Chọn concept có mastery thấp và câu độ khó {selected.difficulty} "
                f"gần mức phù hợp {target_difficulty}."
            ),
        )

    def grade_answer(
        self,
        question: AssessmentQuestion,
        *,
        selected_option_id: str,
    ) -> AssessmentGrade:
        normalized = selected_option_id.strip().upper()
        option_ids = {option.option_id for option in question.options}
        if normalized not in option_ids:
            raise AssessmentAgentError("Lựa chọn không tồn tại trong câu hỏi.")
        is_correct = normalized == question.correct_option_id
        prefix = "Chính xác." if is_correct else "Chưa chính xác."
        return AssessmentGrade(
            question_id=question.question_id,
            submitted_option_id=normalized,
            correct_option_id=question.correct_option_id,
            is_correct=is_correct,
            feedback=f"{prefix} {question.explanation}",
        )
