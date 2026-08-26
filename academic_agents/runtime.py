import asyncio
import threading
from pathlib import Path

from academic_agents.assessment import AssessmentAgent
from academic_agents.assessment_workflow import AcademicAssessmentWorkflow
from academic_agents.knowledge import KnowledgeAgent
from academic_agents.llm import OpenAICompatibleChatModel
from academic_agents.orchestrator import AcademicAgentWorkflow
from academic_agents.planning import PlanningAgent
from academic_agents.planning_workflow import AcademicPlanningWorkflow
from academic_agents.routing import OrchestratorAgent
from academic_agents.tool import AcademicRetrievalTool
from academic_agents.verification import VerificationAgent
from academic_retrieval.service import AcademicHybridRetriever
from assessment.question_bank import QuestionBankRegistry
from planning.learning_map import LearningMapRegistry
from courses.naming import vector_alias_for
from schemas.agents import AcademicAssistantRequest, AcademicAssistantResponse
from schemas.course import COURSE_ID_PATTERN, VERSION_PATTERN
from llm.provider import OpenAICompatibleProvider, provider_config_from_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AcademicRuntimeConfigurationError(RuntimeError):
    pass


class AcademicRetrieverRegistry:
    """Lazy per-course retriever cache used by one generic academic tool."""

    def __init__(
        self,
        *,
        data_root: str | Path,
        qdrant_url: str,
        qdrant_api_key: str | None,
        timeout_seconds: float,
        local_files_only: bool,
    ) -> None:
        root = Path(data_root)
        if not root.is_absolute():
            root = PROJECT_ROOT / root
        self.data_root = root.resolve()
        self.qdrant_url = qdrant_url
        self.qdrant_api_key = qdrant_api_key
        self.timeout_seconds = timeout_seconds
        self.local_files_only = local_files_only
        self._retrievers = {}
        self._lock = threading.Lock()

    def _course_directory(self, course_id: str, course_version: str) -> Path:
        if not COURSE_ID_PATTERN.fullmatch(course_id):
            raise AcademicRuntimeConfigurationError("course_id không hợp lệ.")
        if not VERSION_PATTERN.fullmatch(course_version):
            raise AcademicRuntimeConfigurationError("course_version không hợp lệ.")
        course_directory = (
            self.data_root / course_id / course_version
        ).resolve()
        try:
            course_directory.relative_to(self.data_root)
        except ValueError as exc:
            raise AcademicRuntimeConfigurationError(
                "Đường dẫn course artifact không an toàn."
            ) from exc
        return course_directory

    def get(self, course_id: str, course_version: str):
        key = (course_id, course_version)
        retriever = self._retrievers.get(key)
        if retriever is not None:
            return retriever

        with self._lock:
            retriever = self._retrievers.get(key)
            if retriever is not None:
                return retriever
            course_directory = self._course_directory(
                course_id,
                course_version,
            )
            processed_directory = course_directory / "processed"
            indexed_directory = course_directory / "indexed"
            if not processed_directory.is_dir() or not indexed_directory.is_dir():
                raise AcademicRuntimeConfigurationError(
                    "Môn học chưa có đầy đủ processed/indexed artifact."
                )
            retriever = AcademicHybridRetriever.from_artifacts(
                str(processed_directory),
                str(indexed_directory),
                qdrant_url=self.qdrant_url,
                qdrant_api_key=self.qdrant_api_key,
                timeout_seconds=self.timeout_seconds,
                local_files_only=self.local_files_only,
                collection_name=vector_alias_for(course_id),
            )
            self._retrievers[key] = retriever
            return retriever

    def close(self) -> None:
        with self._lock:
            retrievers = list(self._retrievers.values())
            self._retrievers.clear()
        for retriever in retrievers:
            retriever.close()


class AcademicAgentRuntime:
    def __init__(
        self,
        *,
        workflow: AcademicAgentWorkflow,
        retriever_registry: AcademicRetrieverRegistry | None = None,
        provider: OpenAICompatibleProvider | None = None,
        assessment_workflow: AcademicAssessmentWorkflow | None = None,
        question_bank_registry: QuestionBankRegistry | None = None,
        planning_workflow: AcademicPlanningWorkflow | None = None,
        learning_map_registry: LearningMapRegistry | None = None,
        orchestrator_agent: OrchestratorAgent | None = None,
        default_top_k: int = 5,
    ) -> None:
        if default_top_k <= 0 or default_top_k > 8:
            raise ValueError("default_top_k phải từ 1 đến 8.")
        self.workflow = workflow
        self.retriever_registry = retriever_registry
        self.provider = provider
        self.assessment_workflow = assessment_workflow
        self.question_bank_registry = question_bank_registry
        self.planning_workflow = planning_workflow
        self.learning_map_registry = learning_map_registry
        self.orchestrator_agent = (
            orchestrator_agent
            or getattr(workflow, "orchestrator_agent", None)
        )
        self.default_top_k = default_top_k

    @classmethod
    def from_settings(cls, settings) -> "AcademicAgentRuntime":
        provider = OpenAICompatibleProvider(
            provider_config_from_settings(settings)
        )
        chat_model = OpenAICompatibleChatModel(
            provider,
            max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            reasoning_effort=settings.LLM_REASONING_EFFORT,
        )
        registry = AcademicRetrieverRegistry(
            data_root=settings.COURSE_DATA_ROOT,
            qdrant_url=settings.QDRANT_URL,
            qdrant_api_key=settings.QDRANT_API_KEY,
            timeout_seconds=settings.QDRANT_TIMEOUT_SECONDS,
            local_files_only=settings.EMBEDDING_LOCAL_FILES_ONLY,
        )
        retrieval_tool = AcademicRetrievalTool(registry.get)
        verification_agent = VerificationAgent(chat_model)
        orchestrator_agent = OrchestratorAgent(chat_model)
        workflow = AcademicAgentWorkflow(
            orchestrator_agent=orchestrator_agent,
            knowledge_agent=KnowledgeAgent(chat_model, retrieval_tool),
            verification_agent=verification_agent,
            max_revisions=settings.ACADEMIC_AGENT_MAX_REVISIONS,
            tracing_enabled=settings.LANGSMITH_TRACING,
        )
        question_bank_registry = QuestionBankRegistry(
            settings.COURSE_DATA_ROOT
        )
        assessment_workflow = AcademicAssessmentWorkflow(
            assessment_agent=AssessmentAgent(),
            verification_agent=verification_agent,
            tracing_enabled=settings.LANGSMITH_TRACING,
        )
        learning_map_registry = LearningMapRegistry(settings.COURSE_DATA_ROOT)
        planning_workflow = AcademicPlanningWorkflow(
            planning_agent=PlanningAgent(),
            verification_agent=verification_agent,
            tracing_enabled=settings.LANGSMITH_TRACING,
        )
        return cls(
            workflow=workflow,
            retriever_registry=registry,
            provider=provider,
            assessment_workflow=assessment_workflow,
            question_bank_registry=question_bank_registry,
            planning_workflow=planning_workflow,
            learning_map_registry=learning_map_registry,
            orchestrator_agent=orchestrator_agent,
            default_top_k=settings.ACADEMIC_AGENT_TOP_K,
        )

    def ask(
        self,
        request: AcademicAssistantRequest,
    ) -> AcademicAssistantResponse:
        return self.workflow.invoke(
            question=request.question,
            course_id=request.course_id,
            course_version=request.course_version,
            top_k=request.top_k or self.default_top_k,
        )

    async def aclose(self) -> None:
        if self.learning_map_registry is not None:
            self.learning_map_registry.clear()
        if self.question_bank_registry is not None:
            self.question_bank_registry.clear()
        if self.retriever_registry is not None:
            await asyncio.to_thread(self.retriever_registry.close)
        if self.provider is not None:
            await self.provider.aclose()
