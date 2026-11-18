param([string]$StatePath='')
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$target = [Windows.Forms.Form]::new(); $target.Text='UIA Background Test Target'; $target.Size=[Drawing.Size]::new(360,220); $target.StartPosition='Manual'; $target.Location=[Drawing.Point]::new(80,80)
$edit=[Windows.Forms.TextBox]::new(); $edit.AccessibleName='Test Input'; $edit.Location=[Drawing.Point]::new(20,20); $edit.Width=200
$button=[Windows.Forms.Button]::new(); $button.Text='Apply'; $button.Location=[Drawing.Point]::new(20,60)
$label=[Windows.Forms.Label]::new(); $label.Text='waiting'; $label.Location=[Drawing.Point]::new(20,100); $label.Width=250
$duplicate1=[Windows.Forms.Label]::new(); $duplicate1.Text='duplicate'; $duplicate1.Location=[Drawing.Point]::new(20,130)
$duplicate2=[Windows.Forms.Label]::new(); $duplicate2.Text='duplicate'; $duplicate2.Location=[Drawing.Point]::new(150,130)
$button.Add_Click({$label.Text='result: '+$edit.Text})
$target.Controls.AddRange(@($edit,$button,$label,$duplicate1,$duplicate2))
$cover=[Windows.Forms.Form]::new(); $cover.Text='UIA Background Test Cover'; $cover.Size=[Drawing.Size]::new(390,250); $cover.StartPosition='Manual'; $cover.Location=[Drawing.Point]::new(70,70)
$sentinel=[Windows.Forms.TextBox]::new(); $sentinel.AccessibleName='Independent sentinel input'; $sentinel.Text='sentinel-original'; $sentinel.Location=[Drawing.Point]::new(20,20); $sentinel.Width=300; $cover.Controls.Add($sentinel)
$timer=[Windows.Forms.Timer]::new(); $timer.Interval=75
$timer.Add_Tick({if($StatePath){@{target=$edit.Text;sentinel=$sentinel.Text;result=$label.Text;sentinel_focused=$sentinel.Focused}|ConvertTo-Json -Compress|Set-Content -LiteralPath $StatePath -Encoding UTF8}})
$timer.Start()
$target.Add_Shown({$cover.Show(); $cover.Activate(); $sentinel.Focus()|Out-Null; [Console]::Out.WriteLine('ready'); [Console]::Out.Flush()})
[Windows.Forms.Application]::Run($target)
