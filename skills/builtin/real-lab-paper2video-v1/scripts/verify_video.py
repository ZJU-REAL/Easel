#!/usr/bin/env python3
"""Verify the encoded MP4. Technical success does not replace visual/audio review."""
import argparse
import hashlib
import json
import math
import re
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
import numpy as np
from PIL import Image

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('video',type=Path)
    p.add_argument('--duration',type=float,required=True)
    p.add_argument('--fps',type=float,default=30)
    p.add_argument('--width',type=int,default=1920)
    p.add_argument('--height',type=int,default=1080)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--references',type=Path,help='JSON list of {frame,path}; paths relative to this JSON')
    p.add_argument('--pixel-threshold',type=float,default=4)
    p.add_argument('--allow-silent',action='store_true',help='Only for intentionally silent engineering previews')
    args=p.parse_args()
    if not all(math.isfinite(x) and x>0 for x in (args.duration,args.fps,args.width,args.height,args.pixel_threshold)):
        p.error('Expected dimensions, timing and threshold must be positive and finite')
    video=args.video.resolve()
    def probe(*options):
        return json.loads(subprocess.check_output(['ffprobe','-v','error',*options,'-of','json',str(video)]))
    meta=probe('-show_format','-show_streams')
    v=next(s for s in meta['streams'] if s['codec_type']=='video')
    a=next((s for s in meta['streams'] if s['codec_type']=='audio'),None)
    timestamps=probe('-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time')['frames']
    pts=np.array([float(f['best_effort_timestamp_time']) for f in timestamps])
    expected=round(args.duration*args.fps)
    errors=[]
    fps=float(Fraction(v['avg_frame_rate']))
    duration=float(meta['format']['duration'])
    if (v['width'],v['height'])!=(args.width,args.height):errors.append('Unexpected dimensions')
    if abs(fps-args.fps)>1e-6:errors.append('Unexpected fps')
    if abs(duration-args.duration)>max(1/args.fps,.05):errors.append('Unexpected duration')
    if len(pts)!=expected:errors.append('Unexpected frame count')
    gaps=int(np.count_nonzero(np.abs(np.diff(pts)-1/args.fps)>1e-5))
    if gaps:errors.append('Nonuniform frame timestamp intervals')
    if len(pts) and abs(pts[0])>1/args.fps:errors.append('Video starts after frame zero')
    if not a and not args.allow_silent:errors.append('Missing audio track')
    black=[];uniform=[];flashes=[];n=0;prev=None;prevprev=None;lastdiff=0
    with tempfile.TemporaryFile() as stderr:
        proc=subprocess.Popen(['ffmpeg','-v','error','-i',str(video),'-map','0:v:0','-vf','scale=320:180,format=gray','-fps_mode','passthrough','-f','rawvideo','-'],stdout=subprocess.PIPE,stderr=stderr)
        while True:
            data=proc.stdout.read(320*180)
            if not data:break
            if len(data)!=320*180:
                errors.append('Incomplete decoded frame');break
            cur=np.frombuffer(data,np.uint8).astype(np.float32)
            if float(cur.mean())<4:black.append(n)
            if float(cur.std())<3:uniform.append(n)
            if prev is not None:
                diff=float(np.mean(np.abs(cur-prev)))
                if prevprev is not None and diff>8 and lastdiff>8 and float(np.mean(np.abs(cur-prevprev)))<2:
                    flashes.append(n-1)
                lastdiff=diff
            prevprev=prev;prev=cur;n+=1
        proc.stdout.close();code=proc.wait();stderr.seek(0);decode_errors=stderr.read().decode(errors='replace')
    if code or decode_errors:errors.append('Decode error')
    if n!=expected:errors.append('Decoded frame count mismatch')
    comparisons=[]
    if args.references:
        samples=json.loads(args.references.read_text())
        if not isinstance(samples,list) or not samples:raise ValueError('References must be a nonempty JSON list')
        indices=sorted(set(s['frame'] for s in samples))
        if any(not isinstance(i,int) or i<0 or i>=n for i in indices):raise ValueError('Reference frame outside video')
        with tempfile.TemporaryDirectory(prefix='paper2video-frames-') as temp:
            expr='+'.join(f'eq(n,{i})' for i in indices)
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(video),'-vf',f"select='{expr}'",'-fps_mode','vfr','-start_number','0',str(Path(temp)/'%06d.png')],check=True)
            mapping={frame:Path(temp)/f'{j:06d}.png' for j,frame in enumerate(indices)}
            for s in samples:
                ref=(args.references.parent/s['path']).resolve()
                actual=np.asarray(Image.open(mapping[s['frame']]).convert('RGB'),np.float32)
                reference=np.asarray(Image.open(ref).convert('RGB'),np.float32)
                if actual.shape!=reference.shape:
                    errors.append(f'Reference size mismatch at frame {s["frame"]}')
                    comparisons.append({**s,'error':'size mismatch'});continue
                value=float(np.mean(np.abs(actual-reference)))
                comparisons.append({**s,'mean_absolute_pixel_error':round(value,4)})
                if value>args.pixel_threshold:errors.append(f'Reference mismatch at frame {s["frame"]}')
    loudness=None
    if a:
        cp=subprocess.run(['ffmpeg','-hide_banner','-i',str(video),'-vn','-af','loudnorm=I=-14:TP=-1:LRA=7:print_format=json','-f','null','-'],capture_output=True,text=True)
        match=re.search(r'\{\s*"input_i".*?\}',cp.stderr,re.S)
        loudness=json.loads(match.group()) if match else {'error':'No measurement available'}
    digest=hashlib.sha256()
    with video.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    report={'video':str(video),'sha256':digest.hexdigest(),'duration':duration,'width':v['width'],'height':v['height'],'fps':fps,
        'expected_frames':expected,'timestamp_frames':len(pts),'decoded_frames':n,'timestamp_gaps':gaps,
        'audio':a and {k:a.get(k) for k in ('codec_name','sample_rate','channels')},'audio_loudness':loudness,
        'black_frame_flags':black,'uniform_frame_flags':uniform,'single_frame_flash_flags':flashes,
        'visual_review_required':bool(black or uniform or flashes),'decode_errors':decode_errors,
        'reference_comparisons':comparisons,'technical_errors':errors,'technical_pass':not errors,
        'scope':'Automatic measurements only; not a claim of full visual inspection or audio listening.'}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('technical_pass','technical_errors','decoded_frames','visual_review_required')},ensure_ascii=False))
    return 0 if not errors else 1

if __name__=='__main__':raise SystemExit(main())
