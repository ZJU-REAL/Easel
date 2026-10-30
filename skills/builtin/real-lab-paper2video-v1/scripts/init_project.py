#!/usr/bin/env python3
"""Copy a portable starter without modifying an existing project."""
import argparse
import shutil
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('destination',type=Path)
    args=p.parse_args()
    root=Path(__file__).resolve().parent.parent
    dest=args.destination.resolve()
    if dest.exists():p.error(f'Destination already exists: {dest}')
    shutil.copytree(root/'assets/project-template',dest)
    (dest/'scripts').mkdir()
    for name in ('render.cjs','verify_video.py','paper_assets.py'):
        shutil.copy2(root/'scripts'/name,dest/'scripts'/name)
    shutil.copytree(root/'vendor',dest/'vendor',ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
    for name in ('assets/figures','assets/audio','assets/meta','qa','renders'):
        (dest/name).mkdir(parents=True,exist_ok=True)
    print(f'Created {dest}\nThis is an 8-second DEMO. Replace its content and timeline before delivery.')

if __name__=='__main__':main()
