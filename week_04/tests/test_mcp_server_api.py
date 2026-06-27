from week_04.mcp_server_api import create_post, get_post, list_posts, mcp

EXPECTED_TOOLS = {"list_posts", "get_post", "create_post", "get_current_weather"}


async def _tools_by_name() -> dict:
    return {t.name: t for t in await mcp.list_tools()}


async def test_four_tools_registered():
    assert {t.name for t in await mcp.list_tools()} == EXPECTED_TOOLS


async def test_get_post_requires_post_id():
    tools = await _tools_by_name()
    assert "post_id" in tools["get_post"].inputSchema.get("required", [])


async def test_create_post_required_and_optional_fields():
    schema = (await _tools_by_name())["create_post"].inputSchema
    required = schema.get("required", [])
    assert "title" in required
    assert "body" in required
    assert "userId" not in required


async def test_list_posts_live():
    posts = await list_posts(limit=3)
    assert len(posts) == 3
    assert set(posts[0]) == {"id", "title", "body", "userId"}


async def test_get_post_live():
    post = await get_post(1)
    assert post["id"] == 1


async def test_create_post_live():
    created = await create_post(title="hello", body="world", userId=1)
    assert created["title"] == "hello"
    assert created["id"] == 101
