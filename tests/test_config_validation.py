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
    "JWT_ALGORITHM": "HS256",
    "AUTH_COOKIE_SECURE": "false",
    "AUTH_COOKIE_SAMESITE": "lax",
    "CORS_ORIGINS": "http://localhost:3000",
    "TRUSTED_HOSTS": "localhost,testserver,app.example.com",
    "LLM_API_KEY": "test-llm-api-key",
    "QDRANT_URL": "http://localhost:6333",
}


class ConfigurationTests(unittest.TestCase):
    def run_config(
        self,
        code: str,
        *,
        overrides: dict[str, str] | None = None,
        remove: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment.update(BASE_ENV)
        environment.update(overrides or {})
        environment["PYTHONIOENCODING"] = "utf-8"
        for name in remove:
            environment.pop(name, None)

        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_legacy_qdrant_host_and_port_build_url(self):
        result = self.run_config(
            "from core.config import settings; print(settings.QDRANT_URL)",
            overrides={
                "QDRANT_HOST": "qdrant",
                "QDRANT_PORT": "6333",
            },
            remove=("QDRANT_URL",),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "http://qdrant:6333")

    def test_default_llm_provider_is_gemini(self):
        result = self.run_config(
            (
                "from core.config import settings; "
                "print(settings.LLM_BASE_URL); "
                "print(settings.LLM_MODEL)"
            ),
            remove=("LLM_BASE_URL", "LLM_MODEL"),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "https://generativelanguage.googleapis.com/v1beta/openai",
                "gemini-3.6-flash",
            ],
        )

    def test_gemini_key_is_used_when_generic_key_is_empty(self):
        result = self.run_config(
            "from core.config import settings; print(settings.LLM_API_KEY)",
            overrides={
                "LLM_API_KEY": "",
                "GEMINI_API_KEY": "test-gemini-key",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "test-gemini-key")

    def test_qdrant_url_ignores_platform_port_variable(self):
        result = self.run_config(
            "from core.config import settings; print(settings.QDRANT_URL)",
            overrides={
                "QDRANT_URL": "http://qdrant:6333",
                "QDRANT_PORT": "tcp://10.0.0.1:6333",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "http://qdrant:6333")

    def test_production_requires_secure_cookie(self):
        result = self.run_config(
            "import core.config",
            overrides={
                "APP_ENV": "production",
                "AUTH_COOKIE_SECURE": "false",
                "CORS_ORIGINS": "https://app.example.com",
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AUTH_COOKIE_SECURE=true", result.stderr)

    def test_valid_production_configuration_loads(self):
        result = self.run_config(
            "from core.config import settings; print(settings.APP_ENV)",
            overrides={
                "APP_ENV": "production",
                "AUTH_COOKIE_SECURE": "true",
                "CORS_ORIGINS": "https://app.example.com",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "production")

    def test_production_requires_explicit_trusted_hosts(self):
        missing_hosts = self.run_config(
            "import core.config",
            overrides={
                "APP_ENV": "production",
                "AUTH_COOKIE_SECURE": "true",
                "CORS_ORIGINS": "https://app.example.com",
            },
            remove=("TRUSTED_HOSTS",),
        )
        self.assertNotEqual(missing_hosts.returncode, 0)
        self.assertIn("TRUSTED_HOSTS", missing_hosts.stderr)

        wildcard_hosts = self.run_config(
            "import core.config",
            overrides={
                "APP_ENV": "production",
                "AUTH_COOKIE_SECURE": "true",
                "CORS_ORIGINS": "https://app.example.com",
                "TRUSTED_HOSTS": "*",
            },
        )
        self.assertNotEqual(wildcard_hosts.returncode, 0)
        self.assertIn("TRUSTED_HOSTS", wildcard_hosts.stderr)

        mismatched_origin = self.run_config(
            "import core.config",
            overrides={
                "APP_ENV": "production",
                "AUTH_COOKIE_SECURE": "true",
                "CORS_ORIGINS": "https://app.example.com",
                "TRUSTED_HOSTS": "api.example.com",
            },
        )
        self.assertNotEqual(mismatched_origin.returncode, 0)
        self.assertIn("CORS origin host", mismatched_origin.stderr)

    def test_production_rejects_placeholder_llm_token(self):
        result = self.run_config(
            "import core.config",
            overrides={
                "APP_ENV": "production",
                "AUTH_COOKIE_SECURE": "true",
                "CORS_ORIGINS": "https://app.example.com",
                "LLM_API_KEY": "replace-with-your-token",
            },
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("LLM_API_KEY hợp lệ", result.stderr)

    def test_invalid_boolean_and_cors_origin_fail_fast(self):
        invalid_boolean = self.run_config(
            "import core.config",
            overrides={"AUTH_COOKIE_SECURE": "treu"},
        )
        self.assertNotEqual(invalid_boolean.returncode, 0)
        self.assertIn("true hoặc false", invalid_boolean.stderr)

        invalid_origin = self.run_config(
            "import core.config",
            overrides={"CORS_ORIGINS": "http://localhost:3000.evil.test/path"},
        )
        self.assertNotEqual(invalid_origin.returncode, 0)
        self.assertIn("Origin không hợp lệ", invalid_origin.stderr)

    def test_invalid_operational_settings_fail_fast(self):
        invalid_retry = self.run_config(
            "import core.config",
            overrides={"EXTERNAL_RETRY_ATTEMPTS": "0"},
        )
        self.assertNotEqual(invalid_retry.returncode, 0)
        self.assertIn("EXTERNAL_RETRY_ATTEMPTS", invalid_retry.stderr)

        invalid_log_level = self.run_config(
            "import core.config",
            overrides={"LOG_LEVEL": "VERBOSE"},
        )
        self.assertNotEqual(invalid_log_level.returncode, 0)
        self.assertIn("LOG_LEVEL", invalid_log_level.stderr)

        invalid_llm_budget = self.run_config(
            "import core.config",
            overrides={"LLM_DAILY_USER_REQUESTS": "0"},
        )
        self.assertNotEqual(invalid_llm_budget.returncode, 0)
        self.assertIn("LLM_DAILY_USER_REQUESTS", invalid_llm_budget.stderr)


if __name__ == "__main__":
    unittest.main()
