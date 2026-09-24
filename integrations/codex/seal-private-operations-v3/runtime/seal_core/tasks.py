from __future__ import annotations
import json, re, sqlite3, threading, uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ=ZoneInfo("Asia/Shanghai")
PLATFORMS={"xiaohongshu","douyin","bilibili","kuaishou","weixin-channels","zhihu"}
STAGES={"W1":[("W1.1","建档与目标对齐"),("W1.2","完整现状分析"),("W1.3","运营策略设计与校准"),("W1.4","内容规划"),("W1.5","内容生产与即时支持"),("W1.6","投放监控与复盘"),("W1.7","报告与滚动优化")],"W2":[("W2.1","目标和探索边界"),("W2.2","账号资产与问题诊断"),("W2.3","用户、赛道与竞品调研"),("W2.4","方向候选与可行性验证"),("W2.5","方向校准与验证计划"),("W2.6","形成探索报告并转运营")],"W3":[("W3.1","现状、目标与约束建档"),("W3.2","市场、用户与竞品研究"),("W3.3","定位、人设与经营路径"),("W3.4","冷启动路线与内容计划"),("W3.5","首批内容生产"),("W3.6","起号方案确认并转运营")]}
SAFE=re.compile(r"^[A-Za-z0-9_-]{1,100}$")
class TaskError(ValueError): pass
def _now(): return datetime.now(TZ).isoformat(timespec="seconds")
def _id(v):
    if not SAFE.fullmatch(v): raise TaskError("非法 task_id")
    return v

class TaskStore:
    """SQLite-backed, restart-safe task state for one V3 web process."""
    def __init__(self, root: str|Path):
        self.root=Path(root).expanduser().resolve(); self.root.mkdir(parents=True,exist_ok=True)
        self.db=self.root/"tasks.sqlite3"; self._lock=threading.RLock(); self._init()
    def _conn(self):
        c=sqlite3.connect(self.db,timeout=10,isolation_level=None); c.row_factory=sqlite3.Row; c.execute("PRAGMA journal_mode=WAL"); return c
    def _init(self):
        with self._conn() as c:
            c.executescript("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT, updated_at TEXT); CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, type TEXT NOT NULL, detail TEXT NOT NULL, at TEXT NOT NULL); CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id,id);")
    def _read(self,c,tid):
        r=c.execute("SELECT state FROM tasks WHERE id=?",(_id(tid),)).fetchone()
        if not r: raise TaskError(f"任务不存在: {tid}")
        return json.loads(r[0])
    def _write(self,c,s,event,detail=None):
        s["updated_at"]=_now(); c.execute("UPDATE tasks SET state=?,updated_at=? WHERE id=?",(json.dumps(s,ensure_ascii=False),s["updated_at"],s["task_id"])); c.execute("INSERT INTO events(task_id,type,detail,at) VALUES(?,?,?,?)",(s["task_id"],event,json.dumps(detail or {},ensure_ascii=False),s["updated_at"]))
    def create(self,title,platform,scenario="W1",account_id=None,goal="",conversation_id=None):
        if platform not in PLATFORMS: raise TaskError("不支持的平台")
        scenario=scenario.upper()
        if scenario not in STAGES: raise TaskError("scenario 仅支持 W1/W2/W3")
        if scenario!="W3" and not account_id: raise TaskError("W1/W2 必须提供账号ID")
        tid="task_"+uuid.uuid4().hex[:12]; t=_now(); stages=[{"id":i,"name":n,"status":"pending","completed_at":None,"skip_reason":None} for i,n in STAGES[scenario]]
        # Allocate the conversation atomically with task creation.  The web UI
        # must never create a task first and then bind a shared/old chat later.
        cid = (conversation_id or "").strip() or ("ops_" + uuid.uuid4().hex)
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", cid):
            raise TaskError("非法 conversation_id")
        s={"schema_version":"2.0","task_id":tid,"title":title.strip() or "未命名运营任务","platform":platform,"account_id":account_id,"account_ids":[account_id] if account_id else [],"scenario":scenario,"goal":goal,"conversation_id":cid,"status":"draft","current_stage_index":0,"stages":stages,"references":[],"artifacts":[],"decisions":[],"data_gaps":[] ,"created_at":t,"updated_at":t}
        with self._lock,self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            # A conversation can belong to at most one task in this store.
            for row in c.execute("SELECT state FROM tasks"):
                existing = json.loads(row[0])
                if existing.get("conversation_id") == cid:
                    raise TaskError("conversation_id 已绑定其他运营任务")
            c.execute("INSERT INTO tasks VALUES(?,?,?,?)",(tid,json.dumps(s,ensure_ascii=False),t,t)); c.execute("INSERT INTO events(task_id,type,detail,at) VALUES(?,?,?,?)",(tid,"TASK_CREATED",json.dumps({"scenario":scenario,"conversation_id":cid}),t)); c.commit()
        return s
    def get(self,tid):
        with self._conn() as c: return self._read(c,tid)
    def ensure_conversation(self, tid, conversation_id=None):
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE"); s = self._read(c, tid)
            requested = (conversation_id or "").strip()
            if requested and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", requested):
                raise TaskError("非法 conversation_id")
            if requested and requested != s.get("conversation_id"):
                for row in c.execute("SELECT state FROM tasks WHERE id<>?", (s["task_id"],)):
                    if json.loads(row[0]).get("conversation_id") == requested:
                        raise TaskError("conversation_id 已绑定其他运营任务")
                s["conversation_id"] = requested
                self._write(c, s, "CONVERSATION_BOUND", {"conversation_id": requested})
            if not s.get("conversation_id"):
                s["conversation_id"] = "ops_" + uuid.uuid4().hex
                self._write(c, s, "CONVERSATION_BOUND", {"conversation_id": s["conversation_id"]})
            c.commit(); return s
    def by_conversation(self, cid):
        if not cid:
            return None
        return next((s for s in self.list() if s.get("conversation_id") == cid), None)
    def events(self,tid):
        with self._conn() as c:
            self._read(c,tid); return [dict(r) for r in c.execute("SELECT id,type,detail,at FROM events WHERE task_id=? ORDER BY id",(_id(tid),))]
    def set_status(self,tid,status):
        if status not in {"draft","in_progress","waiting_confirmation","paused","blocked","completed","cancelled"}: raise TaskError("非法状态")
        with self._lock,self._conn() as c:
            c.execute("BEGIN IMMEDIATE"); s=self._read(c,tid); old=s["status"]
            allowed={"paused":{"in_progress"},"in_progress":{"paused","waiting_confirmation","blocked","completed","cancelled"},"draft":{"in_progress","cancelled"},"waiting_confirmation":{"in_progress","completed","cancelled"},"blocked":{"in_progress","cancelled"}}
            if old != status and status not in allowed.get(old,set()): raise TaskError(f"不允许状态迁移: {old} -> {status}")
            s["status"]=status; self._write(c,s,"STATUS_CHANGED",{"from":old,"to":status}); c.commit(); return s
    def complete_stage(self,tid,stage_id,decision=None):
        with self._lock,self._conn() as c:
            c.execute("BEGIN IMMEDIATE"); s=self._read(c,tid)
            if s["status"] in ("draft","paused","blocked","cancelled","completed"): raise TaskError("当前任务状态禁止阶段操作")
            i=next((i for i,x in enumerate(s["stages"]) if x["id"]==stage_id),-1)
            if i<0: raise TaskError("阶段不存在")
            if i!=s["current_stage_index"]: raise TaskError("只能完成当前阶段")
            if s["stages"][i]["status"] not in ("pending","in_progress"): raise TaskError("阶段不可完成")
            s["stages"][i]["status"]="completed"; s["stages"][i]["completed_at"]=_now()
            if decision: s["decisions"].append({"stage":stage_id,"text":decision,"at":_now()})
            self._write(c,s,"STAGE_COMPLETED",{"stage":stage_id}); c.commit(); return s
    def advance(self,tid,stage_id,skip=False,reason=None):
        with self._lock,self._conn() as c:
            c.execute("BEGIN IMMEDIATE"); s=self._read(c,tid)
            if s["status"] in ("paused","blocked","cancelled","completed"): raise TaskError("当前任务状态禁止阶段操作")
            i=next((i for i,x in enumerate(s["stages"]) if x["id"]==stage_id),-1); cur=s["current_stage_index"]
            if i<0 or i>cur+1: raise TaskError("不能跳跃阶段")
            if i>cur and s["stages"][cur]["status"] not in ("completed","skipped"): raise TaskError("当前阶段尚未完成")
            s["stages"][i]["status"]="skipped" if skip else "in_progress"; s["stages"][i]["skip_reason"]=reason if skip else None; s["current_stage_index"]=i; s["status"]="in_progress"; self._write(c,s,"STAGE_SKIPPED" if skip else "STAGE_STARTED",{"stage":stage_id}); c.commit(); return s
    def add_reference(self,tid,kind,value):
        if not value: raise TaskError("引用不能为空")
        with self._lock,self._conn() as c:
            c.execute("BEGIN IMMEDIATE"); s=self._read(c,tid); item={"kind":kind,"value":value,"at":_now()}
            if item not in s["references"]: s["references"].append(item); self._write(c,s,"REFERENCE_ADDED",item)
            c.commit(); return s

    def add_artifact(self, tid, kind, value, stage_id=None):
        """Link a locally produced artifact to a task with an auditable event."""
        if not kind or not value:
            raise TaskError("产物类型和地址不能为空")
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE"); s=self._read(c,tid)
            item={"kind":kind,"value":value,"stage_id":stage_id,"at":_now()}
            if item not in s["artifacts"]:
                s["artifacts"].append(item); self._write(c,s,"ARTIFACT_LINKED",item)
            c.commit(); return s

    def add_decision(self, tid, text, stage_id=None):
        if not text: raise TaskError("决策内容不能为空")
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE"); s=self._read(c,tid)
            item={"stage_id":stage_id,"text":text,"at":_now()}
            s["decisions"].append(item); self._write(c,s,"DECISION_RECORDED",item)
            c.commit(); return s
    def list(self):
        with self._conn() as c:
            return [json.loads(r[0]) for r in c.execute("SELECT state FROM tasks ORDER BY created_at DESC")]

    def delete(self, tid):
        """Delete task state/events and return its bound conversation for cleanup."""
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE"); state = self._read(c, tid)
            c.execute("DELETE FROM events WHERE task_id=?", (_id(tid),))
            c.execute("DELETE FROM tasks WHERE id=?", (_id(tid),)); c.commit()
        return {"ok": True, "task_id": tid, "conversation_id": state.get("conversation_id")}
