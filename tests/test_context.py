

def test_async_httpx_hook_injects_request_id():
    import asyncio
    import httpx
    from rexbrown_observability import async_httpx_event_hook, request_id_var
    seen = {}
    def handler(req):
        seen["rid"] = req.headers.get("x-request-id")
        return httpx.Response(200)
    async def go():
        tok = request_id_var.set("abc123")
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                         event_hooks={"request": [async_httpx_event_hook]}) as c:
                await c.get("http://x/")
        finally:
            request_id_var.reset(tok)
    asyncio.run(go())
    assert seen["rid"] == "abc123"
