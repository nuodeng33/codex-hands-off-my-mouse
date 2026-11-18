# Windows Desktop for Codex

A local Windows 11 x64 plugin that lets Codex operate a particular desktop window. It reads Windows accessibility controls, can capture one window for a vision model, and can send foreground input when the task calls for it. The plugin bundles one MCP server and a Skill.

## 安装

从离线包解压后，在包含 `.agents` 和 `plugins` 的目录打开 PowerShell。需要支持 `codex plugin` 的 Codex 版本。

```powershell
codex plugin marketplace add "$((Get-Location).Path)"
codex plugin add windows-desktop@windows-desktop-tools
```

打开新会话，即可使用 Windows Desktop 插件。可以说“后台在测试窗口中填入这行字，点保存，读回结果”，或者“可以看这个画布，并在这个窗口用鼠标把图块拖到右边”。

如果使用 Git 源码，先在仓库根目录运行下面的脚本。它会准备固定版本的 Windows x64 运行时，之后执行上面的两条插件安装命令。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-runtime.ps1
```

## 功能

| 工具 | 作用 |
|---|---|
| `list_windows` | 找到目标窗口句柄及其进程。 |
| `get_tree` | 读取窗口或指定子树，支持按控件名、AutomationId 筛选及相邻观测差异。 |
| `perform_action` | 调用控件、设值、选择、展开、折叠、切换和滚动。操作后可读回实际状态。 |
| `begin_task` / `end_task` | 将识图和前台输入权限分别限定在本次任务的目标窗口。 |
| `capture_window` | 返回窗口 PNG 和定位标签。坐标使用同次截图标识。 |
| `window_input` | 在授权范围内点击、拖拽、输入文字、发送按键或滚动。 |

后台控件路径默认不截图，不移动物理鼠标。少数应用调用无障碍控件时会自行切换焦点，插件报告观测到的变化。浏览器网页优先使用浏览器 DOM。前台输入会占用真实键鼠，已开始操作后若发现用户切换窗口便停止后续输入。

窗口图像交给当前 MCP 客户端和它使用的模型。最小化、受保护以及无法单独渲染的窗口可能无法截图。驱动投递成功后，应用是否保存、选中或切换，需要从界面或应用状态读回确认。

## 开发与测试

应用源码在 `plugins/windows-desktop/app/`，Skill 在插件目录的 `skills/`。MCP 兼容接口名为 `windows-uia-background`。原生测试使用 Windows 交互桌面，按顺序运行。WPF 和画布测试需要开发用 Python 3.11 或更高版本及 Pillow。

```powershell
py -3 tests/test_integration.py
py -3 tests/test_native_extended.py
```

生成包含运行时的离线插件包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\package-offline.ps1
```

卸载插件可运行 `codex plugin remove windows-desktop@windows-desktop-tools`。老版手工 MCP 注册与这个插件共存时，同一服务可能出现两次。迁移前请备份自己的手工 MCP 配置和独立 Skill。

项目代码采用 MIT 许可证。CPython、Cua Driver 及其依赖保留各自的许可。见 [LICENSE](LICENSE) 和 [THIRD_PARTY.md](THIRD_PARTY.md)。

