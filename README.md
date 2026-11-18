# Windows Desktop for Codex

[简体中文](README.zh-CN.md) · [Download for Windows](https://github.com/nuodeng33/windows-desktop-mcp/releases/latest) · [Quick install](#install-in-codex)

Give Codex a job in a Windows desktop app.

> “Enter customer ID C-1042 in the order form, save it, and tell me what the status says.”

Keep writing your notes. Codex fills the field and presses Save through the form’s Windows accessibility controls, even with your notes covering the form. **Your mouse stays in your hands.**

![Illustrated example showing a user typing notes while Codex fills a background form](docs/background-demo.svg)

## What to try

| When you have… | Ask Codex to… |
| --- | --- |
| A WinForms data-entry tool open behind another window | Enter a value, submit the form, and read the confirmation back. |
| A WPF settings dialog or an Electron app | Open a menu, choose an option, and check which item is selected. |
| A custom canvas | Inspect just that window. Enable foreground mouse input when you want Codex to click or drag something on the canvas. |

## Install in Codex

Use Windows 11 x64 and a Codex version with the `codex plugin` command. The plugin bundles a local MCP server and a skill.

**From a release.** Download and extract `windows-desktop-mcp-<version>-windows-x64.zip`. The ZIP includes the runtime. Open PowerShell in the extracted directory containing `.agents` and `plugins`, then run the two commands below. [Latest release](https://github.com/nuodeng33/windows-desktop-mcp/releases/latest)

```powershell
codex plugin marketplace add (Get-Location).Path
codex plugin add windows-desktop@windows-desktop-tools
```

**From source.** Open PowerShell in the repository root. Prepare the pinned Windows x64 runtime before registering the marketplace.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1
codex plugin marketplace add (Get-Location).Path
codex plugin add windows-desktop@windows-desktop-tools
```

Open a new Codex chat. Give Codex the title of an open desktop window and tell it what to fill in, click, or read.

## MCP tool reference

| Tool | What it does |
| --- | --- |
| `list_windows` | Lists open windows and returns their window handles and process IDs. |
| `get_tree` | Reads accessibility controls. Query a subtree by name or AutomationId, or compare it with a previous observation to see what changed. |
| `perform_action` | Sets a value, invokes a button, selects an item, toggles, expands, collapses, or scrolls. Read back the control or status afterward to verify the result. |
| `begin_task` / `end_task` | Opens or closes a session for one window, with separate options for capture and input. |
| `capture_window` | Returns a PNG of the selected window, available accessibility labels, and a capture ID. Pixel coordinates start at the top left of the PNG. |
| `window_input` | Clicks, drags, types, sends keys, or scrolls. Coordinate actions use a fresh capture ID. |

The MCP client receives the PNG and can pass it to its model. Capture depends on Windows being able to render the target window. Restore a minimized window before requesting its image.

### Use with another MCP client

The server uses stdio. After extracting the release or preparing the source runtime, adapt this example to your client's MCP configuration. Replace `C:\Tools\windows-desktop-mcp` with the absolute path to the directory that contains `plugins`.

```json
{
  "mcpServers": {
    "windows-uia-background": {
      "command": "C:\\Tools\\windows-desktop-mcp\\plugins\\windows-desktop\\runtime\\python.exe",
      "args": [
        "-B",
        "-I",
        "C:\\Tools\\windows-desktop-mcp\\plugins\\windows-desktop\\app\\server.py"
      ]
    }
  }
}
```

## Development

The server is in `plugins/windows-desktop/app/`. The Codex skill is in `plugins/windows-desktop/skills/`.

After preparing the runtime, run the native tests in order on an interactive Windows desktop. Use Python 3.11 or newer with Pillow for the WPF and canvas suite.

```powershell
py -3 tests/test_integration.py
py -3 tests/test_native_extended.py
```

Build the offline ZIP and its SHA-256 file in `dist/`.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\package-offline.ps1
```

Use the command below to uninstall the Codex plugin.

```powershell
codex plugin remove windows-desktop@windows-desktop-tools
```

## License

The project uses the MIT License. CPython, Cua Driver, and their dependencies retain their own licenses. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY.md).
