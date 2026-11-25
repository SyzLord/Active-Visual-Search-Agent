"""Use the same local image reader, calendar and scheduler as the preceding trial."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "信函水平日期与底部印章_2026-11-18"
sys.path[:0] = [str(HERE), str(OLD), str(HERE.parent / "document-evidence-agent-v3.2"),
                str(HERE.parent / "印章定位放大评测_2026-11-17"), str(HERE.parent / "印章日期修复_2026-11-18"),
                str(HERE.parent / "正文标题优先复读_2026-11-18")]
