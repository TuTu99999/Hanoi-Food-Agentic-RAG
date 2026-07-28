import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline


ALLOWED_INTENTS = {
    "chitchat",
    "entity_lookup",
    "food_search",
    "recommendation",
    "comparison",
    "planning",
    "out_of_scope",
}
DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "query_router"
    / "intents.jsonl"
)
MIN_EXAMPLES_PER_INTENT = 10


@dataclass(frozen=True)
class RoutePrediction:
    intent: str
    confidence: float
    source: str


class QueryRouter:
    def __init__(
        self,
        dataset_path: str | Path | None = None,
        confidence_threshold: float = 0.35,
    ):
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be between 0 and 1")

        self.confidence_threshold = confidence_threshold
        self.model = None

        try:
            texts, labels = self._load_dataset(
                Path(dataset_path) if dataset_path else DEFAULT_DATASET_PATH
            )
            self.model = self._build_model()
            self.model.fit(texts, labels)
        except Exception:
            # A missing or invalid local dataset must not stop the chat service.
            self.model = None

    def predict(self, query: str) -> RoutePrediction:
        if self.model is None or not isinstance(query, str) or not query.strip():
            return RoutePrediction("unknown", 0.0, "fallback")

        try:
            probabilities = self.model.predict_proba([query.strip()])[0]
            best_index = int(probabilities.argmax())
            confidence = float(probabilities[best_index])
            intent = str(self.model.classes_[best_index])
        except Exception:
            return RoutePrediction("unknown", 0.0, "fallback")

        if confidence < self.confidence_threshold:
            return RoutePrediction(
                intent,
                round(confidence, 4),
                "low_confidence",
            )

        return RoutePrediction(intent, round(confidence, 4), "ml")

    @staticmethod
    def _build_model() -> Pipeline:
        features = FeatureUnion(
            [
                (
                    "word",
                    TfidfVectorizer(
                        ngram_range=(1, 2),
                        sublinear_tf=True,
                    ),
                ),
                (
                    "character",
                    TfidfVectorizer(
                        analyzer="char_wb",
                        ngram_range=(3, 5),
                        sublinear_tf=True,
                    ),
                ),
            ]
        )
        classifier = LogisticRegression(
            C=4.0,
            class_weight="balanced",
            max_iter=1000,
            random_state=42,
        )
        return Pipeline(
            [
                ("features", features),
                ("classifier", classifier),
            ]
        )

    @staticmethod
    def _load_dataset(path: Path) -> tuple[list[str], list[str]]:
        texts = []
        labels = []
        group_ids = set()

        with path.open("r", encoding="utf-8") as dataset_file:
            for line_number, line in enumerate(dataset_file, start=1):
                if not line.strip():
                    continue

                row = json.loads(line)
                text = row.get("text")
                label = row.get("label")
                group_id = row.get("group_id")

                if not isinstance(text, str) or not text.strip():
                    raise ValueError(f"Invalid text at line {line_number}")
                if label not in ALLOWED_INTENTS:
                    raise ValueError(f"Invalid label at line {line_number}")
                if not isinstance(group_id, str) or not group_id.strip():
                    raise ValueError(f"Invalid group_id at line {line_number}")
                if group_id in group_ids:
                    raise ValueError(f"Duplicate group_id at line {line_number}")

                texts.append(text.strip())
                labels.append(label)
                group_ids.add(group_id)

        label_counts = Counter(labels)
        if set(label_counts) != ALLOWED_INTENTS:
            raise ValueError("Dataset does not contain every supported intent")
        if any(
            count < MIN_EXAMPLES_PER_INTENT
            for count in label_counts.values()
        ):
            raise ValueError("Dataset has too few examples for an intent")

        return texts, labels
