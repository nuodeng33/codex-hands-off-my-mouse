---
name: windows-uia-background
description: 在 Windows 里读取和操作指定桌面软件。优先后台控件，在任务允许时识别单个窗口或前台操作自绘画布。
---

浏览器网页优先使用浏览器 DOM。Windows 桌面任务先用 list_windows 确认目标 HWND 和 PID，再用 get_tree 读取控件，通过 perform_action 的 invoke、select、toggle、expand、collapse、set_value 或 scroll 完成操作。使用最近一次读树返回的节点 ID。操作后读回状态，例如按钮旁的保存结果、菜单的展开状态或选中项。普通后台任务走这三个工具即可。

大窗口可用 root_automation_id 或 root_name 定位唯一子树。要获取变化，传入上一次同窗口同范围读树的 observation_id 作为 diff_from。变化节点有新的可操作 ID。需要操作一个未变化的节点时重新读完整子树。unobserved 表示某些变化无法判断。

找不到画布、图标时，按用户在本次任务中给出的范围使用 begin_task。用户允许查看这个窗口时设置 allow_capture=true，使用 capture_window 取得 PNG 和对应控件标签。先向用户说明任何所需的前台键鼠使用，已有本次授权可直接执行。只有本次允许前台操作时设置 allow_foreground=true，并对 window_input 显式传 mode=foreground。会话默认值和 window_input 默认模式都是后台。驱动可能通过程序自身行为引起焦点变化，后台动作报告 foreground_changed 或 cursor_changed 时停下并报告。

图片坐标以返回 PNG 左上角为原点，使用同次截图的 capture_id，拖拽另给终点 to_x、to_y。每次输入后重新观察。前台操作开始后切到其它窗口会停止后续输入。明确未投递的控件动作可在授权范围内用画面重新定位，再单独调用 window_input。投递结果未知时先读回现状。任务结束调用 end_task。

截图可能包含目标程序显示的内容。看图使用当前支持图片的模型。窗口无法单独渲染时说明当前限制。
