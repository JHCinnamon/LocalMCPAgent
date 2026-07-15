# Zapier MCP Discussion

A Windows desktop chat application that uses a local Ollama model to discuss and invoke tools exposed by a Zapier remote MCP server. The desktop UI is deliberately limited to the conversation history and message composer.

## Components

- **Tkinter desktop UI**: shows the Zapier discussion history and a message composer after the server connection succeeds.
- **Ollama**: runs the local `qwen3.5:35b` model at `http://localhost:11434`.
- **MCP client**: connects through streamable HTTP to Zapier at `https://mcp.zapier.com/api/v1/connect`, discovers its tools, and calls tools selected by the model.
- **OllMCP login**: launches the installed `ollmcp` CLI against the supplied Zapier URL so the user can complete Zapier authentication before the desktop UI opens.

## Prerequisites

1. Install [Ollama](https://ollama.com/) for Windows.
2. Install Python 3.12 or a compatible Python version with Tk support.
3. Have a Zapier account and its MCP connection URL.

## Setup

Pull the model required by the application:

```powershell
ollama pull qwen3.5:35b
```

Start Ollama if it is not already running:

```powershell
ollama serve
```

The application checks for and installs its Python packages (`ollama`, `ollmcp`, and `mcp`) on first launch. To install them yourself instead, run:

```powershell
python -m pip install -r requirements.txt
```

## Run

From this directory, start the app:

```powershell
python "[Template] Agentic MCP Outline.py"
```

## Use

1. At the terminal prompt, paste the Zapier MCP connection URL.
2. OllMCP opens against that server. Complete the Zapier sign-in flow, then exit OllMCP to return to the launcher.
3. The launcher verifies the Zapier connection. It opens the discussion window only after the server has connected successfully.
4. Enter a request in the composer and select **Send**. The agent reconnects to Zapier for that request, lists the available tools, calls tools as needed, and displays its answer.

## Troubleshooting

- If the status says Ollama is unavailable, run `ollama serve` and verify that port `11434` is available.
- If the status says to pull the model, run `ollama pull qwen3.5:35b`.
- If Zapier connection or tool calls fail, rerun the application, complete the OllMCP sign-in flow, and confirm the supplied MCP URL has access to the Zapier tools you expect.
