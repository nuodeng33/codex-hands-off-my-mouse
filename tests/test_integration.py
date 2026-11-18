import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.GetForegroundWindow.restype = wintypes.HWND

def cursor():
    point = wintypes.POINT()
    assert user32.GetCursorPos(ctypes.byref(point))
    return (point.x, point.y)

class TestBackground(unittest.TestCase):
    def test_end_to_end(self):
        flags = subprocess.CREATE_NO_WINDOW
        state_path = ROOT / 'tests/winforms-state.json'
        window = subprocess.Popen(['powershell.exe', '-NoProfile', '-STA', '-File', str(ROOT / 'tests/test_window.ps1'), '-StatePath', str(state_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=flags)
        server = subprocess.Popen([PYTHON, str(ROOT / 'plugins/windows-desktop/app/server.py')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', creationflags=flags)
        try:
            self.assertEqual(window.stdout.readline().strip(), 'ready')
            time.sleep(.5)
            counter = 0
            def rpc(method, params=None):
                nonlocal counter
                counter += 1
                server.stdin.write(json.dumps({'jsonrpc':'2.0', 'id':counter, 'method':method, 'params':params or {}})+'\n'); server.stdin.flush()
                reply=json.loads(server.stdout.readline()); self.assertNotIn('error',reply)
                return reply['result']
            def tool(name, args=None):
                result=rpc('tools/call', {'name':name,'arguments':args or {}})
                self.assertFalse(result.get('isError'), result)
                return json.loads(result['content'][0]['text'])
            self.assertIn('protocolVersion',rpc('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'test','version':'1'}}))
            self.assertTrue({'list_windows','get_tree','perform_action'} <= {t['name'] for t in rpc('tools/list')['tools']})
            wins=tool('list_windows')['windows']
            target=next(w for w in wins if w['pid']==window.pid and w['name']=='UIA Background Test Target')
            cover=next(w for w in wins if w['pid']==window.pid and w['name']=='UIA Background Test Cover')
            self.assertEqual(user32.GetForegroundWindow(),cover['hwnd'])
            # Real keyboard input is gated to the owned sentinel fixture, and checked
            # via the application's own state rather than through the service under test.
            sentinel_before=json.loads(state_path.read_text(encoding='utf-8-sig'))
            self.assertTrue(sentinel_before['sentinel_focused'])
            for key in (0x58,0x59):
                self.assertEqual(user32.GetForegroundWindow(),cover['hwnd'])
                user32.keybd_event(key,0,0,0);user32.keybd_event(key,0,2,0)
            time.sleep(.2)
            sentinel_before=json.loads(state_path.read_text(encoding='utf-8-sig'))
            self.assertTrue(sentinel_before['sentinel'].endswith('xy'),sentinel_before)
            before=(user32.GetForegroundWindow(),cursor())
            query={'hwnd':target['hwnd'],'pid':target['pid']}
            tree=tool('get_tree',query)
            edits=[n for n in tree['nodes'] if n['type']=='ControlType.Edit' and not n['password']]
            self.assertEqual(len(edits),1,tree)
            edit=edits[0]
            expected='background-ok / 后台写入'
            written=tool('perform_action',{**query,'observation_id':tree['observation_id'],'node_id':edit['id'],'action':'set_value','value':expected})
            self.assertFalse(written['foreground_changed']); self.assertFalse(written['cursor_changed'])
            stale=rpc('tools/call',{'name':'perform_action','arguments':{**query,'observation_id':tree['observation_id'],'node_id':edit['id'],'action':'set_value','value':'wrong'}})
            self.assertTrue(stale.get('isError'))
            for name, expected_error in [('missing-root', 'not found'), ('duplicate', 'ambiguous')]:
                failure=rpc('tools/call',{'name':'get_tree','arguments':{**query,'root_name':name}})
                self.assertTrue(failure.get('isError'), failure)
                self.assertIn(expected_error,failure['content'][0]['text'])
            tree=tool('get_tree',{**query,'root_name':'Apply'})
            self.assertEqual(tree['nodes'][0]['name'],'Apply')
            self.assertEqual(tree['nodes'][0]['depth'],0)
            button=tree['nodes'][0]
            invoked=tool('perform_action',{**query,'observation_id':tree['observation_id'],'node_id':button['id'],'action':'invoke'})
            self.assertFalse(invoked['foreground_changed']); self.assertFalse(invoked['cursor_changed'])
            tree=tool('get_tree',query)
            self.assertTrue(any(n['name']=='result: '+expected for n in tree['nodes']),tree)
            after=(user32.GetForegroundWindow(),cursor())
            self.assertEqual(before[0],after[0])
            time.sleep(.2)
            independent=json.loads(state_path.read_text(encoding='utf-8-sig'))
            self.assertEqual(independent['target'],expected)
            self.assertEqual(independent['sentinel'],sentinel_before['sentinel'])
            self.assertTrue(independent['sentinel_focused'])
            (ROOT/'tests/native-result.json').write_text(json.dumps({
                'passed':True,'scope':'Self-created covered WinForms window; MCP stdio + UIA',
                'utc':datetime.now(timezone.utc).isoformat(),
                'independent_application_state':independent,
                'sentinel_actual_keyboard_input':sentinel_before['sentinel'],
                'actions':['list_windows','get_tree','set_value Unicode','reject stale observation','reject missing and ambiguous subtree','invoke from named subtree','read updated result'],
                'foreground_before':before[0],'foreground_after':after[0],
                'cursor_before':before[1],'cursor_after':after[1],
                'whole_interval_cursor_unchanged':before[1]==after[1],
                'action_intervals_cursor_unchanged':not written['cursor_changed'] and not invoked['cursor_changed'],
                'target_hwnd':target['hwnd'],'cover_hwnd':cover['hwnd'],
                'result_text':'result: '+expected,'screenshots':0,
                'transports':[written['transport'],invoked['transport']]},ensure_ascii=False,indent=2),encoding='utf8')
            print('covered target and sentinel verified; foreground unchanged; action cursor flags unchanged; whole-interval cursor recorded')
        finally:
            server.stdin.close(); window.terminate()
            server.wait(timeout=5); window.wait(timeout=5)
            for stream in (server.stdout,server.stderr,window.stdout,window.stderr): stream.close()

if __name__=='__main__': unittest.main()
