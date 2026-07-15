"""Desktop client for an Ollama agent using tools from a Zapier MCP server."""

import asyncio
import importlib.util
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict


REQUIRED_PACKAGES = {
    "ollama": "ollama",
    "ollmcp": "ollmcp",
    "mcp": "mcp",
}
OLLAMA_MODEL = "qwen3.5:35b"
OLLAMA_HOST = "http://localhost:11434"


def ensure_packages() -> None:
    """Install the Python dependencies when this script is started directly."""
    missing_packages = [
        package
        for module, package in REQUIRED_PACKAGES.items()
        if importlib.util.find_spec(module) is None
    ]
    if missing_packages:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing_packages])


ensure_packages()

import tkinter as tk
from tkinter import scrolledtext, ttk

from ollama import Client
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class MCPAgent:
    def __init__(self, mcp_url: str, activity_callback=None):
        self.mcp_url = mcp_url
        self.activity_callback = activity_callback or (lambda _: None)
        self.client = Client(host=OLLAMA_HOST)
        self.tool_map: Dict[str, Any] = {}
        self.ollama_tools = []
        self.http_ctx = None
        self.session = None

    async def connect(self) -> None:
        self.activity_callback("Connecting to Zapier MCP server...")
        self.http_ctx = streamablehttp_client(self.mcp_url)
        read_stream, write_stream, _ = await self.http_ctx.__aenter__()
        self.session = ClientSession(read_stream, write_stream)
        await self.session.initialize()

        tools_response = await self.session.list_tools()
        for tool in tools_response.tools:
            self.tool_map[tool.name] = tool
            self.ollama_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.inputSchema,
                    },
                }
            )

        tool_names = ", ".join(self.tool_map) or "no tools"
        self.activity_callback(f"Connected. Available Zapier tools: {tool_names}")

    async def close(self) -> None:
        if self.http_ctx is not None:
            await self.http_ctx.__aexit__(None, None, None)
            self.http_ctx = None

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        if self.session is None:
            raise RuntimeError("MCP session is not connected.")
        return await self.session.call_tool(name, arguments)

    async def run(self, conversation: list[Dict[str, str]]) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful Zapier automation assistant. You can use the "
                    "available Zapier MCP tools to inspect and perform actions in the "
                    "user's connected apps. Use a tool whenever it is necessary, explain "
                    "important results clearly, and ask for clarification before making "
                    "an irreversible external change."
                ),
            },
            *conversation,
        ]

        while True:
            response = self.client.chat(
                model=OLLAMA_MODEL, messages=messages, tools=self.ollama_tools
            )
            assistant_message = response["message"]
            tool_calls = assistant_message.get("tool_calls", [])
            if not tool_calls:
                return assistant_message.get("content", "")

            messages.append(assistant_message)
            for call in tool_calls:
                function = call["function"]
                tool_name = function["name"]
                arguments = function.get("arguments", {})
                self.activity_callback(f"Calling Zapier tool: {tool_name}")
                try:
                    tool_result = await self.call_tool(tool_name, arguments)
                    content = json.dumps(
                        tool_result.model_dump()
                        if hasattr(tool_result, "model_dump")
                        else str(tool_result),
                        default=str,
                    )
                except Exception as error:
                    content = json.dumps({"error": str(error)})

                messages.append(
                    {"role": "tool", "tool_name": tool_name, "content": content}
                )


class ZapierAgentApp(tk.Tk):
    def __init__(self, mcp_url: str):
        super().__init__()
        self.mcp_url = mcp_url
        self.title("Zapier Discussion")
        self.minsize(760, 560)
        self.geometry("900x680")
        self.conversation: list[Dict[str, str]] = []
        self._configure_ollmcp_theme()
        self._build_ui()

    def _configure_ollmcp_theme(self) -> None:
        colors = {
            "ink": "#10151f",
            "surface": "#18212f",
            "cyan": "#5eead4",
            "amber": "#fbbf24",
            "text": "#e5edf5",
            "muted": "#a4b1c1",
        }
        self.configure(background=colors["ink"])
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "OllMCP.TButton",
            background=colors["cyan"],
            foreground=colors["ink"],
            borderwidth=0,
            font=("Segoe UI Semibold", 10),
            padding=(16, 10),
        )
        style.map(
            "OllMCP.TButton",
            background=[("active", colors["amber"]), ("disabled", colors["surface"])],
            foreground=[("disabled", colors["muted"])],
        )
        self.colors = colors

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.transcript = scrolledtext.ScrolledText(
            self,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Segoe UI", 11),
            background=self.colors["surface"],
            foreground=self.colors["text"],
            insertbackground=self.colors["text"],
            relief=tk.FLAT,
            borderwidth=0,
            padx=18,
            pady=18,
        )
        self.transcript.tag_configure("user", foreground=self.colors["cyan"], font=("Segoe UI Semibold", 10))
        self.transcript.tag_configure("agent", foreground=self.colors["amber"], font=("Segoe UI Semibold", 10))
        self.transcript.tag_configure("body", foreground=self.colors["text"], spacing3=16)
        self.transcript.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 8))

        prompt_frame = tk.Frame(self, background=self.colors["ink"], padx=14, pady=14)
        prompt_frame.grid(row=1, column=0, sticky="ew")
        prompt_frame.columnconfigure(0, weight=1)
        self.prompt = tk.Text(
            prompt_frame,
            height=3,
            wrap=tk.WORD,
            font=("Segoe UI", 11),
            background=self.colors["surface"],
            foreground=self.colors["text"],
            insertbackground=self.colors["text"],
            relief=tk.FLAT,
            padx=12,
            pady=10,
        )
        self.prompt.grid(row=0, column=0, sticky="ew")
        self.prompt.bind("<Control-Return>", self._submit_from_shortcut)
        self.send_button = ttk.Button(
            prompt_frame, text="Send", style="OllMCP.TButton", command=self._submit
        )
        self.send_button.grid(row=0, column=1, sticky="ns", padx=(8, 0))

    def _submit_from_shortcut(self, _event):
        self._submit()
        return "break"

    def _submit(self) -> None:
        question = self.prompt.get("1.0", tk.END).strip()
        if not question:
            return

        self.prompt.delete("1.0", tk.END)
        self.conversation.append({"role": "user", "content": question})
        self._append("You", question)
        self.send_button.configure(state=tk.DISABLED)
        threading.Thread(
            target=self._run_agent, args=(self.conversation.copy(),), daemon=True
        ).start()

    def _run_agent(self, conversation: list[Dict[str, str]]) -> None:
        async def execute() -> str:
            agent = MCPAgent(self.mcp_url)
            try:
                await agent.connect()
                return await agent.run(conversation)
            finally:
                await agent.close()

        try:
            answer = asyncio.run(execute())
            self.after(0, self._append_answer, answer)
        except Exception as error:
            self.after(0, self._append, "Error", str(error))
        finally:
            self.after(0, self.send_button.configure, {"state": tk.NORMAL})

    def _append(self, speaker: str, text: str) -> None:
        self.transcript.configure(state=tk.NORMAL)
        tag = "user" if speaker == "You" else "agent"
        self.transcript.insert(tk.END, f"{speaker}\n", tag)
        self.transcript.insert(tk.END, f"{text}\n\n", "body")
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _append_answer(self, answer: str) -> None:
        self.conversation.append({"role": "assistant", "content": answer})
        self._append("Agent", answer)


def _run_ollmcp_login(mcp_url: str) -> None:
    print("\nOpening OllMCP for Zapier sign-in. Complete any browser login, then exit OllMCP to continue.")
    ollmcp_executable = Path(sys.executable).with_name("ollmcp.exe")
    try:
        subprocess.run(
            [str(ollmcp_executable), "--mcp-server-url", mcp_url, "--model", OLLAMA_MODEL],
            check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError("OllMCP is not installed or is unavailable on PATH.") from error


def _connect_before_launch(mcp_url: str) -> None:
    async def verify() -> None:
        agent = MCPAgent(mcp_url)
        try:
            await agent.connect()
        finally:
            await agent.close()

    asyncio.run(verify())


def bootstrap() -> str:
    print("Zapier MCP setup")
    mcp_url = input("Paste your Zapier MCP connection URL: ").strip()
    if not mcp_url:
        raise RuntimeError("A Zapier MCP connection URL is required.")
    _run_ollmcp_login(mcp_url)
    print("\nVerifying the Zapier MCP connection...")
    _connect_before_launch(mcp_url)
    print("Connected. Opening the Zapier discussion window.")
    return mcp_url


if __name__ == "__main__":
    try:
        ZapierAgentApp(bootstrap()).mainloop()
    except Exception as error:
        print(f"Unable to connect to Zapier MCP: {error}", file=sys.stderr)
        sys.exit(1)