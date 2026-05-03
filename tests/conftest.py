import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.session import get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db: AsyncSession):

    async def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_adk(monkeypatch):

    async def fake_execute_turn(session_id, user_message, state):
        from app.agents.adk_runner import AdkTurnResult

        q = user_message.lower()
        if "rotate" in q or ("deploy" in q and "key" in q):
            return AdkTurnResult(
                reply="According to [chunk_abc] you can rotate a deploy key in Settings.",
                routed_to="knowledge",
                tool_calls=[
                    {
                        "tool_name": "search_docs",
                        "args": {"query": "rotate deploy key", "k": 3},
                        "result": {"ok": True},
                    }
                ],
                retrieved_chunk_ids=["chunk_abc"],
            )
        return AdkTurnResult(
            reply=f"Your current plan tier is {state.plan_tier}.",
            routed_to="smalltalk",
            tool_calls=[],
            retrieved_chunk_ids=[],
        )

    async def fake_execute_turn_stream(session_id, user_message, state):
        res = await fake_execute_turn(session_id, user_message, state)
        yield ("delta", res.reply)
        yield ("complete", res)

    monkeypatch.setattr("app.srop.pipeline.execute_turn", fake_execute_turn)
    monkeypatch.setattr("app.srop.pipeline.execute_turn_stream", fake_execute_turn_stream)
