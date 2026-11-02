"""今日头条接入 Web 工作台的契约测试。

覆盖 web/app.py 里为头条新增的接触点。全部不启浏览器、不联网（subprocess 被替身顶掉）：
  1) /api/accounts 出现 toutiao 卡片（账号页的卡片完全由这个接口驱动）
  2) /api/login/toutiao 分派到 toutiao_publish.py 的 login 子命令
  3) /api/accounts/toutiao/whoami 分派到 whoami 子命令并透传 JSON
  4) /api/publish/toutiao 分派到发布（正文走 --content 直传，不落临时文件）

运行：pytest tests/test_toutiao_web.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))

import app as web  # noqa: E402

SCRIPT_SUFFIX = "skill-toutiao-publisher/scripts/toutiao_publish.py"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """把登录目录与产物目录换到沙箱，避免测试污染 outputs/ 与用户配置。"""
    login_dir = tmp_path / "_login"
    login_dir.mkdir()
    monkeypatch.setattr(web, "LOGIN_DIR", login_dir)
    monkeypatch.setattr(web, "OUTPUTS_DIR", tmp_path)
    # 内容日历文件是导入期算出的模块常量（OUTPUTS_DIR / "_schedule.json"），
    # 不显式改掉的话，发布用例会往用户真实的内容日历里写测试条目。
    monkeypatch.setattr(web, "SCHEDULE_FILE", tmp_path / "_schedule.json")
    monkeypatch.setattr(web, "LOGIN_PROCESSES", {})
    with web._WHOAMI_LOCK:
        web._WHOAMI_CACHE.clear()
    # TrustedHostMiddleware 只放行 localhost/127.0.0.1（TestClient 默认的 testserver 会被判
    # Invalid host header），local_write_guard 又会把非本机来源的写请求判 403——三件套都要给。
    local = "http://127.0.0.1:7860"
    with TestClient(web.app, base_url=local, client=("127.0.0.1", 51234),
                    headers={"Origin": local}) as c:
        yield c


def test_accounts_lists_toutiao(client):
    """账号页卡片由 /api/accounts 驱动——注册表加了头条，卡片就该出现。"""
    data = client.get("/api/accounts").json()
    platforms = [a["platform"] for a in data]

    assert "toutiao" in platforms, f"缺 toutiao，实际返回：{platforms}"
    toutiao = next(a for a in data if a["platform"] == "toutiao")
    assert toutiao["name"] == "今日头条"
    assert toutiao["supported"] is True
    assert len(data) == len(web.LOGIN_RUNNERS)


def test_login_dispatch_uses_toutiao_login_subcommand(monkeypatch, client):
    """登录分派：起 toutiao_publish.py 的 login 子命令，二维码/状态文件指向登录目录。"""
    captured: dict = {}

    class FakePopen:
        def __init__(self, cmd, **kw):
            captured["cmd"] = cmd
            # 模拟 runner 立刻写好状态与二维码，免得 api_login_start 等满轮询窗口
            (web.LOGIN_DIR / "toutiao.png").write_bytes(b"fake-png")
            (web.LOGIN_DIR / "toutiao.json").write_text(
                json.dumps({"state": "qr_ready", "message": "请扫码", "qr": "", "ts": 0}),
                encoding="utf-8")

        def poll(self):
            return None  # 进程还活着

    monkeypatch.setattr(web.subprocess, "Popen", FakePopen)

    r = client.post("/api/login/toutiao")

    assert r.status_code == 200, r.text
    assert r.json()["state"] == "qr_ready"
    cmd = captured["cmd"]
    assert Path(cmd[1]).as_posix().endswith(SCRIPT_SUFFIX), cmd
    assert cmd[2] == "login", cmd
    assert "--qr-out" in cmd and "--status-file" in cmd, cmd
    assert str(web.LOGIN_DIR / "toutiao.png") in cmd, cmd
    assert str(web.LOGIN_DIR / "toutiao.json") in cmd, cmd


def test_whoami_dispatch_passes_through_json(monkeypatch, client):
    """whoami 分派到头条脚本，并把脚本 stdout 的 JSON 透传给前端。"""
    captured: dict = {}

    class FakeCompleted:
        returncode = 0
        stdout = json.dumps({"loggedIn": True, "name": "我的头条号", "avatar": ""})
        stderr = ""

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr(web.subprocess, "run", fake_run)

    r = client.get("/api/accounts/toutiao/whoami")

    assert r.status_code == 200, r.text
    assert r.json() == {"loggedIn": True, "name": "我的头条号", "avatar": ""}
    cmd = captured["cmd"]
    assert Path(cmd[1]).as_posix().endswith(SCRIPT_SUFFIX), cmd
    assert cmd[2] == "whoami", cmd


def test_whoami_script_error_is_not_cached(monkeypatch, client):
    """脚本自报 error（浏览器起不来）时，后端不能把它当「可信的未登录」写缓存。

    上游 v0.3.0 起这类「结论不可信」的情况统一报 502（未能确认当前账号身份），
    而不是回一个 loggedIn=False —— 后者会被前端当成「没登录，去扫码」误导用户。
    """
    class FakeCompleted:
        returncode = 0
        stdout = json.dumps({"loggedIn": False, "name": "", "avatar": "",
                             "error": "浏览器起不来"})
        stderr = ""

    monkeypatch.setattr(web.subprocess, "run", lambda cmd, **kw: FakeCompleted())

    r = client.get("/api/accounts/toutiao/whoami")

    assert r.status_code == 502, r.text
    assert "未能确认" in r.json()["detail"], r.text
    with web._WHOAMI_LOCK:
        assert "toutiao" not in web._WHOAMI_CACHE, "error 结论不应进缓存"


def test_publish_dispatch_uses_toutiao_script(monkeypatch, client):
    """发布分派：正文走 --content 直传，不落临时文件；标题/话题一并带上。"""
    cmds = _capture_all_cmds(monkeypatch)

    r = client.post("/api/publish/toutiao",
                    json={"title": "标题", "body": "正文内容", "tags": "AI"})

    assert r.status_code == 200, r.text
    cmd = _publish_cmd(cmds)
    assert "--content" in cmd and "正文内容" in cmd, cmd
    assert "--title" in cmd and "标题" in cmd, cmd


def _capture_all_cmds(monkeypatch) -> list[list[str]]:
    """收下发布链路里跑过的所有子进程命令行。

    上游 v0.3.0 起发布成功后还会调 skill-publish-log 记一条，所以一次发布会起两个子进程；
    只抓最后一个会抓到 log.py，必须按脚本路径挑出真正的发布命令。
    """
    cmds: list[list[str]] = []

    class FakeCompleted:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kw):
        cmds.append(list(cmd))
        result=FakeCompleted()
        result.stdout=json.dumps({"draft_saved": "--draft" in cmd, "published": "--draft" not in cmd})
        return result

    monkeypatch.setattr(web.subprocess, "run", fake_run)
    return cmds


def _publish_cmd(cmds: list[list[str]]) -> list[str]:
    """从所有子进程调用里挑出头条发布那一条。"""
    for cmd in cmds:
        if len(cmd) > 1 and Path(cmd[1]).as_posix().endswith(SCRIPT_SUFFIX):
            return cmd
    raise AssertionError(f"没找到头条发布命令，实际跑过：{cmds}")


def _capture_publish_cmd(monkeypatch, client, payload: dict) -> list[str]:
    """跑一次发布并返回真正拼出来的发布命令行（subprocess 被替身顶掉）。"""
    cmds = _capture_all_cmds(monkeypatch)
    r = client.post("/api/publish/toutiao", json=payload)
    assert r.status_code == 200, r.text
    return _publish_cmd(cmds)


def test_publish_draft_flag_switches_to_draft(monkeypatch, client):
    """draft=true → 走 --draft（落后台草稿箱），不发 --exec。"""
    cmd = _capture_publish_cmd(monkeypatch, client,
                               {"title": "标题", "body": "正文", "tags": "AI", "draft": True})

    assert "--draft" in cmd, cmd
    assert "--exec" not in cmd, cmd


def test_publish_without_draft_flag_still_execs(monkeypatch, client):
    """默认仍是真发布（--exec）——存草稿必须显式勾选，不能默认改行为。"""
    cmd = _capture_publish_cmd(monkeypatch, client, {"title": "标题", "body": "正文"})

    assert "--exec" in cmd, cmd
    assert "--draft" not in cmd, cmd


def test_draft_flag_is_rejected_for_unsupported_platforms(monkeypatch, client):
    cmds = _capture_all_cmds(monkeypatch)
    response = client.post('/api/publish/zhihu', json={'title':'title','body':'body','draft':True})
    assert response.status_code == 400 and not cmds


def test_draft_publish_is_logged_as_draft_in_calendar(monkeypatch, client, tmp_path):
    """存草稿的内容不该在内容日历里记成「已发布」。"""
    sched = tmp_path / "_schedule.json"
    monkeypatch.setattr(web, "SCHEDULE_FILE", sched)

    _capture_publish_cmd(monkeypatch, client,
                         {"title": "草稿标题", "body": "正文", "draft": True})

    items = json.loads(sched.read_text(encoding="utf-8"))
    assert len(items) == 1, items
    assert items[0]["status"] == "draft", items
    assert items[0]["title"] == "草稿标题", items


def test_publish_passes_media_as_images(monkeypatch, client):
    """发布页选的图要透传成 --images（此前媒体被静默丢弃，图文发不出图）。"""
    img = Path(web.OUTPUTS_DIR) / "fig.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"fake-png")

    cmd = _capture_publish_cmd(monkeypatch, client,
                               {"title": "标题", "body": "正文", "media": ["fig.png"]})

    assert "--images" in cmd, cmd
    idx = cmd.index("--images")
    assert str(img) in cmd[idx + 1], cmd


def test_unverified_result_does_not_record_calendar(monkeypatch,client,tmp_path):
    class Result:
        returncode=0
        stdout='{"published":false}'
        stderr=''
    monkeypatch.setattr(web.subprocess,'run',lambda *a,**k:Result())
    response=client.post('/api/publish/toutiao',json={'title':'title','body':'body'})
    assert response.status_code==200 and response.json()['ok'] is False
    assert not (tmp_path/'_schedule.json').exists()
