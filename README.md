# Zapier MCP Agent

A Windows desktop application that uses a local Ollama model to answer prompts and invoke tools exposed by Zapier's remote MCP server.

## Components

- **Tkinter desktop UI**: collects a prompt, displays connection and tool activity, and shows the final agent response.
- **Ollama**: runs the local `qwen3.5:35b` model at `http://localhost:11434`.
- **MCP client**: connects through streamable HTTP to Zapier at `https://mcp.zapier.com/api/v1/connect`, discovers its tools, and calls tools selected by the model.
- **Zapier authentication**: sends the secret token as `Authorization: Bearer <token>`.
- **Encrypted credential store**: encrypts saved URL/token records with Fernet. The encrypted payload is stored under `%LOCALAPPDATA%\ZapierMCPAgent\credentials.enc`; its encryption key is held separately by Windows Credential Manager through `keyring`.

## Prerequisites

1. Install [Ollama](https://ollama.com/) for Windows.
2. Install Python 3.12 or a compatible Python version with Tk support.
3. Have a Zapier account and generate a Zapier MCP secret token.

## Setup

Pull the model required by the application:

```powershell
ollama pull qwen3.5:35b
```

Start Ollama if it is not already running:

```powershell
ollama serve
```

The application checks for and installs its Python packages (`ollama`, `ollmcp`, `mcp`, `cryptography`, and `keyring`) on first launch. To install them yourself instead, run:

```powershell
python -m pip install ollama ollmcp mcp cryptography keyring
```

## Run

From this directory, start the app:

```powershell
python "[Template] Agentic MCP Outline.py"
```

## Use

1. Select **Log in to Zapier** and sign in in the browser.
2. Create or copy a Zapier MCP secret token.
3. Leave the MCP endpoint set to `https://mcp.zapier.com/api/v1/connect`.
4. Paste the token into **Access token**.
5. Select **Save encrypted** to store the token securely for later runs.
6. Enter a request in the prompt area and select **Send**. The agent connects to Zapier, lists the available tools, calls tools as needed, and displays its answer.

The app uses a saved token automatically on later launches. Entering a replacement token and selecting **Save encrypted** replaces the existing `zapier` credential record.

## Troubleshooting

- If the status says Ollama is unavailable, run `ollama serve` and verify that port `11434` is available.
- If the status says to pull the model, run `ollama pull qwen3.5:35b`.
- If Zapier connection or tool calls fail, confirm the secret token is current and that it has access to the Zapier MCP tools you expect.
