#!/usr/bin/env python3
import argparse, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "runtime"))
from seal_core.tasks import TaskStore, TaskError
def main():
 p=argparse.ArgumentParser(); p.add_argument('--data-root'); q=p.add_subparsers(dest='cmd',required=True)
 c=q.add_parser('create'); c.add_argument('--title',required=True); c.add_argument('--platform',required=True); c.add_argument('--scenario',default='W1'); c.add_argument('--account-id'); c.add_argument('--goal',default=''); c.add_argument('--conversation-id')
 s=q.add_parser('status'); s.add_argument('--task-id',required=True)
 e=q.add_parser('events'); e.add_argument('--task-id',required=True)
 x=q.add_parser('set-status'); x.add_argument('--task-id',required=True); x.add_argument('--action',required=True)
 a=q.add_parser('advance'); a.add_argument('--task-id',required=True); a.add_argument('--stage-id',required=True); a.add_argument('--skip',action='store_true'); a.add_argument('--reason')
 d=q.add_parser('complete-stage'); d.add_argument('--task-id',required=True); d.add_argument('--stage-id',required=True); d.add_argument('--decision')
 r=q.add_parser('add-ref'); r.add_argument('--task-id',required=True); r.add_argument('--kind',required=True); r.add_argument('--value',required=True)
 a=p.parse_args(); store=TaskStore(a.data_root or os.environ.get('SEAL_DATA_ROOT',str(Path(__file__).parents[1]/'runtime'/'outputs'/'_ops_tasks')))
 if a.cmd=='create': out=store.create(a.title,a.platform,a.scenario,a.account_id,a.goal,a.conversation_id)
 elif a.cmd=='status': out=store.get(a.task_id)
 elif a.cmd=='events': out=store.events(a.task_id)
 elif a.cmd=='set-status': out=store.set_status(a.task_id,a.action)
 elif a.cmd=='advance': out=store.advance(a.task_id,a.stage_id,a.skip,a.reason)
 elif a.cmd=='complete-stage': out=store.complete_stage(a.task_id,a.stage_id,a.decision)
 else: out=store.add_reference(a.task_id,a.kind,a.value)
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try: main()
 except TaskError as e: raise SystemExit(f'错误: {e}')
