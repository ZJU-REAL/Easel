"""Slow native readiness probes must not block chat or bypass activation guards."""
import asyncio
import threading

import pytest
from web import app as web


def test_slow_hermes_readiness_does_not_block_the_event_loop(monkeypatch):
    tick=threading.Event()
    monkeypatch.setattr(web,'_direct_api_enabled',lambda:False)
    monkeypatch.setattr(web,'_harness_settings',lambda:{'runtime':'hermes'})
    monkeypatch.setattr(web,'get_skills',lambda:[])
    monkeypatch.setattr(web,'list_personas',lambda:[])
    def describe(runtime):
        assert tick.wait(1), 'readiness probe blocked the event loop'
        return {'installed':True}
    monkeypatch.setattr(web.harnesses,'describe',describe)
    async def exercise():
        async def advance():
            await asyncio.sleep(.01)
            tick.set()
        results=await asyncio.gather(web.api_status(),advance())
        assert results[0]['gateway'] and results[0]['runtime']=='hermes'
    asyncio.run(exercise())


def test_activation_rechecks_live_tasks_after_native_probe(monkeypatch):
    active=set(); release=threading.Event()
    for name in ('_BG_TASKS','_DIRECT_CHAT_TASKS'):
        monkeypatch.setattr(web,name,set())
    monkeypatch.setattr(web,'_RUNNING_CHAT',{})
    monkeypatch.setattr(web,'_HARNESS_TASKS',active)
    monkeypatch.setattr(web,'read_settings',lambda path:{})
    def describe(runtime):
        assert release.wait(1)
        return {'installed':True}
    monkeypatch.setattr(web.harnesses,'describe',describe)
    req=web.HarnessSettingsRequest(runtime='hermes',model='',sandbox='workspace-write')
    async def exercise():
        async def start_task():
            await asyncio.sleep(.01)
            active.add('other-live-task')
            release.set()
        results=await asyncio.gather(web.api_harness_settings_save(req),start_task(),return_exceptions=True)
        assert isinstance(results[0],web.HTTPException) and results[0].status_code==409
    asyncio.run(exercise())
