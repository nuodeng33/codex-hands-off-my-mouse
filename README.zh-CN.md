# Windows Desktop for Codex

[English](README.md) · [下载 Windows 版](https://github.com/nuodeng33/windows-desktop-mcp/releases/latest) · [快速安装](#安装到-codex)

把 Windows 软件里的一件事交给 Codex。

> “帮我在订单窗口填入客户编号 C-1042，点保存，告诉我状态栏写了什么。”

你可以留在笔记窗口继续写。即使订单窗口被盖住，Codex 也能通过它的无障碍控件填值、按按钮、读回结果。**这期间鼠标一直归你用。**

![操作示意：用户在前台写笔记，Codex 同时在后台填写表单](docs/background-demo.svg)

## 推荐用在哪

| 手头的工作 | 可以交给 Codex 的操作 |
| --- | --- |
| 在 WinForms 业务软件里录入数据 | 填字段、提交表单，把保存结果读给你。 |
| 调整 WPF 或 Electron 应用的设置 | 展开菜单、选中选项，再确认当前选中的是哪一项。 |
| 操作自绘画布 | 单独查看这个窗口的画面；需要点击或拖拽时，切换到前台鼠标模式。 |

## 安装到 Codex

需要 Windows 11 x64 和支持 `codex plugin` 命令的 Codex 版本。插件内含本地 MCP 服务和桌面操作 Skill。

**从发布包安装。** 下载并解压 `windows-desktop-mcp-<版本>-windows-x64.zip`。ZIP 自带运行时。在包含 `.agents` 和 `plugins` 的解压目录打开 PowerShell，执行下面两条命令。 [最新发布](https://github.com/nuodeng33/windows-desktop-mcp/releases/latest)

```powershell
codex plugin marketplace add (Get-Location).Path
codex plugin add windows-desktop@windows-desktop-tools
```

**从源码安装。** 在仓库根目录打开 PowerShell，先准备固定版本的 Windows x64 运行时，再注册插件市场并安装。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1
codex plugin marketplace add (Get-Location).Path
codex plugin add windows-desktop@windows-desktop-tools
```

打开新的 Codex 会话，告诉 Codex 已打开的窗口标题，以及要填入、点击或读取的内容。

## MCP 工具

| 工具 | 用途 |
| --- | --- |
| `list_windows` | 列出打开的窗口，返回窗口句柄和进程 ID。 |
| `get_tree` | 读取无障碍控件树。支持按控件名或 AutomationId 查询子树，也能和上一轮观察比较变化。 |
| `perform_action` | 填值、点击按钮、选择、切换、展开、折叠或滚动。操作后读回控件或状态以核对结果。 |
| `begin_task` / `end_task` | 开启或结束针对一个窗口的会话，分别设置截图与输入权限。 |
| `capture_window` | 返回指定窗口的 PNG、可用的无障碍标签和截图 ID。像素坐标以 PNG 左上角为原点。 |
| `window_input` | 点击、拖拽、输入文字、发送按键或滚动。坐标操作使用新的截图 ID。 |

PNG 会传给当前 MCP 客户端，客户端可交给模型查看。能否截图取决于 Windows 能否单独渲染目标窗口。窗口最小化时，先还原再截图。

### 接入其他 MCP 客户端

服务使用 stdio。解压发布包或准备好源码运行时后，按客户端的配置格式参考下面的 JSON。把 `C:\Tools\windows-desktop-mcp` 换成包含 `plugins` 的目录绝对路径。

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

## 开发

服务代码在 `plugins/windows-desktop/app/`，Codex Skill 在 `plugins/windows-desktop/skills/`。

准备好运行时后，在可交互的 Windows 桌面中按顺序运行原生测试。WPF 和画布测试使用 Python 3.11 或更新版本，并需要 Pillow。

```powershell
py -3 tests/test_integration.py
py -3 tests/test_native_extended.py
```

生成离线 ZIP 和对应的 SHA-256 文件，输出到 `dist/`。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\package-offline.ps1
```

卸载 Codex 插件。

```powershell
codex plugin remove windows-desktop@windows-desktop-tools
```

## 许可证

项目使用 MIT 许可证。CPython、Cua Driver 和它们的依赖保留各自的许可证。见 [LICENSE](LICENSE) 和[第三方声明](THIRD_PARTY.md)。
