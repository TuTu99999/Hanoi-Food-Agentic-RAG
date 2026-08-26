from dataclasses import dataclass
import os


class AcademicMcpConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AcademicMcpSettings:
    """Identity binding for the trusted local stdio process."""

    user_id: int

    @classmethod
    def from_env(cls) -> "AcademicMcpSettings":
        raw_user_id = os.getenv("ACADEMIC_MCP_USER_ID", "").strip()
        if not raw_user_id:
            raise AcademicMcpConfigurationError(
                "Cần cấu hình ACADEMIC_MCP_USER_ID trước khi chạy MCP server."
            )
        try:
            user_id = int(raw_user_id)
        except ValueError as exc:
            raise AcademicMcpConfigurationError(
                "ACADEMIC_MCP_USER_ID phải là số nguyên dương."
            ) from exc
        if user_id <= 0:
            raise AcademicMcpConfigurationError(
                "Cần cấu hình ACADEMIC_MCP_USER_ID trước khi chạy MCP server."
            )
        return cls(user_id=user_id)


__all__ = ["AcademicMcpConfigurationError", "AcademicMcpSettings"]
