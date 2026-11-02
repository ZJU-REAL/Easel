import sys
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/builtin/skill-toutiao-publisher/scripts'))
import toutiao_publish as tp


def test_default_preview_never_opens_a_browser(monkeypatch):
    monkeypatch.setattr(tp,'_require_playwright',lambda:pytest.fail('preview must be offline'))
    result=tp.publish_article('body','title',[],None,[],True,False,False,1000)
    assert result['published'] is False and not result.get('draft_saved')


def test_draft_is_a_remote_write_and_scans_sensitive_content(monkeypatch):
    monkeypatch.setattr(tp,'publish_article',lambda *a:pytest.fail('must block before remote write'))
    with pytest.raises(SystemExit) as caught:
        tp.main(['--title','title','--content','sk-ABCDEFGHIJKLMNOPQRSTUVWX','--draft'])
    assert caught.value.code==7


def test_unverified_result_cannot_exit_success(monkeypatch,tmp_path):
    monkeypatch.setattr(tp,'publish_article',lambda *a:{'published':False})
    monkeypatch.setattr(tp,'_write_record',lambda *a:pytest.fail('must not record success'))
    with pytest.raises(SystemExit) as caught:tp.main(['--title','title','--content','body','--exec'])
    assert caught.value.code==5


@pytest.mark.parametrize('mode,endpoint',[('draft','save'),('publish','publish')])
def test_receipt_requires_matching_write_and_id(mode,endpoint):
    url=f'https://mp.toutiao.com/mp/agw/article/{endpoint}/'
    result=tp._write_receipt(url,200,{'code':0,'data':{'article_id':'123'}})
    assert result=={'mode':mode,'outcome':'accepted','id':'123'}
    assert tp._write_receipt(url,200,{'code':0,'data':{}})['outcome']=='unknown'
    assert tp._write_receipt(url,500,{'code':0,'data':{'article_id':'123'}})['outcome']=='unknown'
    assert tp._write_receipt(url.replace('mp.toutiao.com','evil.example'),200,{'code':0,'data':{'article_id':'123'}}) is None


def test_saving_activity_does_not_confirm_saved_draft(monkeypatch):
    clock=[0.0]
    monkeypatch.setattr(tp,'time',SimpleNamespace(time=lambda:clock[0]))
    class Page:
        def inner_text(self,*a):return '草稿保存中...'
        def wait_for_timeout(self,ms):clock[0]+=ms/1000
    assert tp._wait_autosave(Page(),1000) is False


def test_confirmation_timeout_does_not_click_another_label(monkeypatch):
    clicked=[]
    class Button:
        def click(self):clicked.append('preview')
    class Confirmation:
        @property
        def first(self):return self
        def count(self):return 1
        def is_visible(self):return True
        def click(self):clicked.append('confirm');raise TimeoutError('uncertain')
    page=SimpleNamespace(wait_for_timeout=lambda *a:None,locator=lambda *a:Confirmation())
    monkeypatch.setattr(tp,'_first_match',lambda *a:Button())
    with pytest.raises(TimeoutError):tp._click_submit(page)
    assert clicked==['preview','confirm']
