"""Desktop client for an Ollama agent using tools from a Zapier MCP server."""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Dict


REQUIRED_PACKAGES = {
    "ollama": "ollama",
    "ollmcp": "ollmcp",
    "mcp": "mcp",
    "cryptography": "cryptography",
    "keyring": "keyring",
}
OLLAMA_MODEL = "qwen3.5:35b"
OLLAMA_HOST = "http://localhost:11434"
ZAPIER_MCP_PORTAL = "https://mcp.zapier.com/"
ZAPIER_MCP_URL = "https://mcp.zapier.com/api/v1/connect"
DEFAULT_MCP_URL = ZAPIER_MCP_URL


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
from tkinter import messagebox, scrolledtext, ttk

from ollama import Client
from cryptography.fernet import Fernet, InvalidToken
import keyring
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class EncryptedCredentialStore:
    """Stores replaceable named credentials encrypted with an OS-protected key."""

    SERVICE_NAME = "ZapierMCPAgent"
    KEY_NAME = "credential-encryption-key"

    def __init__(self, storage_path: Path | None = None):
        app_data = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        self.storage_path = storage_path or app_data / self.SERVICE_NAME / "credentials.enc"
        self.cipher = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        key = keyring.get_password(self.SERVICE_NAME, self.KEY_NAME)
        if key is None:
            key = Fernet.generate_key().decode("ascii")
            keyring.set_password(self.SERVICE_NAME, self.KEY_NAME, key)
        return key.encode("ascii")

    def load(self, credential_name: str) -> Dict[str, str]:
        records = self._load_records()
        return records.get(credential_name, {}).copy()

    def replace(self, credential_name: str, url: str, token: str) -> None:
        records = self._load_records()
        records[credential_name] = {"url": url.strip(), "token": token.strip()}
        self._save_records(records)

    def _load_records(self) -> Dict[str, Dict[str, str]]:
        if not self.storage_path.exists():
            return {}
        try:
            encrypted_payload = self.storage_path.read_bytes()
            return json.loads(self.cipher.decrypt(encrypted_payload))
        except (InvalidToken, OSError, json.JSONDecodeError) as error:
            raise RuntimeError("Saved credentials could not be decrypted.") from error

    def _save_records(self, records: Dict[str, Dict[str, str]]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        encrypted_payload = self.cipher.encrypt(json.dumps(records).encode("utf-8"))
        temporary_path = self.storage_path.with_suffix(".tmp")
        temporary_path.write_bytes(encrypted_payload)
        temporary_path.replace(self.storage_path)


class MCPAgent:
    def __init__(self, mcp_url: str, access_token: str, activity_callback=None):
        self.mcp_url = mcp_url
        self.access_token = access_token
        self.activity_callback = activity_callback or (lambda _: None)
        self.client = Client(host=OLLAMA_HOST)
        self.tool_map: Dict[str, Any] = {}
        self.ollama_tools = []
        self.http_ctx = None
        self.session = None

    async def connect(self) -> None:
        self.activity_callback("Connecting to Zapier MCP server...")
        authorization = self.access_token
        if authorization and not authorization.lower().startswith("bearer "):
            authorization = f"Bearer {authorization}"
        headers = {"Authorization": authorization} if authorization else None
        self.http_ctx = streamablehttp_client(self.mcp_url, headers=headers)
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

    async def run(self, user_question: str) -> str:
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
            {"role": "user", "content": user_question},
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
    def __init__(self):
        super().__init__()
        self.title("Zapier MCP Agent")
        self.minsize(760, 560)
        self.geometry("900x680")
        self.credential_store = EncryptedCredentialStore()
        saved_credential = self.credential_store.load("zapier")
        self.endpoint_var = tk.StringVar(value=DEFAULT_MCP_URL)
        self.token_var = tk.StringVar(value=saved_credential.get("token", ""))
        self.status_var = tk.StringVar(value="Checking Ollama...")
        self._build_ui()
        threading.Thread(target=self._check_ollama, daemon=True).start()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        connection_frame = ttk.LabelFrame(self, text="Zapier MCP Connection", padding=12)
        connection_frame.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        connection_frame.columnconfigure(1, weight=1)
        ttk.Label(connection_frame, text="MCP endpoint:").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.endpoint_entry = ttk.Entry(connection_frame, textvariable=self.endpoint_var)
        self.endpoint_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(
            connection_frame, text="Log in to Zapier", command=self._open_zapier_login
        ).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(
            connection_frame,
            text="Uses Zapier's streamable HTTP connection URL. Enter your secret token below.",
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(7, 0))
        ttk.Label(connection_frame, text="Access token:").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0)
        )
        self.token_entry = ttk.Entry(
            connection_frame, textvariable=self.token_var, show="*"
        )
        self.token_entry.grid(row=2, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(
            connection_frame, text="Save encrypted", command=self._save_credential
        ).grid(row=2, column=2, padx=(8, 0), pady=(8, 0))

        status_frame = ttk.Frame(self, padding=(16, 0))
        status_frame.grid(row=1, column=0, sticky="ew")
        ttk.Label(status_frame, text="Model:").pack(side="left")
        ttk.Label(status_frame, text=OLLAMA_MODEL).pack(side="left", padx=(5, 20))
        ttk.Label(status_frame, textvariable=self.status_var).pack(side="left")

        self.transcript = scrolledtext.ScrolledText(
            self, wrap=tk.WORD, state=tk.DISABLED, font=("Segoe UI", 10)
        )
        self.transcript.grid(row=2, column=0, sticky="nsew", padx=14, pady=8)

        prompt_frame = ttk.Frame(self, padding=(14, 0, 14, 14))
        prompt_frame.grid(row=3, column=0, sticky="ew")
        prompt_frame.columnconfigure(0, weight=1)
        self.prompt = tk.Text(prompt_frame, height=4, wrap=tk.WORD, font=("Segoe UI", 10))
        self.prompt.grid(row=0, column=0, sticky="ew")
        self.prompt.bind("<Control-Return>", self._submit_from_shortcut)
        self.send_button = ttk.Button(prompt_frame, text="Send", command=self._submit)
        self.send_button.grid(row=0, column=1, sticky="ns", padx=(8, 0))

    def _open_zapier_login(self) -> None:
        webbrowser.open(ZAPIER_MCP_PORTAL)
        self.status_var.set("Browser opened. Sign in to Zapier and create or copy a secret token.")

    def _save_credential(self) -> None:
        endpoint = self.endpoint_var.get().strip()
        token = self.token_var.get().strip()
        if not endpoint or not token:
            messagebox.showwarning(
                "URL and token required",
                "Enter both the Zapier MCP endpoint and its access token before saving.",
            )
            return
        try:
            self.credential_store.replace("zapier", endpoint, token)
            self.status_var.set("Zapier credentials saved with encryption")
        except Exception as error:
            messagebox.showerror("Credential storage failed", str(error))

    def _check_ollama(self) -> None:
        client = Client(host=OLLAMA_HOST)
        try:
            response = client.list()
            models = response.models if hasattr(response, "models") else response.get("models", [])
            model_names = {
                model.model if hasattr(model, "model") else model.get("model", "")
                for model in models
            }
            status = "Ollama is ready" if OLLAMA_MODEL in model_names else f"Run: ollama pull {OLLAMA_MODEL}"
        except Exception:
            status = "Ollama is unavailable. Start it with: ollama serve"
        self.after(0, self.status_var.set, status)

    def _submit_from_shortcut(self, _event):
        self._submit()
        return "break"

    def _submit(self) -> None:
        question = self.prompt.get("1.0", tk.END).strip()
        endpoint = self.endpoint_var.get().strip()
        token = self.token_var.get().strip()
        if not question:
            return
        if not endpoint:
            messagebox.showwarning(
                "Zapier MCP endpoint required",
                "Enter the Zapier streamable HTTP URL before sending.",
            )
            return
        if not token:
            messagebox.showwarning(
                "Zapier access token required",
                "Enter the access token for this Zapier MCP endpoint before sending.",
            )
            return

        self.prompt.delete("1.0", tk.END)
        self._append("You", question)
        self.send_button.configure(state=tk.DISABLED)
        self.status_var.set("Working...")
        threading.Thread(
            target=self._run_agent, args=(endpoint, token, question), daemon=True
        ).start()

    def _run_agent(self, endpoint: str, token: str, question: str) -> None:
        async def execute() -> str:
            agent = MCPAgent(endpoint, token, self._set_status_threadsafe)
            try:
                await agent.connect()
                return await agent.run(question)
            finally:
                await agent.close()

        try:
            answer = asyncio.run(execute())
            self.after(0, self._append, "Agent", answer)
            self.after(0, self.status_var.set, "Ready")
        except Exception as error:
            self.after(0, self._append, "Error", str(error))
            self.after(0, self.status_var.set, "Connection or tool request failed")
        finally:
            self.after(0, self.send_button.configure, {"state": tk.NORMAL})

    def _set_status_threadsafe(self, status: str) -> None:
        self.after(0, self.status_var.set, status)

    def _append(self, speaker: str, text: str) -> None:
        self.transcript.configure(state=tk.NORMAL)
        self.transcript.insert(tk.END, f"{speaker}:\n{text}\n\n")
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)


if __name__ == "__main__":
    ZapierAgentApp().mainloop()