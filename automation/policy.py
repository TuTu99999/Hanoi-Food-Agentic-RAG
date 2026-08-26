from schemas.automation import ReplanDecision


WEAK_MASTERY_BOUNDARY = 0.5


def decide_replan(
    *,
    is_correct: bool,
    mastery_after: float,
    has_active_plan: bool,
    has_pending_replan: bool,
) -> ReplanDecision:
    """Small, explainable guard policy used by the Orchestrator.

    Planning is triggered only when a wrong answer leaves a concept weak and
    the learner already has an active plan. A pending revision is reused to
    prevent proposal spam.
    """

    if not has_active_plan:
        return ReplanDecision(
            replan_required=False,
            create_proposal=False,
            reason="NO_ACTIVE_PLAN",
        )
    if is_correct:
        return ReplanDecision(
            replan_required=False,
            create_proposal=False,
            reason="ANSWER_CORRECT",
        )
    if mastery_after >= WEAK_MASTERY_BOUNDARY:
        return ReplanDecision(
            replan_required=False,
            create_proposal=False,
            reason="MASTERY_NOT_WEAK",
        )
    if has_pending_replan:
        return ReplanDecision(
            replan_required=True,
            create_proposal=False,
            reason="PENDING_REPLAN_EXISTS",
        )
    return ReplanDecision(
        replan_required=True,
        create_proposal=True,
        reason="WEAKNESS_DETECTED",
    )


__all__ = ["WEAK_MASTERY_BOUNDARY", "decide_replan"]
