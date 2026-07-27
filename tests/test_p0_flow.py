import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest


TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="rag-chat-p0-")
TEST_DATABASE_PATH = Path(TEST_DIRECTORY.name, "p0.sqlite3").resolve()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE_PATH.as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET_KEY"] = "p0-test-secret-that-is-not-used-in-production"
os.environ["GITHUB_TOKEN"] = "p0-test-github-token"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "60"
os.environ["CORS_ORIGINS"] = (
    "http://localhost:3000,http://127.0.0.1:3000"
)
os.environ["AUTH_COOKIE_SECURE"] = "false"
os.environ["AUTH_COOKIE_SAMESITE"] = "lax"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["CHAT_RATE_LIMIT_REQUESTS"] = "20"
os.environ["CHAT_RATE_LIMIT_WINDOW_SECONDS"] = "60"
os.environ["DB_SCHEMA_CHECK"] = "false"

from fastapi.testclient import TestClient
from sqlalchemy import event

from core.config import settings
from core.security import create_access_token
from database.connection import Base, SessionLocal, engine
from database.models import ChatSessionModel, MessageModel, UserModel
from main import app
from routers import chat as chat_router
from schemas.chat import ChatRequest


TRUSTED_ORIGIN = settings.CORS_ORIGINS[0]


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class FakeRAGPipeline:
    def __init__(self):
        self.calls = []
        self.answer = None
        self.stream_chunks = None
        self.error = None
        self.delay_seconds = 0

    def _record_call(
        self,
        *,
        user_question,
        collection_name,
        district,
        history,
    ):
        self.calls.append(
            {
                "question": user_question,
                "collection_name": collection_name,
                "district": district,
                "history": history,
            }
        )

    def _answer_for(self, user_question):
        if self.answer is not None:
            return self.answer
        return f"Trả lời kiểm thử cho: {user_question}"

    def run(
        self,
        *,
        user_question,
        collection_name,
        district,
        history,
    ):
        self._record_call(
            user_question=user_question,
            collection_name=collection_name,
            district=district,
            history=history,
        )
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return self._answer_for(user_question)

    async def stream(
        self,
        *,
        user_question,
        collection_name,
        district,
        history,
    ):
        self._record_call(
            user_question=user_question,
            collection_name=collection_name,
            district=district,
            history=history,
        )
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.error is not None and self.stream_chunks is None:
            raise self.error

        answer = self._answer_for(user_question)
        midpoint = max(1, len(answer) // 2)
        chunks = self.stream_chunks
        if chunks is None:
            chunks = [answer[:midpoint], answer[midpoint:]]

        for chunk in chunks:
            yield chunk
            await asyncio.sleep(0)

        if self.error is not None:
            raise self.error


class SecretObject:
    def __str__(self):
        return "TOP_SECRET_INTERNAL_VALUE"


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    normalized = body.replace("\r\n", "\n")
    for frame in normalized.split("\n\n"):
        if not frame.strip():
            continue
        event_name = "message"
        data_lines = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
        payload = json.loads("\n".join(data_lines)) if data_lines else {}
        events.append((event_name, payload))
    return events


class P0FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        TEST_DIRECTORY.cleanup()

    def setUp(self):
        database = SessionLocal()
        try:
            database.query(MessageModel).delete()
            database.query(ChatSessionModel).delete()
            database.query(UserModel).delete()
            database.commit()
        finally:
            database.close()

        self.fake_rag = FakeRAGPipeline()
        app.state.rag_pipeline = self.fake_rag

    def register_and_login(self, username: str) -> TestClient:
        client = TestClient(
            app,
            headers={"Origin": TRUSTED_ORIGIN},
        )
        register_response = client.post(
            "/api/auth/register",
            json={"username": username, "password": "password123"},
        )
        self.assertEqual(register_response.status_code, 201)
        login_response = client.post(
            "/api/auth/login",
            json={"username": username, "password": "password123"},
        )
        self.assertEqual(login_response.status_code, 200)
        return client

    def test_auth_cookie_me_and_logout(self):
        client = TestClient(app)
        self.assertEqual(client.get("/api/auth/me").status_code, 401)

        client = self.register_and_login("auth-user")
        me_response = client.get("/api/auth/me")
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.json()["username"], "auth-user")

        logout_response = client.post("/api/auth/logout")
        self.assertEqual(logout_response.status_code, 200)
        self.assertEqual(client.get("/api/auth/me").status_code, 401)

    def test_csrf_rejects_untrusted_auth_requests(self):
        evil_origin = "https://evil.example"
        attacker = TestClient(
            app,
            headers={"Origin": evil_origin},
        )
        register_response = attacker.post(
            "/api/auth/register",
            json={"username": "csrf-user", "password": "password123"},
        )
        self.assertEqual(register_response.status_code, 403)

        same_origin_client = TestClient(
            app,
            headers={"Origin": "http://testserver"},
        )
        same_origin_register = same_origin_client.post(
            "/api/auth/register",
            json={
                "username": "same-origin-user",
                "password": "password123",
            },
        )
        self.assertEqual(same_origin_register.status_code, 201)

        client = self.register_and_login("csrf-user")
        calls_before_attack = len(self.fake_rag.calls)

        del client.headers["Origin"]
        missing_origin = client.post(
            "/api/chat/stream",
            json={"question": "Yêu cầu thiếu origin"},
        )
        self.assertEqual(missing_origin.status_code, 403)

        spoofed_origin = client.post(
            "/api/chat/stream",
            headers={"Origin": f"{TRUSTED_ORIGIN}.evil.example"},
            json={"question": "Yêu cầu giả origin"},
        )
        self.assertEqual(spoofed_origin.status_code, 403)
        self.assertEqual(len(self.fake_rag.calls), calls_before_attack)

        valid_referer = client.post(
            "/api/chat/stream",
            headers={"Referer": f"{TRUSTED_ORIGIN}/chat"},
            json={"question": "Yêu cầu hợp lệ"},
        )
        self.assertEqual(valid_referer.status_code, 200)
        session_id = parse_sse(valid_referer.text)[0][1]["session_id"]

        rejected_delete = client.delete(
            f"/api/history/{session_id}",
            headers={"Origin": evil_origin},
        )
        self.assertEqual(rejected_delete.status_code, 403)
        self.assertEqual(
            client.get(f"/api/history/{session_id}").status_code,
            200,
        )

        rejected_logout = client.post(
            "/api/auth/logout",
            headers={"Origin": "null"},
        )
        self.assertEqual(rejected_logout.status_code, 403)
        self.assertEqual(client.get("/api/auth/me").status_code, 200)

        allowed_delete = client.delete(
            f"/api/history/{session_id}",
            headers={"Origin": TRUSTED_ORIGIN},
        )
        self.assertEqual(allowed_delete.status_code, 200)

        cross_origin_login = attacker.post(
            "/api/auth/login",
            json={"username": "csrf-user", "password": "password123"},
        )
        self.assertEqual(cross_origin_login.status_code, 403)
        self.assertIsNone(
            attacker.cookies.get(settings.AUTH_COOKIE_NAME)
        )

    def test_bearer_only_write_bypasses_cookie_csrf(self):
        cookie_client = self.register_and_login("bearer-user")
        cookie_value = cookie_client.cookies.get(
            settings.AUTH_COOKIE_NAME
        )
        self.assertIsNotNone(cookie_value)
        access_token = create_access_token({"sub": "bearer-user"})

        bearer_client = TestClient(
            app,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response = bearer_client.post(
            "/api/chat",
            json={"question": "Bearer API request"},
        )
        self.assertEqual(response.status_code, 200)

        del cookie_client.headers["Origin"]
        cookie_client.headers["Authorization"] = (
            f"Bearer {access_token}"
        )
        cookie_and_bearer = cookie_client.post(
            "/api/chat",
            json={"question": "Cookie vẫn phải kiểm tra CSRF"},
        )
        self.assertEqual(cookie_and_bearer.status_code, 403)

    def test_unauthenticated_stream_creates_no_rows(self):
        client = TestClient(app)
        response = client.post(
            "/api/chat/stream",
            json={"question": "Phở ngon ở đâu?"},
        )
        self.assertEqual(response.status_code, 401)

        database = SessionLocal()
        try:
            self.assertEqual(database.query(ChatSessionModel).count(), 0)
            self.assertEqual(database.query(MessageModel).count(), 0)
        finally:
            database.close()

    def test_two_turn_stream_history_ownership_and_cascade(self):
        owner = self.register_and_login("owner")

        first_response = owner.post(
            "/api/chat/stream",
            json={"question": "Phở ngon ở Hoàn Kiếm?", "district": "Ba Đình"},
        )
        self.assertEqual(first_response.status_code, 200)
        first_events = parse_sse(first_response.text)
        self.assertEqual(first_events[0][0], "session")
        self.assertEqual(first_events[-1][0], "done")
        self.assertEqual(
            [event[0] for event in first_events],
            ["session", "token", "token", "done"],
        )
        session_id = first_events[0][1]["session_id"]

        second_response = owner.post(
            "/api/chat/stream",
            json={
                "session_id": session_id,
                "question": "Quán mở cửa lúc nào?",
                "district": "Hoàn Kiếm",
            },
        )
        self.assertEqual(second_response.status_code, 200)
        second_events = parse_sse(second_response.text)
        self.assertEqual(second_events[0][1]["session_id"], session_id)
        self.assertEqual(second_events[-1][0], "done")
        self.assertEqual(
            self.fake_rag.calls[1]["history"],
            [
                {
                    "role": "user",
                    "content": "Phở ngon ở Hoàn Kiếm?",
                },
                {
                    "role": "assistant",
                    "content": "Trả lời kiểm thử cho: Phở ngon ở Hoàn Kiếm?",
                },
            ],
        )

        sessions_response = owner.get("/api/history")
        self.assertEqual(sessions_response.status_code, 200)
        self.assertEqual(len(sessions_response.json()), 1)

        messages_response = owner.get(f"/api/history/{session_id}")
        self.assertEqual(messages_response.status_code, 200)
        messages = messages_response.json()
        self.assertEqual(
            [message["role"] for message in messages],
            ["user", "assistant", "user", "assistant"],
        )
        self.assertEqual([message["position"] for message in messages], [0, 1, 2, 3])
        self.assertTrue(
            all(message["status"] == "completed" for message in messages)
        )
        self.assertEqual(messages[0]["district_filter"], "Hoàn Kiếm")

        other_user = self.register_and_login("other-user")
        calls_before_attack = len(self.fake_rag.calls)
        forbidden_stream = other_user.post(
            "/api/chat/stream",
            json={"session_id": session_id, "question": "Đọc session người khác"},
        )
        self.assertEqual(forbidden_stream.status_code, 404)
        self.assertEqual(len(self.fake_rag.calls), calls_before_attack)
        self.assertEqual(
            other_user.get(f"/api/history/{session_id}").status_code,
            404,
        )
        self.assertEqual(
            other_user.delete(f"/api/history/{session_id}").status_code,
            404,
        )

        delete_response = owner.delete(f"/api/history/{session_id}")
        self.assertEqual(delete_response.status_code, 200)

        database = SessionLocal()
        try:
            self.assertEqual(
                database.query(ChatSessionModel)
                .filter(ChatSessionModel.id == session_id)
                .count(),
                0,
            )
            self.assertEqual(
                database.query(MessageModel)
                .filter(MessageModel.session_id == session_id)
                .count(),
                0,
            )
        finally:
            database.close()

    def test_stream_failure_is_persisted_as_error(self):
        client = self.register_and_login("failure-user")
        self.fake_rag.error = RuntimeError("internal test failure")

        response = client.post(
            "/api/chat/stream",
            json={"question": "Câu hỏi gây lỗi"},
        )
        self.assertEqual(response.status_code, 200)
        events = parse_sse(response.text)
        self.assertEqual([event[0] for event in events], ["session", "error"])
        self.assertEqual(events[-1][1]["code"], "RAG_FAILED")
        self.assertNotIn("internal test failure", response.text)

        session_id = events[0][1]["session_id"]
        messages = client.get(f"/api/history/{session_id}").json()
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual(messages[0]["status"], "completed")
        self.assertEqual(messages[1]["status"], "error")

    def test_invalid_rag_types_do_not_leak_internal_string(self):
        sync_client = self.register_and_login("invalid-sync-user")
        self.fake_rag.answer = SecretObject()

        sync_response = sync_client.post(
            "/api/chat",
            json={"question": "Câu hỏi sync lỗi kiểu dữ liệu"},
        )
        self.assertEqual(sync_response.status_code, 502)
        self.assertNotIn("TOP_SECRET_INTERNAL_VALUE", sync_response.text)

        self.fake_rag.answer = None
        self.fake_rag.stream_chunks = [SecretObject()]
        stream_client = self.register_and_login("invalid-stream-user")
        stream_response = stream_client.post(
            "/api/chat/stream",
            json={"question": "Câu hỏi stream lỗi kiểu dữ liệu"},
        )
        events = parse_sse(stream_response.text)
        self.assertEqual([event[0] for event in events], ["session", "error"])
        self.assertEqual(events[-1][1]["code"], "RAG_FAILED")
        self.assertNotIn("TOP_SECRET_INTERNAL_VALUE", stream_response.text)

    def test_disconnect_after_session_event_finalizes_pending_message(self):
        self.register_and_login("disconnect-user")
        database = SessionLocal()
        try:
            user = (
                database.query(UserModel)
                .filter(UserModel.username == "disconnect-user")
                .one()
            )

            async def disconnect_after_session():
                response = await chat_router.chat_stream(
                    payload=ChatRequest(question="Ngắt kết nối sớm"),
                    current_user=user,
                    db=database,
                    rag_pipeline=self.fake_rag,
                )
                first_chunk = await response.body_iterator.__anext__()
                await response.body_iterator.aclose()
                return first_chunk

            first_chunk = asyncio.run(disconnect_after_session())
            events = parse_sse(first_chunk)
            self.assertEqual([event[0] for event in events], ["session"])
            session_id = events[0][1]["session_id"]
        finally:
            database.close()

        database = SessionLocal()
        try:
            assistant_message = (
                database.query(MessageModel)
                .filter(
                    MessageModel.session_id == session_id,
                    MessageModel.role == "assistant",
                )
                .one()
            )
            self.assertEqual(assistant_message.status, "error")
            self.assertTrue(assistant_message.content)
        finally:
            database.close()

    def test_memory_keeps_only_three_recent_complete_turns(self):
        client = self.register_and_login("memory-limit-user")
        session_id = None

        for turn_number in range(1, 5):
            response = client.post(
                "/api/chat/stream",
                json={
                    "session_id": session_id,
                    "question": f"Câu hỏi số {turn_number}",
                },
            )
            events = parse_sse(response.text)
            self.assertEqual(events[-1][0], "done")
            session_id = events[0][1]["session_id"]

        last_history = self.fake_rag.calls[-1]["history"]
        self.assertEqual(len(last_history), 6)
        self.assertEqual(
            [
                message["content"]
                for message in last_history
                if message["role"] == "user"
            ],
            ["Câu hỏi số 1", "Câu hỏi số 2", "Câu hỏi số 3"],
        )
        self.assertNotIn(
            "Câu hỏi số 4",
            [message["content"] for message in last_history],
        )

    def test_stream_timeout_returns_error_event(self):
        client = self.register_and_login("timeout-user")
        self.fake_rag.delay_seconds = 0.1

        from core.config import settings
        from routers.chat import LLM_TIMEOUT_MESSAGE

        original_timeout = settings.LLM_TIMEOUT_SECONDS
        settings.LLM_TIMEOUT_SECONDS = 0.01
        try:
            response = client.post(
                "/api/chat/stream",
                json={"question": "Câu hỏi bị quá thời gian"},
            )
        finally:
            settings.LLM_TIMEOUT_SECONDS = original_timeout

        self.assertEqual(response.status_code, 200)
        events = parse_sse(response.text)
        self.assertEqual([event[0] for event in events], ["session", "error"])
        self.assertEqual(events[-1][1]["code"], "LLM_TIMEOUT")
        self.assertEqual(events[-1][1]["message"], LLM_TIMEOUT_MESSAGE)

        session_id = events[0][1]["session_id"]
        messages = client.get(f"/api/history/{session_id}").json()
        self.assertEqual(messages[-1]["status"], "error")
        self.assertEqual(messages[-1]["content"], LLM_TIMEOUT_MESSAGE)

    def test_stream_partial_error_keeps_received_content(self):
        client = self.register_and_login("partial-error-user")
        self.fake_rag.stream_chunks = ["Câu trả lời", " đang dở"]
        self.fake_rag.error = RuntimeError("internal partial failure")

        response = client.post(
            "/api/chat/stream",
            json={"question": "Câu hỏi nhận phản hồi dở"},
        )

        self.assertEqual(response.status_code, 200)
        events = parse_sse(response.text)
        self.assertEqual(
            [event[0] for event in events],
            ["session", "token", "token", "error"],
        )
        self.assertEqual(
            "".join(
                event[1]["content"]
                for event in events
                if event[0] == "token"
            ),
            "Câu trả lời đang dở",
        )
        self.assertEqual(
            events[-1][1]["assistant_message"]["content"],
            "Câu trả lời đang dở",
        )

        session_id = events[0][1]["session_id"]
        messages = client.get(f"/api/history/{session_id}").json()
        self.assertEqual(messages[-1]["status"], "error")
        self.assertEqual(messages[-1]["content"], "Câu trả lời đang dở")

        self.fake_rag.stream_chunks = None
        self.fake_rag.error = None
        follow_up = client.post(
            "/api/chat/stream",
            json={
                "session_id": session_id,
                "question": "Câu hỏi tiếp theo",
            },
        )
        self.assertEqual(parse_sse(follow_up.text)[-1][0], "done")
        self.assertEqual(self.fake_rag.calls[-1]["history"], [])

    def test_empty_rag_answer_returns_error_event(self):
        client = self.register_and_login("empty-answer-user")
        self.fake_rag.answer = ""

        response = client.post(
            "/api/chat/stream",
            json={"question": "Câu hỏi nhận nội dung rỗng"},
        )

        self.assertEqual(response.status_code, 200)
        events = parse_sse(response.text)
        self.assertEqual([event[0] for event in events], ["session", "error"])

        session_id = events[0][1]["session_id"]
        messages = client.get(f"/api/history/{session_id}").json()
        self.assertEqual(messages[-1]["status"], "error")

    def test_database_backed_rate_limit(self):
        client = self.register_and_login("rate-user")

        from core.config import settings

        original_limit = settings.CHAT_RATE_LIMIT_REQUESTS
        settings.CHAT_RATE_LIMIT_REQUESTS = 1
        try:
            first = client.post(
                "/api/chat",
                json={"question": "Câu đầu tiên"},
            )
            self.assertEqual(first.status_code, 200)

            second = client.post(
                "/api/chat",
                json={"question": "Câu thứ hai"},
            )
            self.assertEqual(second.status_code, 429)
            self.assertIn("Retry-After", second.headers)
        finally:
            settings.CHAT_RATE_LIMIT_REQUESTS = original_limit


if __name__ == "__main__":
    unittest.main()
