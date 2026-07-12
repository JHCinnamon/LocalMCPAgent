import asyncio
import json

from ollama import Client

from config import *
from models import Plan
from prompts import *
from ollmcp_client import MCPExecutor


ollama = Client(host=OLLAMA_HOST)


class Orchestrator:

    def __init__(self):

        self.mcp = MCPExecutor(MCP_URL)

    def create_plan(self, request: str) -> Plan:

        response = ollama.chat(
            model=LLAMA_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": PLANNER_PROMPT + "\n\n" + request,
                },
            ],
            format="json",
        )

        return Plan.model_validate_json(
            response["message"]["content"]
        )

    async def execute(self, request):

        plan = self.create_plan(request)

        print("Goal:", plan.goal)

        print()

        for i, step in enumerate(plan.steps, start=1):

            print(f"STEP {i}: {step}")

        if not plan.requires_tools:

            return {
                "plan": plan,
                "result": "No external actions required.",
            }

        instruction = f"""
Goal:
{plan.goal}

Execution Plan:

{chr(10).join(plan.steps)}

Carry out this plan using available MCP tools.
"""

        result = await self.mcp.execute(instruction)

        return {
            "plan": plan,
            "result": result,
        }


async def main():

    orchestrator = Orchestrator()

    result = await orchestrator.execute(
        """
        Email my manager tomorrow's meeting agenda.

        Then create a Trello task reminding me to
        prepare the slides.

        Finally notify the engineering Slack channel.
        """
    )

    print(result)


if __name__ == "__main__":
    asyncio.run(main())