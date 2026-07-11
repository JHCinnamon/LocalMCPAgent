import asyncio  # Import library to run tasks that can wait without freezing the program
import json  # Import library to convert between Python objects and JSON text
from typing import Any, Dict  # Import type names to describe what kinds of values functions use

from ollama import Client  # Import the Ollama client used to talk to the language model service

from mcp import ClientSession  # Import the MCP session class for talking to MCP tools
from mcp.client.streamable_http import streamablehttp_client  # Import a helper to create a stream-based HTTP client


OLLAMA_MODEL = "llama3.2"  # The name of the model used for generating responses
MCP_URL = "http://localhost:3000/mcp"  # The address for the MCP service

ollama = Client(host="http://localhost:11434")  # Create a client to connect to the Ollama service


class MCPAgent:

    def __init__(self):
        self.tool_map = {}  # Start with an empty dictionary of tools

    async def connect(self):
        self.http_ctx = streamablehttp_client(MCP_URL)  # Prepare the HTTP stream helper for MCP
        read_stream, write_stream, _ = await self.http_ctx.__aenter__()  # Open the connection streams

        self.session = ClientSession(read_stream, write_stream)  # Create an MCP session using the streams
        await self.session.initialize()  # Initialize the MCP session

        tools_response = await self.session.list_tools()  # Ask MCP which tools are available

        self.tool_map = {}  # Reset the tool map just in case

        ollama_tools = []  # Prepare a list of tool descriptions for Ollama

        for tool in tools_response.tools:
            self.tool_map[tool.name] = tool  # Store each tool by name

            ollama_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema,
                    },
                }
            )  # Build the tool description Ollama expects

        self.ollama_tools = ollama_tools  # Save the list of Ollama-compatible tool descriptions

        print("\nAvailable tools:")
        for t in self.tool_map:
            print(" -", t)  # Print the names of all available tools

    async def close(self):
        await self.http_ctx.__aexit__(None, None, None)  # Close the MCP connection cleanly

    async def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any]
    ) -> Any:

        result = await self.session.call_tool(
            name,
            arguments
        )  # Call the named tool with the provided arguments

        return result  # Return the result from the tool call

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
        ]  # Start the conversation with a system message and the user's question

        while True:

            response = ollama.chat(
                model=OLLAMA_MODEL,
                messages=messages,
                tools=self.ollama_tools,
            )  # Send the conversation and tool list to Ollama for the next step

            assistant_message = response["message"]  # Get the model's response message

            tool_calls = assistant_message.get("tool_calls", [])  # Check if the model wants to call any tools

            if not tool_calls:
                return assistant_message["content"]  # If there are no tool calls, return the final answer

            messages.append(assistant_message)  # Save the assistant message in the conversation history

            for call in tool_calls:

                fn_name = call["function"]["name"]  # Get the name of the tool to call

                args = call["function"].get(
                    "arguments",
                    {}
                )  # Get the arguments for the tool, or use an empty dict if none

                print(f"\nCalling tool: {fn_name}")
                print(json.dumps(args, indent=2))  # Print the tool call and its arguments for debugging

                try:
                    tool_result = await self.call_tool(
                        fn_name,
                        args,
                    )  # Call the requested tool and wait for its result

                    content = json.dumps(
                        tool_result.model_dump()
                        if hasattr(tool_result, "model_dump")
                        else str(tool_result),
                        default=str,
                    )  # Convert the tool result to a JSON string

                except Exception as e:
                    content = json.dumps(
                        {"error": str(e)}
                    )  # If the call fails, store the error message instead

                messages.append(
                    {
                        "role": "tool",
                        "tool_name": fn_name,
                        "content": content,
                    }
                )  # Add the tool output back into the conversation before looping again


async def main():

    agent = MCPAgent()  # Create the agent object

    await agent.connect()  # Connect the agent to MCP and load tool information

    try:

        while True:

            question = input("\nQuestion > ")  # Ask the user for a question

            if question.lower() in (
                "quit",
                "exit",
            ):
                break  # Stop asking questions if the user types quit or exit

            answer = await agent.run(question)  # Send the question to the agent and get the answer

            print("\nAnswer:")
            print(answer)  # Print the answer returned by the agent

    finally:
        await agent.close()  # Always close the connection to clean up resources


if __name__ == "__main__":
    asyncio.run(main())  # Run the main function when this file is executed directly
