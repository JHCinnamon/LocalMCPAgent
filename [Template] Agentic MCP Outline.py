import subprocess
import sys

subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])

import asyncio
import json
from typing import Any, Dict

from ollama import Client

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


OLLAMA_MODEL = "llama3.2"
MCP_URL = "http://localhost:3000/mcp"

ollama = Client(host="http://localhost:11434")


class MCPAgent:

    def __init__(self):
        self.tool_map = {}

    async def connect(self):
        self.http_ctx = streamablehttp_client(MCP_URL)
        read_stream, write_stream, _ = await self.http_ctx.__aenter__()

        self.session = ClientSession(read_stream, write_stream)
        await self.session.initialize()

        tools_response = await self.session.list_tools()

        self.tool_map = {}

        ollama_tools = []

        for tool in tools_response.tools:
            self.tool_map[tool.name] = tool

            ollama_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema,
                    },
                }
            )

        self.ollama_tools = ollama_tools

        print("\nAvailable tools:")
        for t in self.tool_map:
            print(" -", t)

    async def close(self):
        await self.http_ctx.__aexit__(None, None, None)

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> Any:

        result = await self.session.call_tool(
            name,
            arguments
        )

        return result

    async def run(self, user_question: str):

        messages = [
            {
                "role": "system",
                "content": """
You are an economic research agent.

You have access to MCP tools.

Use tools whenever needed.
You may call multiple tools.
Continue calling tools until you have enough
information to answer the user.

When finished, provide a complete answer.
""",
            },
            {
                "role": "user",
                "content": user_question,
            },
        ]

        while True:

            response = ollama.chat(
                model=OLLAMA_MODEL,
                messages=messages,
                tools=self.ollama_tools,
            )

            assistant_message = response["message"]

            tool_calls = assistant_message.get("tool_calls", [])

            if not tool_calls:
                return assistant_message["content"]

            messages.append(assistant_message)

            for call in tool_calls:

                fn_name = call["function"]["name"]

                args = call["function"].get(
                    "arguments",
                    {}
                )

                print(f"\nCalling tool: {fn_name}")
                print(json.dumps(args, indent=2))

                try:
                    tool_result = await self.call_tool(
                        fn_name,
                        args,
                    )

                    content = json.dumps(
                        tool_result.model_dump()
                        if hasattr(tool_result, "model_dump")
                        else str(tool_result),
                        default=str,
                    )

                except Exception as e:
                    content = json.dumps(
                        {"error": str(e)}
                    )

                messages.append(
                    {
                        "role": "tool",
                        "tool_name": fn_name,
                        "content": content,
                    }
                )


async def main():

    agent = MCPAgent()

    await agent.connect()

    try:

        while True:

            question = input("\nQuestion > ")

            if question.lower() in (
                "quit",
                "exit",
            ):
                break

            answer = await agent.run(question)

            print("\nAnswer:")
            print(answer)

    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())