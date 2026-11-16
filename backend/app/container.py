from dataclasses import dataclass

from app.providers.mock import MockAvatarEngine, MockLLMProvider, MockTTSProvider
from app.services.conversation_access import ConversationAccessManager
from app.services.orchestrator import ConversationOrchestrator
from app.services.sessions import SessionManager


@dataclass(frozen=True)
class Container:
    orchestrator: ConversationOrchestrator
    sessions: SessionManager
    access: ConversationAccessManager


def build_container() -> Container:
    avatar = MockAvatarEngine()
    orchestrator = ConversationOrchestrator(
        llm=MockLLMProvider(),
        tts=MockTTSProvider(),
        avatar=avatar,
    )
    return Container(
        orchestrator=orchestrator,
        sessions=SessionManager(avatar),
        access=ConversationAccessManager(),
    )


container = build_container()
