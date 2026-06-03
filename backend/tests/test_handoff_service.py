import pytest

from core.kanban_protocol.handoff import HandoffService
from core.kanban_protocol.lanes import WORKER_LANES


@pytest.mark.asyncio
async def test_create_returns_pending_handoff():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={"diff_summary": "wip"},
        created_by="alice",
    )
    assert handoff["status"] == "pending"
    assert handoff["toLane"] == "frontend"
    assert handoff["createdBy"] == "alice"
    assert handoff["boardId"] == "board-default"


@pytest.mark.asyncio
async def test_create_rejects_unknown_target_lane():
    svc = HandoffService()
    with pytest.raises(ValueError) as exc_info:
        await svc.create(
            issue_id="issue-1",
            board_id="board-default",
            from_lane=None,
            to_lane="not-a-lane",
            payload={},
            created_by="alice",
        )
    assert "Unknown worker lane" in str(exc_info.value)


@pytest.mark.asyncio
async def test_accept_moves_pending_to_accepted():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    accepted = await svc.accept(handoff["id"], actor="bob")
    assert accepted["status"] == "accepted"
    assert accepted["acceptedBy"] == "bob"


@pytest.mark.asyncio
async def test_accept_rejects_non_pending_handoff():
    svc = HandoffService()
    handoff = await svc.create(
        issue_id="issue-1",
        board_id="board-default",
        from_lane=None,
        to_lane="frontend",
        payload={},
        created_by="alice",
    )
    await svc.accept(handoff["id"], actor="bob")
    with pytest.raises(ValueError) as exc_info:
        await svc.accept(handoff["id"], actor="bob")
    assert "cannot accept" in str(exc_info.value).lower()
