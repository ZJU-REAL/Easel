from seal_core.tasks import TaskStore, TaskError


def test_tasks_have_isolated_conversations_and_persist(tmp_path):
    store = TaskStore(tmp_path)
    a = store.create("任务 A", "xiaohongshu", account_id="acc", scenario="W1")
    b = store.create("任务 B", "xiaohongshu", account_id="acc", scenario="W1")
    assert a["conversation_id"] != b["conversation_id"]
    assert store.by_conversation(a["conversation_id"])["task_id"] == a["task_id"]
    # A fresh store instance must recover the same state after restart.
    restarted = TaskStore(tmp_path)
    assert {x["task_id"] for x in restarted.list()} == {a["task_id"], b["task_id"]}
    assert restarted.by_conversation(b["conversation_id"])["title"] == "任务 B"


def test_task_conversation_cannot_be_reused(tmp_path):
    store = TaskStore(tmp_path)
    a = store.create("A", "xiaohongshu", account_id="acc", conversation_id="chat-a")
    try:
        store.create("B", "xiaohongshu", account_id="acc", conversation_id="chat-a")
        assert False, "应拒绝复用其他任务的会话"
    except TaskError:
        pass
    assert store.ensure_conversation(a["task_id"], "chat-a")["conversation_id"] == "chat-a"
    # A task may keep its own conversation; replacing it with another task's
    # conversation is rejected.
    b = store.create("B", "xiaohongshu", account_id="acc")
    with __import__("pytest").raises(TaskError):
        store.ensure_conversation(b["task_id"], "chat-a")


def test_delete_task_keeps_other_tasks_and_is_scoped(tmp_path):
    store = TaskStore(tmp_path)
    a = store.create("A", "xiaohongshu", account_id="acc")
    b = store.create("B", "xiaohongshu", account_id="acc")
    deleted = store.delete(a["task_id"])
    assert deleted == {"ok": True, "task_id": a["task_id"], "conversation_id": a["conversation_id"]}
    assert [x["task_id"] for x in store.list()] == [b["task_id"]]
    assert store.by_conversation(a["conversation_id"]) is None
    assert store.by_conversation(b["conversation_id"])["task_id"] == b["task_id"]
    with __import__("pytest").raises(TaskError):
        store.events(a["task_id"])


def test_workflow_stage_and_status_boundaries(tmp_path):
    store = TaskStore(tmp_path)
    t = store.create("A", "xiaohongshu", account_id="acc")
    tid = t["task_id"]
    # Draft cannot complete stages until explicitly started.
    with __import__("pytest").raises(TaskError):
        store.complete_stage(tid, "W1.1")
    store.set_status(tid, "in_progress")
    store.complete_stage(tid, "W1.1")
    store.advance(tid, "W1.2")
    assert store.get(tid)["current_stage_index"] == 1
    store.set_status(tid, "paused")
    with __import__("pytest").raises(TaskError):
        store.advance(tid, "W1.3")
def test_lifecycle(tmp_path):
 s=TaskStore(tmp_path); t=s.create('t','xiaohongshu',account_id='a'); tid=t['task_id']
 s.set_status(tid,'in_progress'); s.complete_stage(tid,'W1.1'); s.advance(tid,'W1.2'); s.set_status(tid,'paused')
 try: s.complete_stage(tid,'W1.2'); assert False
 except TaskError: pass
 s.set_status(tid,'in_progress'); s.complete_stage(tid,'W1.2')
def test_w3_without_account(tmp_path):
 assert TaskStore(tmp_path).create('x','xiaohongshu',scenario='W3')['account_id'] is None

def test_task_conversations_are_unique_and_isolated(tmp_path):
 s = TaskStore(tmp_path)
 a = s.create('A', 'xiaohongshu', account_id='acct', conversation_id='chat_a')
 b = s.create('B', 'xiaohongshu', account_id='acct', conversation_id='chat_b')
 assert s.by_conversation('chat_a')['task_id'] == a['task_id']
 assert s.by_conversation('chat_b')['task_id'] == b['task_id']
 try:
  s.ensure_conversation(b['task_id'], 'chat_a')
  assert False, '同一会话不应绑定多个任务'
 except TaskError as exc:
  assert '已绑定' in str(exc)

def test_delete_task_does_not_affect_other_task(tmp_path):
 s = TaskStore(tmp_path)
 a = s.create('A', 'xiaohongshu', account_id='acct')
 b = s.create('B', 'xiaohongshu', account_id='acct')
 result = s.delete(a['task_id'])
 assert result['ok'] is True
 assert s.by_conversation(a['conversation_id']) is None
 assert s.get(b['task_id'])['title'] == 'B'
 try:
  s.get(a['task_id'])
  assert False, '已删除任务仍可读取'
 except TaskError:
  pass

def test_invalid_conversation_id_rejected(tmp_path):
 s = TaskStore(tmp_path)
 try:
  s.create('bad', 'xiaohongshu', account_id='acct', conversation_id='chat/../../x')
  assert False, '应拒绝路径穿越式 conversation_id'
 except TaskError:
  pass
