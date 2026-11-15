"""Hermes admission and shared lifecycle preserve native session ownership."""
from pathlib import Path

from easel import run_store
from easel.run_store import RunStore


def test_hermes_runs_can_be_admitted_completed_and_reopened(tmp_path):
    store=RunStore(tmp_path/'runs.sqlite3')
    queued=store.create('hermes-turn','hermes-session','hermes')
    running=store.transition(queued.turn_id,expected_version=queued.version,state='running',owner_id='owner')
    final=store.transition(running.turn_id,expected_version=running.version,state='succeeded',owner_id='owner')
    assert RunStore(store.path).get(queued.turn_id)==final
    assert final.backend=='hermes'


def test_invalid_unicode_admission_reports_422_before_dispatch(tmp_path,monkeypatch):
    import asyncio
    import pytest
    from web import app as web
    monkeypatch.setattr(web,'SESSIONS_DIR',tmp_path)
    req=web.ChatRequest(message='no dispatch',sessionId='\udcff',turnId='invalid-unicode')
    with pytest.raises(web.HTTPException) as error:
        asyncio.run(web._reserve_chat_run(req,'hermes'))
    assert error.value.status_code==422
    assert RunStore(tmp_path/'runs.sqlite3').get('invalid-unicode') is None
