"""Owned-window acceptance helpers. Never discovers a target by title alone."""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
TESTS=ROOT/'tests'
user32=ctypes.WinDLL('user32',use_last_error=True)
user32.GetForegroundWindow.restype=wintypes.HWND
user32.SetForegroundWindow.argtypes=[wintypes.HWND]

def stamp():return datetime.now(timezone.utc).isoformat()
def state(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def eventually(fn, predicate, timeout=4):
    end=time.monotonic()+timeout
    last=None
    while time.monotonic()<end:
        try:
            last=fn()
            if predicate(last):return last
        except (OSError,ValueError):pass
        time.sleep(.08)
    raise AssertionError(f'Condition not reached: {last!r}')

class MCP:
    def __init__(self):
        self.process=subprocess.Popen([sys.executable,str(ROOT/'plugins/windows-desktop/app/server.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
        self.queue=queue.Queue();self.counter=0
        def reader():
            for line in self.process.stdout:self.queue.put(line)
        threading.Thread(target=reader,daemon=True).start()
    def rpc(self,method,params=None):
        self.counter+=1
        self.process.stdin.write(json.dumps({'jsonrpc':'2.0','id':self.counter,'method':method,'params':params or {}})+'\n');self.process.stdin.flush()
        reply=json.loads(self.queue.get(timeout=25))
        if 'error' in reply:raise AssertionError(reply['error'])
        return reply['result']
    def raw(self,name,args=None):return self.rpc('tools/call',{'name':name,'arguments':args or {}})
    def call(self,name,args=None):
        result=self.raw(name,args)
        if result.get('isError'):raise AssertionError(result)
        return json.loads(next(x['text'] for x in result['content'] if x['type']=='text'))
    def close(self):
        self.process.stdin.close()
        try:self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.process.stdout.close();self.process.stderr.close()

class Fixture:
    def __init__(self,name):
        self.path=TESTS/(name+'-state.json')
        self.process=subprocess.Popen(['powershell.exe','-NoProfile','-STA','-File',str(TESTS/(name+'_window.ps1')),'-StatePath',str(self.path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
        output=queue.Queue()
        threading.Thread(target=lambda:output.put(self.process.stdout.readline()),daemon=True).start()
        if output.get(timeout=15).strip()!='ready':raise AssertionError(self.process.stderr.read())
        eventually(lambda:state(self.path),lambda v:bool(v))
    def target(self,mcp,title):
        return next(w for w in mcp.call('list_windows')['windows'] if w['pid']==self.process.pid and w['name']==title)
    def close(self):
        self.process.terminate();self.process.wait(timeout=5)
        self.process.stdout.close();self.process.stderr.close()

def action(mcp,target,tree,node,kind,**kwargs):
    result=mcp.call('perform_action',{**target,'observation_id':tree['observation_id'],'node_id':node['id'],'action':kind,**kwargs})
    assert not result['foreground_changed'] and not result['cursor_changed'],result
    return result

def query(target):return {k:target[k] for k in ('hwnd','pid')}
def node(tree,**fields):return next(n for n in tree['nodes'] if all(n.get(k)==v for k,v in fields.items()))
