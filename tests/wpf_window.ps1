param([string]$StatePath)
Add-Type -AssemblyName PresentationFramework,PresentationCore,WindowsBase
$window=[Windows.Window]::new(); $window.Title='UIA WPF Native Fixture'; $window.Width=420; $window.Height=260
$panel=[Windows.Controls.StackPanel]::new(); $panel.Margin='20'; [Windows.Automation.AutomationProperties]::SetAutomationId($panel,'fixture-panel')
$edit=[Windows.Controls.TextBox]::new(); $edit.Text='wpf-initial'; [Windows.Automation.AutomationProperties]::SetAutomationId($edit,'fixture-input'); [Windows.Automation.AutomationProperties]::SetName($edit,'WPF Input')
$combo=[Windows.Controls.ComboBox]::new(); [Windows.Automation.AutomationProperties]::SetAutomationId($combo,'fixture-combo'); [Windows.Automation.AutomationProperties]::SetName($combo,'WPF Choice')
foreach($name in @('Alpha','Beta','Gamma')){$item=[Windows.Controls.ComboBoxItem]::new();$item.Content=$name;$combo.Items.Add($item)|Out-Null};$combo.SelectedIndex=0
$label=[Windows.Controls.TextBlock]::new();$label.Text='WPF status';[Windows.Automation.AutomationProperties]::SetName($label,'WPF status')
$panel.Children.Add($edit)|Out-Null;$panel.Children.Add($combo)|Out-Null;$panel.Children.Add($label)|Out-Null;$window.Content=$panel
$timer=[Windows.Threading.DispatcherTimer]::new();$timer.Interval=[TimeSpan]::FromMilliseconds(75)
$timer.Add_Tick({@{value=$edit.Text;selected=$combo.SelectedItem.Content;expanded=$combo.IsDropDownOpen}|ConvertTo-Json -Compress|Set-Content -LiteralPath $StatePath -Encoding UTF8});$timer.Start()
$window.Add_ContentRendered({[Console]::WriteLine('ready');[Console]::Out.Flush()});$window.ShowDialog()|Out-Null
