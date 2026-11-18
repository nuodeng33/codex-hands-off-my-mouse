"""Actual desktop fixtures. Run serially; requires a quiet desktop interval."""
import json
import base64
import io
import time
import unittest
from PIL import Image
from native_support import *

class NativeExtended(unittest.TestCase):
    def test_activation_keyboard(self):
        fixture=Fixture('canvas');mcp=MCP();cover=None
        try:
            target=query(fixture.target(mcp,'UIA Dedicated Canvas Fixture'))
            cover=Fixture('test')
            sentinel=cover.target(mcp,'UIA Background Test Cover')
            self.assertEqual(user32.GetForegroundWindow(),sentinel['hwnd'])
            session=mcp.call('begin_task',{**target,'allow_foreground':True})['session_id']
            request={'session_id':session,'action':'type_text','text':'native-input 验收','mode':'foreground'}
            initial=mcp.raw('window_input',request)
            activation='automatic'
            if initial.get('isError'):
                self.assertIn('Windows declined foreground activation',initial['content'][0]['text'])
                current=eventually(lambda:user32.GetForegroundWindow(),lambda hwnd:bool(hwnd),timeout=1)
                self.assertIn(current,(sentinel['hwnd'],target['hwnd']))
                user32.SetForegroundWindow(target['hwnd'])
                self.assertEqual(eventually(lambda:user32.GetForegroundWindow(),lambda hwnd:bool(hwnd),timeout=1),target['hwnd'])
                activation='Windows refused automatic activation; explicit owned-target activation then retry'
                typed=mcp.call('window_input',request)
            else:typed=json.loads(initial['content'][0]['text'])
            self.assertEqual(user32.GetForegroundWindow(),target['hwnd'])
            independent=eventually(lambda:state(fixture.path),lambda s:s['typed']=='native-input 验收')
            key=mcp.call('window_input',{'session_id':session,'action':'press_key','key':'ENTER','mode':'foreground'})
            independent=eventually(lambda:state(fixture.path),lambda s:s['enter_keys']==1)
            hotkey=mcp.call('window_input',{'session_id':session,'action':'hotkey','keys':['CTRL','K'],'mode':'foreground'})
            independent=eventually(lambda:state(fixture.path),lambda s:s['hotkeys']==1)
            self.assertEqual(state(cover.path)['sentinel'],'sentinel-original')
            # An unrelated, owned sentinel takes foreground after the first input.
            user32.SetForegroundWindow(sentinel['hwnd'])
            self.assertEqual(eventually(lambda:user32.GetForegroundWindow(),lambda hwnd:bool(hwnd),timeout=1),sentinel['hwnd'])
            refused=mcp.raw('window_input',{'session_id':session,'action':'type_text','text':'must-not-arrive','mode':'foreground'})
            self.assertTrue(refused.get('isError'),refused)
            self.assertEqual(user32.GetForegroundWindow(),sentinel['hwnd'])
            self.assertEqual(state(cover.path)['sentinel'],'sentinel-original')
            self.assertNotIn('must-not-arrive',state(fixture.path)['typed'])
            mcp.call('end_task',{'session_id':session})
            (TESTS/'activation-keyboard-result.json').write_text(json.dumps({'utc':stamp(),'passed':True,'activation':activation,'initial_response':initial,'type_text':typed,'press_key':key,'hotkey':hotkey,'independent_application_state':independent,'unrelated_foreground_refusal':refused,'sentinel_unchanged':True,'screenshots':0},ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            mcp.close()
            if cover:cover.close()
            fixture.close()

    def test_wpf(self):
        fixture=Fixture('wpf');mcp=MCP()
        try:
            target=query(fixture.target(mcp,'UIA WPF Native Fixture'))
            first=mcp.call('get_tree',target)
            edit=node(first,automation_id='fixture-input')
            self.assertEqual(edit['value'],'wpf-initial')
            action(mcp,target,first,edit,'set_value',value='WPF Unicode 验收')
            second=mcp.call('get_tree',{**target,'diff_from':first['observation_id']})
            self.assertEqual(node(second,automation_id='fixture-input')['value'],'WPF Unicode 验收')
            self.assertIn('diff',second)
            self.assertTrue(second['diff']['changed'])
            combo_tree=mcp.call('get_tree',{**target,'root_automation_id':'fixture-combo'})
            self.assertEqual(combo_tree['nodes'][0]['depth'],0)
            self.assertEqual(combo_tree['nodes'][0]['state']['expansion'],'Collapsed')
            action(mcp,target,combo_tree,combo_tree['nodes'][0],'expand')
            expanded=mcp.call('get_tree',target)
            (TESTS/'wpf-expanded-tree.json').write_text(json.dumps(expanded,ensure_ascii=False,indent=2),encoding='utf-8')
            self.assertEqual(node(expanded,automation_id='fixture-combo')['state']['expansion'],'Expanded')
            beta=next(n for n in expanded['nodes'] if n['name']=='Beta' and n['type']=='ControlType.ListItem' and 'SelectionItemPatternIdentifiers.Pattern' in n['patterns'])
            action(mcp,target,expanded,beta,'select')
            current=mcp.call('get_tree',target)
            combo=node(current,automation_id='fixture-combo')
            if combo['state']['expansion']=='Expanded':
                action(mcp,target,current,combo,'collapse')
                current=mcp.call('get_tree',target)
            independent=eventually(lambda:state(fixture.path),lambda x:x['selected']=='Beta' and x['value']=='WPF Unicode 验收')
            (TESTS/'wpf-result.json').write_text(json.dumps({'utc':stamp(),'passed':True,'scope':'native WPF Value, ExpandCollapse, SelectionItem, automation-id subtree, state and diff','independent_application_state':independent,'diff':second['diff'],'screenshots':0},ensure_ascii=False,indent=2),encoding='utf-8')
        finally:mcp.close();fixture.close()

    def test_canvas(self):
        fixture=Fixture('canvas');mcp=MCP();cover=None
        try:
            target=query(fixture.target(mcp,'UIA Dedicated Canvas Fixture'))
            self.assertEqual(user32.GetForegroundWindow(),target['hwnd'])
            denied=mcp.call('begin_task',target)
            self.assertTrue(mcp.raw('capture_window',{'session_id':denied['session_id']}).get('isError'))
            mcp.call('end_task',{'session_id':denied['session_id']})
            session=mcp.call('begin_task',{**target,'allow_capture':True,'allow_foreground':True})['session_id']
            captured=mcp.raw('capture_window',{'session_id':session})
            self.assertFalse(captured.get('isError'),captured)
            self.assertTrue(any(x['type']=='image' for x in captured['content']))
            capture=json.loads(next(x['text'] for x in captured['content'] if x['type']=='text'))
            self.assertGreater(capture['width'],100);self.assertGreater(capture['height'],100)
            pixels=Image.open(io.BytesIO(base64.b64decode(next(x['data'] for x in captured['content'] if x['type']=='image')))).convert('RGB')
            self.assertEqual(pixels.size,(capture['width'],capture['height']))
            marker=[(x,y) for y in range(pixels.height) for x in range(pixels.width) if pixels.getpixel((x,y))==(100,149,237)]
            self.assertGreater(len(marker),5000)
            marker_box=[min(p[0] for p in marker),min(p[1] for p in marker),max(p[0] for p in marker),max(p[1] for p in marker)]
            x=(marker_box[0]+marker_box[2])//2;y=(marker_box[1]+marker_box[3])//2
            click=mcp.call('window_input',{'session_id':session,'action':'click','capture_id':capture['capture_id'],'x':x,'y':y,'mode':'foreground'})
            independent=eventually(lambda:state(fixture.path),lambda x:x['clicks']==1)
            self.assertEqual(independent['marker_hits'],1,{'image_point':[x,y],'application_state':independent,'marker_box':marker_box})
            self.assertTrue(mcp.raw('window_input',{'session_id':session,'action':'click','capture_id':capture['capture_id'],'x':x,'y':y,'mode':'foreground'}).get('isError'))
            capture=mcp.call('capture_window',{'session_id':session})
            drag=mcp.call('window_input',{'session_id':session,'action':'drag','capture_id':capture['capture_id'],'x':x,'y':y,'to_x':x+90,'to_y':y+40,'mode':'foreground'})
            independent=eventually(lambda:state(fixture.path),lambda x:x['drags']==1)
            capture=mcp.call('capture_window',{'session_id':session})
            # Only an owned fixture may be activated for the refusal probe.
            cover=Fixture('test')
            sentinel=cover.target(mcp,'UIA Background Test Cover')
            self.assertEqual(user32.GetForegroundWindow(),sentinel['hwnd'])
            before=state(cover.path)
            refused=mcp.raw('window_input',{'session_id':session,'action':'click','capture_id':capture['capture_id'],'x':75,'y':85,'mode':'foreground'})
            self.assertTrue(refused.get('isError'),refused)
            self.assertEqual(user32.GetForegroundWindow(),sentinel['hwnd'])
            self.assertEqual(before['sentinel'],state(cover.path)['sentinel'])
            self.assertEqual(independent['clicks'],state(fixture.path)['clicks'])
            mcp.call('end_task',{'session_id':session})
            self.assertTrue(mcp.raw('capture_window',{'session_id':session}).get('isError'))
            (TESTS/'canvas-result.json').write_text(json.dumps({'utc':stamp(),'passed':True,'scope':'dedicated custom canvas only','capture_image_returned':True,'capture_dimensions':[capture['width'],capture['height']],'capture_not_saved':True,'marker_rgb':[100,149,237],'marker_pixels':len(marker),'marker_box':marker_box,'click_point_from_png':[x,y],'click':click,'drag':drag,'independent_application_state':independent,'stale_capture_refused':True,'different_foreground_fixture_refused':refused,'sentinel_unchanged':True,'ended_session_refused':True},ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            mcp.close()
            if cover:cover.close()
            fixture.close()

if __name__=='__main__':unittest.main()
