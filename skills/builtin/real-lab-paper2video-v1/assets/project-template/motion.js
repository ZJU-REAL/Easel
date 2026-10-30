const {ease,transition}=Motion;
const TL=window.TIMELINE,film=document.getElementById('film');
const duration=.64,copyFade=.24;
window.ready=false;
function paintScene(scene,t){
  if(scene.id==='opening'){
    const u=t-scene.start;
    document.getElementById('concept-a').style.opacity=ease(u/.7);
    document.getElementById('concept-b').style.opacity=ease((u-1.5)/.7);
    const line=document.getElementById('concept-link'),p=ease((u-.8)/.8);
    line.style.opacity=p;line.style.strokeDasharray='1';line.style.strokeDashoffset=1-p;
  }
  // Add paper-specific deterministic animations and source-coordinate highlights here.
}
window.render=function(t){
  t=Math.max(0,Math.min(TL.duration-1e-6,t));
  film.style.transform=`scale(${Math.min(innerWidth/1920,innerHeight/1080)})`;
  const i=TL.scenes.findIndex(s=>t>=s.start&&t<s.end);
  if(i<0)throw Error('Timeline gap at '+t);
  for(const el of document.querySelectorAll('.scene')){
    el.classList.remove('active');el.querySelector('.visual').style.clipPath='none';el.querySelector('.copy').style.opacity=1;
  }
  const k=TL.scenes.findIndex((s,j)=>j>0&&Math.abs(t-s.start)<duration/2);
  if(k>0){
    const old=TL.scenes[k-1],next=TL.scenes[k],a=document.getElementById(old.id),b=document.getElementById(next.id);
    const z=transition(t,next.start,1920,duration,copyFade);
    a.classList.add('active');b.classList.add('active');
    a.querySelector('.visual').style.clipPath=z.oldClip;b.querySelector('.visual').style.clipPath=z.newClip;
    a.querySelector('.copy').style.opacity=z.oldCopy;b.querySelector('.copy').style.opacity=0;
    paintScene(old,t);paintScene(next,t);
  }else{
    const sc=TL.scenes[i],el=document.getElementById(sc.id);el.classList.add('active');paintScene(sc,t);
    el.querySelector('.copy').style.opacity=i===0?1:ease((t-sc.start-duration/2)/copyFade);
  }
  const sub=TL.subtitles.find(s=>t>=s.start&&t<s.end);
  document.getElementById('caption').textContent=sub?sub.text:'';
  document.getElementById('counter').textContent=String(i+1).padStart(2,'0')+' / '+String(TL.scenes.length).padStart(2,'0');
  document.getElementById('progress').style.width=t/TL.duration*1920+'px';
};
Promise.all([document.fonts.ready,...Array.from(document.images).map(im=>im.decode())])
 .then(()=>{render(0);window.ready=true;}).catch(e=>{window.loadError=String(e);});
