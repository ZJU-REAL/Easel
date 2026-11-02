"""New channels must prove submission and retain uncertain outcomes without replay."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/shared/scripts'))
import web_publisher as wp
from playwright.sync_api import TimeoutError as BrowserTimeout


@pytest.mark.parametrize('platform,url,payload,identifier', [
    ('juejin','https://api.juejin.cn/content_api/v1/article/publish',{'err_no':0,'data':{'article_id':'123'}},'123'),
    ('twitter-x','https://x.com/i/api/graphql/hash/CreateTweet',{'data':{'create_tweet':{'tweet_results':{'result':{'rest_id':'456'}}}}},'456'),
])
def test_submission_receipt_requires_platform_and_content_id(platform,url,payload,identifier):
    assert wp._publish_receipt(platform,url,200,payload)['id']==identifier
    assert wp._publish_receipt(platform,url,500,payload)['outcome']=='unknown'
    assert wp._publish_receipt(platform,url,200,{})['outcome']=='unknown'
    assert wp._publish_receipt(platform,url.replace('https://','https://evil.example/'),200,payload) is None
    assert wp._publish_receipt(platform,url+'Other',200,payload) is None


@pytest.mark.parametrize('platform,url,payload', [
    ('juejin','https://api.juejin.cn/content_api/v1/article/publish',{'err_no':403,'err_msg':'private-text'}),
    ('twitter-x','https://x.com/i/api/graphql/hash/CreateTweet',{'errors':[{'message':'private-text'}]}),
])
def test_platform_rejection_does_not_expose_raw_response(platform,url,payload):
    assert wp._publish_receipt(platform,url,200,payload)=={'outcome':'rejected'}


def browser_flow(monkeypatch,tmp_path,platform,*,timeout=False,reject=False,unknown=False):
    calls=[]
    listeners={}
    clock=[0.0]
    monkeypatch.setattr(wp,'time',SimpleNamespace(time=lambda:clock[0],monotonic=lambda:clock[0]))
    url = 'https://api.juejin.cn/content_api/v1/article/publish' if platform=='juejin' else 'https://x.com/i/api/graphql/hash/CreateTweet'
    payload = {'err_no':0,'data':{'article_id':'123'}} if platform=='juejin' else {'data':{'create_tweet':{'tweet_results':{'result':{'rest_id':'456'}}}}}
    if reject:
        payload={'err_no':403} if platform=='juejin' else {'errors':[{'code':403}]}
    if unknown:payload={}
    class Element:
        def __init__(self,selector): self.selector=selector
        def scroll_into_view_if_needed(self): pass
        def inner_text(self): return 'test post content'
        def click(self,**kwargs):
            if 'ui-btn.primary' in self.selector or 'tweetButton' in self.selector:
                calls.append('submit')
                if timeout: raise BrowserTimeout('may already have reached platform')
                if 'response' in listeners:
                    listeners['response'](SimpleNamespace(request=SimpleNamespace(method='POST'),url=url,status=200,json=lambda:payload))
    class Page:
        url='https://x.com/compose/post'
        keyboard=SimpleNamespace(press=lambda *a:None,type=lambda *a:None)
        def on(self,event,callback): listeners[event]=callback
        def goto(self,*a,**k): pass
        def wait_for_timeout(self,milliseconds): clock[0]+=milliseconds/1000
        def wait_for_selector(self,*a,**k): pass
        def screenshot(self,*a,**k): pass
        def evaluate(self,script,*args):
            assert 'pointerdown' not in script,'uncertain submit must not replay through JS'
        def query_selector(self,*args): return object()  # a visible popup/toast is not proof
    page=Page()
    browser=SimpleNamespace(pages=[page],close=lambda:None)
    class Runtime:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a,**k:browser))
        def __exit__(self,*args):pass
    monkeypatch.setattr('playwright.sync_api.sync_playwright',lambda:Runtime())
    monkeypatch.setattr(wp,'_profile_dir',lambda *args:tmp_path/'profile')
    monkeypatch.setattr(wp,'_launch_kwargs',lambda *args,**kwargs:{})
    monkeypatch.setattr(wp,'_authenticated_account',lambda *args:{'id':'1'})
    monkeypatch.setattr(wp,'_first_visible_el',lambda page,selector:Element(selector))
    monkeypatch.setattr(wp,'_fill_first_visible',lambda *args:None)
    monkeypatch.setattr(wp.human_pace,'pause_before_commit',lambda *args:None)
    args=SimpleNamespace(platform=platform,profile_base=None,media='',title='title',desc='body',tags='',cover='',keep_open=False)
    return calls,lambda:wp._run_browser(args,headed=False,do_publish=True)


@pytest.mark.parametrize('platform',['juejin','twitter-x'])
def test_real_flow_accepts_only_receipt_and_submits_once(monkeypatch,tmp_path,platform,capsys):
    calls,run=browser_flow(monkeypatch,tmp_path,platform)
    assert run()==0
    assert calls==['submit']
    assert '平台响应作品' in capsys.readouterr().out


@pytest.mark.parametrize('platform',['juejin','twitter-x'])
def test_real_flow_does_not_reclick_after_uncertain_submit(monkeypatch,tmp_path,platform,capsys):
    calls,run=browser_flow(monkeypatch,tmp_path,platform,timeout=True)
    with pytest.raises(SystemExit) as caught:run()
    assert caught.value.code==5 and calls==['submit']
    assert '先别重发' in capsys.readouterr().err


@pytest.mark.parametrize('platform',['juejin','twitter-x'])
def test_real_flow_rejection_is_not_published(monkeypatch,tmp_path,platform):
    calls,run=browser_flow(monkeypatch,tmp_path,platform,reject=True)
    with pytest.raises(SystemExit) as caught:run()
    assert caught.value.code==5 and calls==['submit']


@pytest.mark.parametrize('platform',['juejin','twitter-x'])
def test_real_flow_popup_or_navigation_cannot_replace_missing_receipt(monkeypatch,tmp_path,platform,capsys):
    calls,run=browser_flow(monkeypatch,tmp_path,platform,unknown=True)
    with pytest.raises(SystemExit) as caught:run()
    assert caught.value.code==5 and calls==['submit']
    assert '先别重发' in capsys.readouterr().err


def test_juejin_anonymous_statistics_are_not_a_login(monkeypatch):
    import juejin_stats as stats
    monkeypatch.setattr(stats,'_request',lambda url,body,jar: {'err_no':0,'data':{'user_id':'1','user_name':'public'}} if 'user/get' in url else {'err_no':0,'data':[]})
    assert stats._fetch_with('1',20,None)['loggedIn'] is False
    assert stats._fetch_with('',20,object())['loggedIn'] is True


def test_x_public_profile_does_not_prove_login(monkeypatch,tmp_path):
    import x_stats as stats
    page=SimpleNamespace(goto=lambda *a,**k:None,wait_for_timeout=lambda *a:None,
                         evaluate=lambda *a:{'handle':'someone','name':'Public account','posts':'0',
                                             'stats':[{'href':'/someone/followers','text':'1.2M Followers'}]},
                         mouse=SimpleNamespace(wheel=lambda *a:None))
    browser=SimpleNamespace(pages=[page],close=lambda:None)
    class Runtime:
        def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a,**k:browser))
        def __exit__(self,*args):pass
    monkeypatch.setattr('playwright.sync_api.sync_playwright',lambda:Runtime())
    monkeypatch.setattr(stats,'BROWSER_PROFILES',tmp_path)
    monkeypatch.setattr(wp,'_settle_login',lambda *a:None)
    monkeypatch.setattr(wp,'_is_logged_in',lambda *a:False)
    assert stats.fetch('someone')['loggedIn'] is False
