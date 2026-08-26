from schemas.assessment import BKTParameters, MasteryLevel


def update_bkt(
    prior_mastery: float,
    *,
    is_correct: bool,
    parameters: BKTParameters,
) -> float:
    """Apply one standard BKT observation followed by the learning transition."""

    prior = min(1.0, max(0.0, float(prior_mastery)))
    if is_correct:
        numerator = prior * (1.0 - parameters.p_slip)
        denominator = numerator + (1.0 - prior) * parameters.p_guess
    else:
        numerator = prior * parameters.p_slip
        denominator = numerator + (1.0 - prior) * (1.0 - parameters.p_guess)

    posterior = numerator / denominator if denominator else prior
    updated = posterior + (1.0 - posterior) * parameters.p_learn
    return round(min(1.0, max(0.0, updated)), 6)


def classify_mastery(
    probability: float,
    *,
    mastery_threshold: float = 0.8,
) -> MasteryLevel:
    if probability >= mastery_threshold:
        return "mastered"
    if probability < 0.5:
        return "weak"
    return "developing"
