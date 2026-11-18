"""Task-scoped window operations. A session and its captures belong to one MCP connection."""
import base64
import ctypes as ct
from ctypes import wintypes as wt
from dataclasses import dataclass
import json
import math
import secrets

from driver_backend import Driver

def block(data):
    return {'type':'text','text':json.dumps(data,ensure_ascii=False)}

user = ct.WinDLL('user32', use_last_error=True)
user.GetForegroundWindow.restype = wt.HWND
user.SetForegroundWindow.argtypes = [wt.HWND]
user.SetForegroundWindow.restype = wt.BOOL
user.GetCursorPos.argtypes = [ct.POINTER(wt.POINT)]
user.GetWindowThreadProcessId.argtypes = [wt.HWND, ct.POINTER(wt.DWORD)]
user.GetWindowThreadProcessId.restype = wt.DWORD
user.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user.GetAncestor.restype = wt.HWND

def target_info(hwnd, pid):
    owner = wt.DWORD()
    tid = user.GetWindowThreadProcessId(hwnd, ct.byref(owner))
    if not tid or owner.value != pid or user.GetAncestor(hwnd, 2) != hwnd:
        raise ValueError('stale window or process')
    return tid

def sample():
    p = wt.POINT()
    return user.GetForegroundWindow(), (p.x,p.y) if user.GetCursorPos(ct.byref(p)) else None

def changes(before, after):
    return {'foreground_changed':before[0]!=after[0],
            'cursor_changed':before[1]!=after[1] if None not in (before[1],after[1]) else None}

@dataclass
class Task:
    hwnd: int
    pid: int
    tid: int
    allow_capture: bool
    allow_foreground: bool
    starting_foreground: int
    foreground_started: bool = False
    capture_id: str = ''
    context: object = None
    interrupted: bool = False

class Tasks:
    def __init__(self):
        self.sessions = {}
        self.driver = Driver()

    def begin(self,a):
        hwnd,pid=a['hwnd'],a['pid']
        tid=target_info(hwnd,pid)
        if len(self.sessions)>=16:
            raise ValueError('close an existing task before starting another')
        capture=a.get('allow_capture',False)
        foreground=a.get('allow_foreground',False)
        sid=secrets.token_urlsafe(24)
        self.sessions[sid]=Task(hwnd,pid,tid,capture,foreground,user.GetForegroundWindow())
        return {'session_id':sid,'hwnd':hwnd,'pid':pid,'allow_capture':capture,'allow_foreground':foreground}

    def invalidate(self,hwnd,pid):
        for s in self.sessions.values():
            if (s.hwnd,s.pid)==(hwnd,pid):
                s.capture_id,s.context='',None

    def run(self,name,a,call_worker):
        if name=='begin_task':
            return {'content':[block(self.begin(a))]}
        sid=a['session_id']
        s=self.sessions.get(sid)
        if s is None:
            raise ValueError('unknown or ended task')
        if name=='end_task':
            del self.sessions[sid]
            return {'content':[block({'ended':True})]}
        if target_info(s.hwnd,s.pid)!=s.tid:
            raise ValueError('stale task window')
        if name=='capture_window':
            if not s.allow_capture:
                raise ValueError('window capture is not enabled for this task')
            s.capture_id,s.context='',None
            png,ctx=self.driver.capture(s.hwnd,s.pid)
            # Names and bounds come from the same process/window, never global hit testing.
            try:
                anchors=call_worker({'op':'anchors','hwnd':s.hwnd,'pid':s.pid})['anchors']
            except ValueError:
                anchors=[]
            self.driver.validate_capture(s.hwnd,s.pid,ctx)
            left,top,right,bottom=ctx.frame[2]
            labels=[]
            for n in anchors:
                x0,y0,x1,y1=n['rect']
                if all(math.isfinite(v) for v in (x0,y0,x1,y1)) and left<=x0<x1<=right and top<=y0<y1<=bottom:
                    labels.append({'name':n['name'],'type':n['type'],'box':[round(x0-left),round(y0-top),round(x1-left),round(y1-top)]})
            s.capture_id,s.context=secrets.token_urlsafe(24),ctx
            meta={'hwnd':s.hwnd,'pid':s.pid,'capture_id':s.capture_id,'width':ctx.width,
                  'height':ctx.height,'backend':ctx.source,'coordinate_frame':'window_png_pixels','labels':labels}
            return {'content':[block(meta),{'type':'image','mimeType':'image/png','data':base64.b64encode(png).decode('ascii')}]}
        action=a['action']
        fg=a.get('mode','background')=='foreground'
        if fg and not s.allow_foreground:
            raise ValueError('foreground input is not enabled for this task')
        if s.interrupted:
            raise ValueError('foreground changed during task; end this task and reselect the target')
        before=sample()
        argmap={'click':{'x','y'},'double_click':{'x','y'},'right_click':{'x','y'},
                'drag':{'x','y','to_x','to_y'},'type_text':{'text'},'press_key':{'key'},
                'hotkey':{'keys'},'scroll':{'direction','amount'}}
        args={k:v for k,v in a.items() if k not in ('session_id','action','capture_id','mode')}
        allowed=argmap[action]
        required=allowed-{'amount'} if action=='scroll' else allowed
        if set(args)-allowed or not required<=set(args):
            raise ValueError('invalid arguments for '+action)
        ctx=None
        if 'x' in args:
            if not s.allow_capture or not s.context or a.get('capture_id')!=s.capture_id:
                raise ValueError('stale or missing capture for this task')
            ctx=s.context
            if action=='drag':
                args['from_x'],args['from_y']=args.pop('x'),args.pop('y')
        elif 'capture_id' in a:
            raise ValueError('a capture ID is valid only for coordinate actions')
        if ctx is not None:
            self.driver.validate_capture(s.hwnd,s.pid,ctx)
        if fg:
            current=user.GetForegroundWindow()
            if current!=s.hwnd:
                if s.foreground_started or current!=s.starting_foreground:
                    s.interrupted=True
                    raise ValueError('target is not foreground; input stopped')
                if not user.SetForegroundWindow(s.hwnd) or user.GetForegroundWindow()!=s.hwnd:
                    raise ValueError('Windows declined foreground activation; bring the selected window forward to continue')
            s.foreground_started=True
        self.invalidate(s.hwnd,s.pid)
        try:
            result=self.driver.input(s.hwnd,s.pid,action,args,ctx,fg)
        except ValueError as exc:
            flags=changes(before,sample())
            if (fg and user.GetForegroundWindow()!=s.hwnd) or (not fg and (flags['foreground_changed'] or flags['cursor_changed'])):
                s.interrupted=True
            unknown= 'unknown' in str(exc).lower()
            return {'isError':True,'content':[block({'error':str(exc),'hwnd':s.hwnd,'pid':s.pid,'backend':'cua-driver',
                        'delivery':'unknown' if unknown else 'not_dispatched',**flags})]}
        after=sample()
        flags=changes(before,after)
        if (fg and after[0]!=s.hwnd) or (not fg and (flags['foreground_changed'] or flags['cursor_changed'])):
            s.interrupted=True
        result.update(hwnd=s.hwnd,pid=s.pid,**flags)
        return {'isError':result['status']!='dispatched','content':[block(result)]}

