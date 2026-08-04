import os
from pathlib import Path
import subprocess
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_ENV = {
    "PYTHON_DOTENV_DISABLED": "1",
    "APP_ENV": "test",
    "DATABASE_URL": "sqlite://",
    "JWT_SECRET_KEY": "test-secret-that-is-long-enough-for-validation",
    "LLM_API_KEY": "test-llm-api-key",
    "CORS_ORIGINS": "http://localhost:3000",
    "TRUSTED_HOSTS": "localhost,testserver",
    "AUTH_COOKIE_SECURE": "false",
}

from rag.agentic_graph import AgenticRAGWorkflow
from rag.tracing import reduce_stream, trace_inputs, trace_outputs


class RecordingGraph:
    def __init__(self):
        self.config = None

    def invoke(self, state, config=None):
        self.config = config
        return state


class LangSmithTracingTests(unittest.TestCase):
    def run_config(self, overrides, remove=()):
        environment = os.environ.copy()
        environment.update(BASE_ENV)
        environment.update(overrides)
        for name in remove:
            environment.pop(name, None)

        return subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import os; "
                    "from core.config import settings; "
                    "print(settings.LANGSMITH_TRACING); "
                    "print(os.getenv('LANGSMITH_TRACING'))"
                ),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_tracing_is_enabled_when_key_is_configured(self):
        result = self.run_config(
            {
                "APP_ENV": "development",
                "LANGSMITH_TRACING": "true",
                "LANGSMITH_API_KEY": "test-langsmith-key",
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["True", "true"])

    def test_missing_key_disables_tracing_without_stopping_startup(self):
        result = self.run_config(
            {
                "APP_ENV": "development",
                "LANGSMITH_TRACING": "true",
                "LANGSMITH_API_KEY": "",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "false"])

    def test_test_environment_never_sends_traces(self):
        result = self.run_config(
            {
                "LANGSMITH_TRACING": "true",
                "LANGSMITH_API_KEY": "test-langsmith-key",
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["False", "false"])

    def test_trace_payload_omits_self_and_history_content(self):
        trace_input = trace_inputs(
            {
                "self": object(),
                "user_question": "Tìm phở ở Cầu Giấy",
                "district": "Cầu Giấy",
                "collection_name": "hanoi_food_current",
                "history": [
                    {"role": "user", "content": "private history"},
                ],
            }
        )

        self.assertNotIn("self", trace_input)
        self.assertNotIn("private history", str(trace_input))
        self.assertEqual(trace_input["history_message_count"], 1)

    def test_trace_outputs_are_small_and_stream_is_aggregated(self):
        output = trace_outputs(
            {
                "answer": "Kết quả",
                "context": [{"title": "A"}, {"title": "B"}],
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "latency_ms": 12.5,
            }
        )

        self.assertEqual(output["evidence_count"], 2)
        self.assertNotIn("context", output)
        self.assertEqual(
            reduce_stream(["Xin ", "chào"]),
            {"answer": "Xin chào", "chunk_count": 2},
        )

    def test_graph_trace_metadata_contains_no_user_identifier(self):
        workflow = AgenticRAGWorkflow.__new__(AgenticRAGWorkflow)
        workflow.graph = RecordingGraph()

        workflow.invoke(
            "phở bò",
            district="Cầu Giấy",
            collection_name="hanoi_food_current",
        )

        config = workflow.graph.config
        self.assertEqual(config["run_name"], "agentic_hybrid_rag")
        self.assertEqual(config["metadata"]["district"], "Cầu Giấy")
        self.assertNotIn("user_id", config["metadata"])
        self.assertNotIn("session_id", config["metadata"])


if __name__ == "__main__":
    unittest.main()
