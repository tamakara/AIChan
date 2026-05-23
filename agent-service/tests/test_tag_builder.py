from agent_service.services.tag_builder import build_session_start_tag


def test_build_session_start_tag_with_session_id() -> None:
    tag = build_session_start_tag(
        agent_id='agent_"1',
        metadata={"session_id": 'private_"1'},
    )
    assert tag == '<session_start agent_id="agent_&quot;1" session_id="private_&quot;1">'


def test_build_session_start_tag_without_session_id() -> None:
    tag = build_session_start_tag(agent_id="agent_1", metadata={})
    assert tag == '<session_start agent_id="agent_1">'

