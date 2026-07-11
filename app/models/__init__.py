"""SQLAlchemy ORM models mapping the brief Section 6.2 schema.

Importing this package registers every model on Base.metadata, which Alembic's
autogenerate and the test fixtures rely on.
"""

from app.models.analysis import CommentAnalysis, Topic
from app.models.content import Comment, Post, PostMetricSnapshot
from app.models.ops import AgentRun, LLMCall, RawEvent, SyncCursor
from app.models.platform_account import Account, FollowerSnapshot, Platform
from app.models.reco_gen import GeneratedContent, Recommendation

__all__ = [
    "Platform",
    "Account",
    "FollowerSnapshot",
    "Post",
    "PostMetricSnapshot",
    "Comment",
    "CommentAnalysis",
    "Topic",
    "Recommendation",
    "GeneratedContent",
    "LLMCall",
    "RawEvent",
    "SyncCursor",
    "AgentRun",
]
