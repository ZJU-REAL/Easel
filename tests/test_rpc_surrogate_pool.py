"""Pool signatures must safely distinguish inherited undecodable environment data."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

from easel.harnesses import rpc
from easel.harnesses.base import RunRequest


def test_environment_surrogates_can_reuse_and_invalidate_a_pool(tmp_path, monkeypatch):
    instances=[]
    class FakeRPC:
        def __init__(self, request, command, notify, respond, *, acp=False):
            self.native_id=''
            self.reader=SimpleNamespace(done=lambda:False)
            self.process=SimpleNamespace(returncode=None)
            self.closed=0
            instances.append(self)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            self.closed+=1

    monkeypatch.setattr(rpc,'RPC',FakeRPC)
    request=RunRequest('hello',tmp_path,{'BROKEN':'\udcff','LABEL':'二维码 🎨'},session_key='env-surrogate')
    async def exercise():
        try:
            async with rpc.connection(request,['fake-agent'],lambda *a:None,lambda *a:None) as first:
                pass
            async with rpc.connection(request,['fake-agent'],lambda *a:None,lambda *a:None) as repeated:
                assert repeated is first
            changed=replace(request,env={'BROKEN':'\udcfe','LABEL':'二维码 🎨'})
            async with rpc.connection(changed,['fake-agent'],lambda *a:None,lambda *a:None) as next_rpc:
                assert next_rpc is not first
        finally:
            await rpc.close_sessions()
    asyncio.run(exercise())
    assert len(instances)==2
    assert [instance.closed for instance in instances]==[1,1]
