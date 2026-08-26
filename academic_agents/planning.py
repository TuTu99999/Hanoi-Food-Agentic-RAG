import math
from datetime import date, timedelta

from schemas.planning import LearningMap, LearningPlanDraft, LearningPlanItem


class PlanningAgentError(ValueError):
    pass


class PlanningAgent:
    """Build a deterministic, mastery-aware plan that respects prerequisites."""

    @staticmethod
    def _prerequisite_closure(
        concept_ids: set[str],
        prerequisites: dict[str, set[str]],
    ) -> set[str]:
        selected = set(concept_ids)
        pending = list(concept_ids)
        while pending:
            concept_id = pending.pop()
            for prerequisite_id in prerequisites[concept_id]:
                if prerequisite_id not in selected:
                    selected.add(prerequisite_id)
                    pending.append(prerequisite_id)
        return selected

    @staticmethod
    def _topological_priority(
        selected: set[str],
        *,
        prerequisites: dict[str, set[str]],
        mastery_by_concept: dict[str, float],
        initial_mastery: float,
        order_by_concept: dict[str, int],
    ) -> list[str]:
        remaining = set(selected)
        ordered = []
        while remaining:
            ready = [
                concept_id
                for concept_id in remaining
                if not (prerequisites[concept_id] & remaining)
            ]
            if not ready:
                raise PlanningAgentError("Learning Map có vòng prerequisite.")
            chosen = min(
                ready,
                key=lambda concept_id: (
                    mastery_by_concept.get(concept_id, initial_mastery),
                    order_by_concept[concept_id],
                    concept_id,
                ),
            )
            ordered.append(chosen)
            remaining.remove(chosen)
        return ordered

    @staticmethod
    def _required_minutes(estimated: int, mastery: float) -> int:
        remaining_ratio = max(0.25, 1.0 - min(1.0, max(0.0, mastery)))
        return max(5, int(math.ceil(estimated * remaining_ratio / 5.0) * 5))

    def create_plan(
        self,
        learning_map: LearningMap,
        *,
        mastery_by_concept: dict[str, float],
        mastery_threshold: float,
        start_date: date,
        target_date: date,
        study_days: int,
        minutes_per_day: int,
        focus_concept_ids: list[str] | None = None,
        initial_mastery: float = 0.2,
    ) -> LearningPlanDraft:
        if start_date >= target_date:
            raise PlanningAgentError("Ngày bắt đầu phải trước ngày mục tiêu.")
        if study_days <= 0 or minutes_per_day <= 0:
            raise PlanningAgentError("Quỹ thời gian học không hợp lệ.")

        concepts = {
            concept.concept_id: concept
            for concept in learning_map.concepts
        }
        prerequisites = {
            concept.concept_id: set(concept.prerequisite_ids)
            for concept in learning_map.concepts
        }
        focus = set(focus_concept_ids or [])
        missing_focus = focus - set(concepts)
        if missing_focus:
            raise PlanningAgentError(
                "Concept mục tiêu không tồn tại: "
                + ", ".join(sorted(missing_focus))
            )

        selected = focus or {
            concept_id
            for concept_id in concepts
            if mastery_by_concept.get(concept_id, initial_mastery)
            < mastery_threshold
        }
        if not selected:
            selected = {
                min(
                    concepts,
                    key=lambda concept_id: (
                        mastery_by_concept.get(concept_id, initial_mastery),
                        concepts[concept_id].order,
                    ),
                )
            }
        selected = self._prerequisite_closure(selected, prerequisites)
        ordered_ids = self._topological_priority(
            selected,
            prerequisites=prerequisites,
            mastery_by_concept=mastery_by_concept,
            initial_mastery=initial_mastery,
            order_by_concept={
                concept.concept_id: concept.order
                for concept in learning_map.concepts
            },
        )

        minutes_by_concept = {
            concept_id: self._required_minutes(
                concepts[concept_id].estimated_minutes,
                mastery_by_concept.get(concept_id, initial_mastery),
            )
            for concept_id in ordered_ids
        }
        required_minutes = sum(minutes_by_concept.values())
        capacity_minutes = study_days * minutes_per_day
        items: list[LearningPlanItem] = []
        unscheduled: list[str] = []
        day_index = 0
        remaining_day_capacity = minutes_per_day

        for concept_id in ordered_ids:
            concept = concepts[concept_id]
            mastery = mastery_by_concept.get(concept_id, initial_mastery)
            activity = (
                "learn"
                if mastery < 0.5
                else "practice"
                if mastery < mastery_threshold
                else "review"
            )
            remaining_minutes = minutes_by_concept[concept_id]
            while remaining_minutes > 0 and day_index < study_days:
                duration = min(remaining_minutes, remaining_day_capacity)
                items.append(
                    LearningPlanItem(
                        sequence=len(items) + 1,
                        study_date=start_date + timedelta(days=day_index),
                        concept_id=concept_id,
                        concept_name=concept.concept_name,
                        duration_minutes=duration,
                        activity=activity,
                        reason=(
                            f"Mastery hiện tại {mastery:.2f}; ưu tiên theo prerequisite "
                            "và mức độ còn thiếu."
                        ),
                        prerequisite_ids=concept.prerequisite_ids,
                        citation=concept.citation,
                    )
                )
                remaining_minutes -= duration
                remaining_day_capacity -= duration
                if remaining_day_capacity == 0:
                    day_index += 1
                    remaining_day_capacity = minutes_per_day
            if remaining_minutes > 0:
                unscheduled.append(concept_id)

        return LearningPlanDraft(
            start_date=start_date,
            target_date=target_date,
            study_days=study_days,
            minutes_per_day=minutes_per_day,
            capacity_minutes=capacity_minutes,
            required_minutes=required_minutes,
            scheduled_minutes=sum(item.duration_minutes for item in items),
            priority_concept_ids=ordered_ids,
            unscheduled_concept_ids=unscheduled,
            items=items,
        )
