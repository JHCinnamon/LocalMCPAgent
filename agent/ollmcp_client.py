from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class MCPExecutor:

    def __init__(self, url):

        self.url = url

    async def execute(self, instruction):

        async with streamablehttp_client(self.url) as (
            read_stream,
            write_stream,
            _
        ):

            async with ClientSession(
                read_stream,
                write_stream
            ) as session:

                await session.initialize()

                response = await session.call_tool(
                    "agent",
                    {
                        "instruction": instruction
                    }
                )

                return response.content