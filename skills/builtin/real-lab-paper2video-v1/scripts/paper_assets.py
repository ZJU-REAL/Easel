#!/usr/bin/env python3
"""Use the bundled paper2assets tools; no separately installed skill is needed."""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

COMMANDS={
    'source':'source_figures.py', 'extract':'extract_pdf.py',
    'crop':'crop_figure.py', 'package':'build_package.py',
    'qr':'make_qr.py', 'logos':'fetch_logos.py', 'venue-logo':'fetch_conf_logo.py',
}

def check():
    core_modules={'pymupdf':'fitz','pillow':'PIL','numpy':'numpy'}
    modules={name:importlib.util.find_spec(module) is not None for name,module in core_modules.items()}
    commands={name:shutil.which(name) for name in ('pdftotext','pdftoppm')}
    optional={name:importlib.util.find_spec(name) is not None for name in ('qrcode','cairosvg','playwright')}
    optional['ghostscript']=shutil.which('gs') or shutil.which('ps2pdf')
    report={'python':sys.version.split()[0], 'core_python_modules':modules,'core_commands':commands,
            'optional':optional,'arxiv_source_tar_filter':sys.version_info>=(3,12),
            'core_ready':sys.version_info>=(3,10) and all(modules.values()) and all(commands.values()),
            'note':'Read-only capability check; no packages installed and no network calls.'}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['core_ready'] else 1

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['check',*COMMANDS])
    parser.add_argument('arguments',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    if args.command=='check':return check()
    root=Path(__file__).resolve().parent.parent
    scripts=root/'vendor/paper2assets/scripts'
    target=scripts/COMMANDS[args.command]
    if not target.is_file():parser.error(f'Bundled tool missing: {target}')
    extra=list(args.arguments)
    # Upstream assumes a repository with skills/paper2assets. Pin the local extractor.
    if args.command=='package' and not any(x=='--extractor' or x.startswith('--extractor=') for x in extra):
        extra+=['--extractor',str(scripts/'extract_pdf.py')]
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run([sys.executable,str(target),*extra],env=env).returncode

if __name__=='__main__':raise SystemExit(main())
