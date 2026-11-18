$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
# PowerShell does not install WPF's default client-side Win32 provider table.
# Without it, ordinary Edit/Button HWNDs appear as generic Pane elements.
Add-Type -AssemblyName UIAutomationClientsideProviders
$null = [System.Windows.Automation.AutomationElement]::RootElement
[System.Windows.Automation.ClientSettings]::RegisterClientSideProviders(
    [UIAutomationClientsideProviders.UIAutomationClientSideProviders]::ClientSideProviderDescriptionTable)
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class UiaNative {
 [StructLayout(LayoutKind.Sequential)] public struct Point { public int X; public int Y; }
 [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool GetCursorPos(out Point p);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll")] public static extern IntPtr GetParent(IntPtr h);
 [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr h);
 [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)] public static extern IntPtr SendMessageTimeout(IntPtr h, uint msg, UIntPtr wp, IntPtr lp, uint flags, uint timeout, out UIntPtr result);
 [DllImport("user32.dll", EntryPoint="SendMessageTimeoutW", CharSet=CharSet.Unicode, SetLastError=true)] public static extern IntPtr SendTextTimeout(IntPtr h, uint msg, UIntPtr wp, string lp, uint flags, uint timeout, out UIntPtr result);
}
'@
$cache = @{}
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$A = [System.Windows.Automation.AutomationElement]
function Window([long]$hwnd, [long]$processId) {
    $h = [IntPtr]::new($hwnd); $actual = [uint32]0
    if (-not [UiaNative]::IsWindow($h)) { throw 'stale window' }
    [void][UiaNative]::GetWindowThreadProcessId($h, [ref]$actual)
    if ($actual -ne $processId) { throw 'stale window process' }
    return $A::FromHandle($h)
}
function Node($element, [int]$depth, $observation, $items, [int]$limit, [int]$maxDepth) {
    if ($items.Count -ge $limit) { return }
    $c = $element.Current
    $id = [guid]::NewGuid().ToString('N')
    $observation.nodes[$id] = $element
    $value = $null
    if (-not $c.IsPassword) {
        $v = $null
        if ($element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$v)) {
            $value = $v.Current.Value
            if ($value.Length -gt 4096) { $value = $value.Substring(0,4096) }
        }
    }
    $name = $c.Name
    if ($c.IsPassword) { $name = '[password control]' }
    if ($name.Length -gt 1024) { $name = $name.Substring(0,1024) }
    $patterns=@($element.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName })
    $rid=$null
    try { $parts=$element.GetRuntimeId(); if ($parts.Count) { $rid=$parts -join '.' } } catch {}
    $state=@{}
    if (-not $c.IsPassword) {
        foreach ($p in @('Toggle','ExpandCollapse','SelectionItem')) {
            if ($patterns -notcontains ($p + 'PatternIdentifiers.Pattern')) { continue }
            $v=$null
            try {
                switch ($p) {
                    'Toggle' { if ($element.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern,[ref]$v)) { $state.toggle=$v.Current.ToggleState.ToString() } }
                    'ExpandCollapse' { if ($element.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern,[ref]$v)) { $state.expansion=$v.Current.ExpandCollapseState.ToString() } }
                    'SelectionItem' { if ($element.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$v)) { $state.selected=$v.Current.IsSelected } }
                }
            } catch [System.Windows.Automation.ElementNotAvailableException] { throw }
        }
    }
    [void]$items.Add(@{ id=$id; runtime_key=$rid; state=$state; depth=$depth; name=$name; type=$c.ControlType.ProgrammaticName; automation_id=$c.AutomationId; enabled=$c.IsEnabled; password=$c.IsPassword; value=$value; patterns=$patterns; class_name=$c.ClassName; native_hwnd=[long]$c.NativeWindowHandle })
    if ($depth -ge $maxDepth) {
        if ($null -ne $walker.GetFirstChild($element)) { $observation.depthLimited=$true }
        return
    }
    $child = $walker.GetFirstChild($element)
    while ($null -ne $child -and $items.Count -lt $limit) {
        Node $child ($depth+1) $observation $items $limit $maxDepth
        $child = $walker.GetNextSibling($child)
    }
    if ($null -ne $child) { $observation.limitReached=$true }
}
function Execute($r) {
    switch ($r.op) {
        'windows' {
            $out = [System.Collections.ArrayList]::new()
            $child = $walker.GetFirstChild($A::RootElement)
            while ($null -ne $child -and $out.Count -lt 300) {
                $c=$child.Current
                if ($c.NativeWindowHandle -ne 0 -and $c.ProcessId -ne 0) {
                    [void]$out.Add(@{hwnd=[long]$c.NativeWindowHandle; pid=$c.ProcessId; name=$c.Name})
                }
                $child=$walker.GetNextSibling($child)
            }
            return @{windows=@($out)}
        }
        'anchors' {
            $prev=[UiaNative]::SetThreadDpiAwarenessContext([IntPtr]::new(-4))
            if ($prev -eq [IntPtr]::Zero) { throw 'window DPI context unavailable' }
            try {
                $root=Window $r.hwnd $r.pid
                $out=[System.Collections.ArrayList]::new()
                $todo=[System.Collections.Generic.Queue[object]]::new()
                $todo.Enqueue($root)
                $visited=0
                while ($todo.Count -gt 0 -and $visited -lt 160 -and $out.Count -lt 60) {
                    $e=$todo.Dequeue(); $visited++
                    $c=$e.Current
                    if ($c.ProcessId -ne $r.pid -or $c.IsPassword) { continue }
                    $rect=$c.BoundingRectangle
                    if ($e -ne $root -and $c.Name -and -not $c.IsOffscreen -and -not $rect.IsEmpty -and $rect.Width -gt 0 -and $rect.Height -gt 0) {
                        [void]$out.Add(@{name=$c.Name.Substring(0,[Math]::Min(160,$c.Name.Length));type=$c.ControlType.ProgrammaticName;
                                rect=@($rect.Left,$rect.Top,$rect.Right,$rect.Bottom)})
                    }
                    $child=$walker.GetFirstChild($e)
                    while ($null -ne $child -and ($visited+$todo.Count) -lt 160) { $todo.Enqueue($child); $child=$walker.GetNextSibling($child) }
                }
                return @{anchors=@($out)}
            } finally { [void][UiaNative]::SetThreadDpiAwarenessContext($prev) }
        }
        'tree' {
            $root=Window $r.hwnd $r.pid
            if ($null -ne $r.root_name -or $null -ne $r.root_automation_id) {
                $field='root_name'; $property=$A::NameProperty
                if ($null -ne $r.root_automation_id) { $field='root_automation_id'; $property=$A::AutomationIdProperty }
                $nameCondition=[System.Windows.Automation.PropertyCondition]::new($property,[string]$r.$field)
                $condition=[System.Windows.Automation.AndCondition]::new($nameCondition,[System.Windows.Automation.Automation]::ControlViewCondition)
                $matches=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
                if ($matches.Count -eq 0) { throw "$field not found" }
                if ($matches.Count -ne 1) { throw "$field ambiguous" }
                $root=$matches.Item(0)
            }
            $observation=@{hwnd=[long]$r.hwnd; pid=[long]$r.pid; nodes=@{}; depthLimited=$false; limitReached=$false}
            $items=[System.Collections.ArrayList]::new()
            $limit=[Math]::Min(300,[Math]::Max(1,[int]$r.limit)); $depth=[Math]::Min(32,[Math]::Max(0,[int]$r.depth))
            Node $root 0 $observation $items $limit $depth
            $oid=[guid]::NewGuid().ToString('N'); $cache.Clear(); $cache[$oid]=$observation
            return @{observation_id=$oid; nodes=@($items); truncated=($observation.limitReached -or $observation.depthLimited); depth_limited=$observation.depthLimited}
        }
        'action' {
            if (-not $cache.ContainsKey([string]$r.observation_id)) { throw 'stale observation' }
            $o=$cache[[string]$r.observation_id]
            if ($o.hwnd -ne [long]$r.hwnd -or $o.pid -ne [long]$r.pid) { throw 'window mismatch' }
            $root=Window $o.hwnd $o.pid
            if (-not $o.nodes.ContainsKey([string]$r.node_id)) { throw 'unknown node' }
            $el=$o.nodes[[string]$r.node_id]; $c=$el.Current
            if ($c.ProcessId -ne $o.pid) { throw 'stale node process' }
            $ancestor=$el; $found=$false
            for ($i=0; $null -ne $ancestor -and $i -lt 256; $i++) {
                if ([System.Windows.Automation.Automation]::Compare($ancestor,$root)) { $found=$true; break }
                $ancestor=$walker.GetParent($ancestor)
            }
            if (-not $found) { throw 'stale node or different window' }
            $pattern=$null
            switch ($r.action) {
                'invoke' { $kind=[System.Windows.Automation.InvokePattern]::Pattern; $method='Invoke' }
                'set_value' { if ($c.IsPassword) { throw 'password value writes unsupported' }; $kind=[System.Windows.Automation.ValuePattern]::Pattern; $method='SetValue' }
                'select' { $kind=[System.Windows.Automation.SelectionItemPattern]::Pattern; $method='Select' }
                'toggle' { $kind=[System.Windows.Automation.TogglePattern]::Pattern; $method='Toggle' }
                'expand' { $kind=[System.Windows.Automation.ExpandCollapsePattern]::Pattern; $method='Expand' }
                'collapse' { $kind=[System.Windows.Automation.ExpandCollapsePattern]::Pattern; $method='Collapse' }
                'scroll' { $kind=[System.Windows.Automation.ScrollPattern]::Pattern; $method='Scroll' }
                default { throw 'unsupported action' }
            }
            if ($c.IsPassword -or -not $c.IsEnabled) { throw 'password or disabled control' }
            if (-not $el.TryGetCurrentPattern($kind,[ref]$pattern)) { throw 'unsupported UIA pattern' }
            $foregroundBefore=[UiaNative]::GetForegroundWindow()
            $cursorBefore=[UiaNative+Point]::new(); [void][UiaNative]::GetCursorPos([ref]$cursorBefore)
            # An action may partially succeed even if its provider later throws.
            $cache.Clear()
            $transport='uia-pattern'
            switch ($method) {
                'SetValue' {
                    if ($c.NativeWindowHandle -ne 0 -and
                        ($c.ClassName -eq 'Edit' -or $c.ClassName -like 'WindowsForms10.EDIT.*')) {
                        if (-not $c.IsEnabled -or $pattern.Current.IsReadOnly) { throw 'text control is disabled or read-only' }
                        $result=[UIntPtr]::Zero
                        if ([UiaNative]::SendTextTimeout([IntPtr]::new($c.NativeWindowHandle),0x000c,[UIntPtr]::Zero,[string]$r.value,2,2000,[ref]$result) -eq [IntPtr]::Zero -or $result -eq [UIntPtr]::Zero) {
                            throw 'text update failed or timed out; outcome unknown'
                        }
                        $transport='win32-set-text'
                    } else { $pattern.SetValue([string]$r.value) }
                }
                'Scroll' {
                    $allowed=@('NoAmount','LargeDecrement','SmallDecrement','LargeIncrement','SmallIncrement')
                    if ($r.horizontal -notin $allowed -or $r.vertical -notin $allowed) { throw 'invalid scroll amount' }
                    $pattern.Scroll([System.Windows.Automation.ScrollAmount]::$($r.horizontal),[System.Windows.Automation.ScrollAmount]::$($r.vertical))
                }
                'Invoke' {
                    # The legacy .NET Win32 Button proxy activates its window in
                    # Invoke(). Deliver the documented BN_CLICKED notification
                    # for ordinary Win32/WinForms buttons, without mouse events.
                    if ($c.NativeWindowHandle -ne 0 -and $c.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
                        ($c.ClassName -eq 'Button' -or $c.ClassName -like 'WindowsForms10.BUTTON.*')) {
                        $handle=[IntPtr]::new($c.NativeWindowHandle); $parent=[UiaNative]::GetParent($handle)
                        $parentPid=[uint32]0; [void][UiaNative]::GetWindowThreadProcessId($parent,[ref]$parentPid)
                        if ($parent -eq [IntPtr]::Zero -or $parentPid -ne $o.pid -or -not $c.IsEnabled) { throw 'unsupported button parent' }
                        # WinForms may use the HWND as its child ID; WM_COMMAND
                        # carries only its low word and the full HWND in lParam.
                        $controlId=[uint32]([UiaNative]::GetDlgCtrlID($handle) -band 0xffff)
                        $result=[UIntPtr]::Zero
                        if ([UiaNative]::SendMessageTimeout($parent,0x0111,[UIntPtr]::new([uint32]$controlId),$handle,2,2000,[ref]$result) -eq [IntPtr]::Zero) {
                            throw 'button notification timed out; outcome unknown'
                        }
                        $transport='win32-button-notification'
                    } else { $pattern.Invoke() }
                }
                default { $pattern.$method() }
            }
            $cursorAfter=[UiaNative+Point]::new(); [void][UiaNative]::GetCursorPos([ref]$cursorAfter)
            return @{ok=$true;transport=$transport;
                foreground_changed=([UiaNative]::GetForegroundWindow() -ne $foregroundBefore);
                cursor_changed=($cursorBefore.X -ne $cursorAfter.X -or $cursorBefore.Y -ne $cursorAfter.Y)}
        }
        default { throw 'unsupported operation' }
    }
}
while ($null -ne ($line=[Console]::ReadLine())) {
    try { $r=ConvertFrom-Json $line; $result=Execute $r; $reply=@{ok=$true;result=$result} }
    catch { $reply=@{ok=$false;error=$_.Exception.Message} }
    [Console]::Out.WriteLine((ConvertTo-Json -InputObject $reply -Depth 20 -Compress))
}
