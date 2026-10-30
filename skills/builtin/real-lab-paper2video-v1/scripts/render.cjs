#!/usr/bin/env node
/* node render.cjs PROJECT OUTPUT [--start-frame N --end-frame N | --still-frame N]
 * [--scale .5] [--allow-demo] [--overwrite] */
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const {pathToFileURL}=require('url'),{spawn}=require('child_process'),{once}=require('events');
async function main(){
 const args=process.argv.slice(2),project=args.shift(),output=args.shift();
 if(!project||!output)throw Error('Usage: node render.cjs PROJECT OUTPUT [--start-frame N --end-frame N | --still-frame N] [--scale .5] [--allow-demo] [--overwrite]');
 const opt={};
 while(args.length){const key=args.shift();
  if(['--allow-demo','--overwrite'].includes(key))opt[key]=true;
  else if(['--start-frame','--end-frame','--still-frame','--scale'].includes(key))opt[key]=Number(args.shift());
  else throw Error('Unknown option '+key);
 }
 const root=path.resolve(project),dest=path.resolve(output),cfg=JSON.parse(fs.readFileSync(path.join(root,'project.json'),'utf8'));
 const temp=dest+`.partial-${process.pid}`+path.extname(dest);
 if(cfg.demo&&!opt['--allow-demo'])throw Error('Demo project: replace its content, set demo=false, or use --allow-demo for an engineering test.');
 const {width,height,fps,duration}=cfg;
 if(![width,height,fps,duration].every(x=>Number.isFinite(x)&&x>0))throw Error('Invalid project dimensions/fps/duration');
 const total=Math.round(duration*fps),first=opt['--start-frame']??0,last=opt['--end-frame']??total;
 const still=opt['--still-frame'];
 if(!Number.isInteger(first)||!Number.isInteger(last)||first<0||last>total||first>=last)throw Error('Invalid half-open frame range');
 if(still!==undefined&&(!Number.isInteger(still)||still<0||still>=total))throw Error('Invalid still frame');
 const scale=opt['--scale']??1;
 if(!Number.isFinite(scale)||scale<=0)throw Error('Invalid scale');
 const w=Math.max(2,2*Math.round(width*scale/2)),h=Math.max(2,2*Math.round(height*scale/2));
 if(fs.existsSync(dest)&&!opt['--overwrite'])throw Error('Output exists; use a new versioned filename or --overwrite: '+dest);
 fs.mkdirSync(path.dirname(dest),{recursive:true});
 let pw;try{pw=require(process.env.PLAYWRIGHT_MODULE||'playwright');}catch{throw Error('Playwright unavailable. Install locally or set PLAYWRIGHT_MODULE to the available module path.');}
 let browser,ff,stderr='',pageErrors=[];
 try{
  browser=await pw.chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL||'chrome',args:['--disable-gpu','--disable-lcd-text','--font-render-hinting=none','--force-color-profile=srgb']});
  const page=await browser.newPage({viewport:{width:w,height:h},deviceScaleFactor:1});
  page.on('pageerror',e=>pageErrors.push(String(e)));
  const entry=path.join(root,cfg.entry||'index.html');
  await page.goto(pathToFileURL(entry).href);
  await page.waitForFunction(()=>window.ready===true||window.loadError);
  const state=await page.evaluate(()=>({error:window.loadError,duration:window.TIMELINE?.duration}));
  if(state.error)throw Error(state.error);
  if(state.duration!==undefined&&Math.abs(state.duration-duration)>1e-6)throw Error('project.json and timeline duration disagree');
  async function frame(n){await page.evaluate(t=>window.render(t),n/fps);if(pageErrors.length)throw Error(pageErrors.join('\n'));return page.screenshot({type:'png'});}
  if(still!==undefined){fs.writeFileSync(temp,await frame(still));}
  else{
   ff=spawn('ffmpeg',['-v','error','-y','-f','image2pipe','-framerate',String(fps),'-i','-','-an','-c:v','libx264','-preset','fast','-crf','17','-pix_fmt','yuv420p','-r',String(fps),'-frames:v',String(last-first),'-movflags','+faststart',temp],{stdio:['pipe','ignore','pipe']});
   ff.stderr.on('data',b=>stderr+=b.toString());ff.stdin.on('error',()=>{});
   let failed;
   const done=new Promise(resolve=>{ff.on('error',e=>{failed=e;resolve(-1)});ff.on('close',resolve)});
   for(let n=first;n<last;n++){
    if(failed||ff.exitCode!==null||ff.stdin.destroyed)throw failed||Error('FFmpeg stopped: '+stderr);
    if(!ff.stdin.write(await frame(n)))await Promise.race([once(ff.stdin,'drain'),done.then(()=>{throw Error('FFmpeg stopped: '+stderr)})]);
   }
   ff.stdin.end();const code=await done;if(code!==0)throw failed||Error('FFmpeg exit '+code+': '+stderr);
  }
  fs.renameSync(temp,dest);
  fs.writeFileSync(dest+'.render.json',JSON.stringify({project:root,output:dest,width:w,height:h,fps,firstFrame:still??first,endFrameExclusive:still!==undefined?still+1:last,frames:still!==undefined?1:last-first,entrySha256:crypto.createHash('sha256').update(fs.readFileSync(entry)).digest('hex'),createdAt:new Date().toISOString(),demo:!!cfg.demo},null,2));
  console.log(JSON.stringify({output:dest,frames:still!==undefined?1:last-first,width:w,height:h,fps}));
 }catch(e){if(ff&&!ff.killed)ff.kill('SIGTERM');if(fs.existsSync(temp))fs.unlinkSync(temp);throw e;}
 finally{if(browser)await browser.close();}
}
main().catch(e=>{console.error(e.message);process.exit(1)});
