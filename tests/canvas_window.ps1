param([string]$StatePath)
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -TypeDefinition @'
using System;using System.Drawing;using System.Windows.Forms;
public class NativeCanvas : Control {
 public int Clicks,Drags,MarkerHits,EnterKeys,Hotkeys; public string Typed=""; public Point Down,Last; public bool Dragging;
 public NativeCanvas(){SetStyle(ControlStyles.Selectable,true);TabStop=true;BackColor=Color.White;}
 protected override bool IsInputKey(Keys keyData){if((keyData & Keys.KeyCode)==Keys.Enter)return true;return base.IsInputKey(keyData);}
 protected override void OnPaint(PaintEventArgs e){base.OnPaint(e);e.Graphics.FillRectangle(Brushes.CornflowerBlue,30,30,100,65);e.Graphics.DrawString("Dedicated test canvas",Font,Brushes.Black,20,120);}
 protected override void OnMouseDown(MouseEventArgs e){base.OnMouseDown(e);Focus();Down=e.Location;Dragging=true;}
 protected override void OnMouseUp(MouseEventArgs e){base.OnMouseUp(e);Last=e.Location;if(Dragging && Math.Abs(e.X-Down.X)+Math.Abs(e.Y-Down.Y)>10)Drags++;else {Clicks++;if(new Rectangle(30,30,100,65).Contains(e.Location))MarkerHits++;}Dragging=false;Invalidate();}
 protected override void OnKeyPress(KeyPressEventArgs e){base.OnKeyPress(e);Typed+=e.KeyChar;}
 protected override void OnKeyDown(KeyEventArgs e){base.OnKeyDown(e);if(e.KeyCode==Keys.Enter)EnterKeys++;if(e.Control && e.KeyCode==Keys.K)Hotkeys++;}
}
'@
$form=[Windows.Forms.Form]::new();$form.Text='UIA Dedicated Canvas Fixture';$form.Size=[Drawing.Size]::new(400,280);$form.StartPosition='Manual';$form.Location=[Drawing.Point]::new(450,100)
$canvas=[NativeCanvas]::new();$canvas.Dock='Fill';$form.Controls.Add($canvas)
$timer=[Windows.Forms.Timer]::new();$timer.Interval=75;$timer.Add_Tick({@{clicks=$canvas.Clicks;drags=$canvas.Drags;marker_hits=$canvas.MarkerHits;enter_keys=$canvas.EnterKeys;hotkeys=$canvas.Hotkeys;typed=$canvas.Typed;last_x=$canvas.Last.X;last_y=$canvas.Last.Y}|ConvertTo-Json -Compress|Set-Content -LiteralPath $StatePath -Encoding UTF8});$timer.Start()
$form.Add_Shown({$canvas.Focus()|Out-Null;[Console]::WriteLine('ready');[Console]::Out.Flush()});[Windows.Forms.Application]::Run($form)
