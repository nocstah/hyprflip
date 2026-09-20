#!/usr/bin/env python3
"""Test two real Brave app windows using local pages and a temporary profile."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from control import environment

p=argparse.ArgumentParser()
p.add_argument("session",type=Path)
p.add_argument("--plugin",type=Path,default=Path("build/hyprflip.so"))
args=p.parse_args()
env=environment(args.session)
root=args.session.parent / "brave-test"
root.mkdir(exist_ok=True)
for k,d in (("XDG_CONFIG_HOME","config"),("XDG_CACHE_HOME","cache"),("XDG_DATA_HOME","data"),("XDG_STATE_HOME","state")):
    (root/d).mkdir(exist_ok=True);env[k]=str(root/d)
env.pop("DBUS_SESSION_BUS_ADDRESS",None)
processes=[]
loaded=False
def ctl(*a):
    r=subprocess.run(["hyprctl",*a],env=env,text=True,capture_output=True,timeout=6)
    if r.returncode or "could not be loaded" in r.stdout:raise AssertionError((a,r.stdout,r.stderr))
    return r.stdout.strip()
def status():return json.loads(ctl("hyprflip","status"))
def wait(fn):
    end=time.monotonic()+20
    while time.monotonic()<end:
        if fn():return
        time.sleep(.05)
    raise AssertionError("Browser test timed out; see brave-test logs")
try:
    assert "hyprflip" not in ctl("plugin","list")
    ctl("plugin","load",str(args.plugin.resolve()));loaded=True
    ctl("repl","hl.config({plugin={hyprflip={duration_ms=500,notifications=false}}})")
    ctl("dispatch","hl.dsp.focus({workspace=5})")
    addresses=[]
    for side,color in (("front","#183a49"),("back","#49334e")):
        title="Hyprflip Brave "+side
        page=root/(side+".html")
        page.write_text(f'<title>{title}</title><body style="background:{color};color:white;font:32px sans-serif;padding:48px"><h1>{title}</h1><p>Two real Brave windows.</p><input placeholder="Type here" style="font:inherit"></body>')
        with (root/(side+".log")).open("wb") as log:
            process=subprocess.Popen(["brave","--user-data-dir="+str(root/"profile"),"--no-first-run","--no-default-browser-check","--disable-background-networking","--disable-component-update","--disable-sync","--ozone-platform=wayland","--app="+page.as_uri()],env=env,stdout=log,stderr=subprocess.STDOUT)
        processes.append(process)
        def match():return [w for w in json.loads(ctl("-j","clients")) if w["title"]==title]
        wait(lambda: bool(match()));addresses.append(match()[0]["address"])
    a,b=addresses
    ctl("dispatch",f'hl.dsp.focus({{window="address:{a}"}})');ctl("hyprflip","mark")
    ctl("dispatch",f'hl.dsp.focus({{window="address:{b}"}})');ctl("hyprflip","pair")
    time.sleep(1)
    for i in range(6):
        ctl("hyprflip","flip");assert status()["animating"],status()
        wait(lambda:not status()["animating"])
        assert status()["pairs"][0]["current"]==(b if i%2==0 else a)
    ctl("hyprflip","unpair")
    print("PASS two real Brave windows, six animated flips, unpair",flush=True)
finally:
    if loaded:ctl("plugin","unload",str(args.plugin.resolve()))
    for process in processes:
        if process.poll() is None:process.terminate()
    for process in processes:
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill()
    ctl("dispatch","hl.dsp.focus({workspace=1})")
