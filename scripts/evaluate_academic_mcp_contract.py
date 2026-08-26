import asyncio
import json

from academic_mcp.evaluation import evaluate_mcp_contract
from academic_mcp.server import mcp


async def _main() -> int:
    report = await evaluate_mcp_contract(mcp)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    passed = (
        report["tool_coverage_rate"] == 1.0
        and report["structured_output_rate"] == 1.0
        and report["annotation_accuracy"] == 1.0
        and report["identity_argument_exposure_count"] == 0
        and report["human_approval_guard"]
        and not report["unexpected_tools"]
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
