"""Cooperative continuation, owned by the existing token reader (no second writer)."""
import time

def drain(step, publish, stop, wait, interrupted, clock=time.monotonic, duration=20):
    deadline=clock()+duration;last=clock()
    while not stop() and not interrupted() and clock()<deadline:
        if wait(.1) or interrupted():return
        progress=step()
        finished=not progress.get('pending')
        if finished or clock()-last>=2:
            if stop() or interrupted():return
            publish(progress);last=clock()
        if finished:return
