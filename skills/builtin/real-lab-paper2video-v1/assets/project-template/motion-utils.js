/* Pure, time-driven helpers. Coordinates use the design canvas, not viewport pixels. */
(function(root){
  const clamp=x=>Math.max(0,Math.min(1,x));
  const ease=x=>{x=clamp(x);return x*x*(3-2*x);};
  function imageContentRect(outer,source,padding=22){
    const [x,y,w,h]=outer,[sw,sh]=source;
    if(![...outer,...source,padding].every(Number.isFinite)||sw<=0||sh<=0||padding<0||w<=2*padding||h<=2*padding)
      throw Error('Invalid figure geometry');
    const scale=Math.min((w-2*padding)/sw,(h-2*padding)/sh);
    return {x:x+(w-sw*scale)/2,y:y+(h-sh*scale)/2,width:sw*scale,height:sh*scale,scale};
  }
  function mapHighlight(outer,source,rect,padding=22){
    const [x,y,w,h]=rect,[sw,sh]=source;
    if(!rect.every(Number.isFinite)||x<0||y<0||w<=0||h<=0||x+w>sw+1e-6||y+h>sh+1e-6)
      throw Error('Highlight lies outside source image');
    const b=imageContentRect(outer,source,padding);
    return {x:b.x+x*b.scale,y:b.y+y*b.scale,width:w*b.scale,height:h*b.scale};
  }
  function cueOpacity(t,start,end,fade=.18){
    if(end<=start||fade<=0)throw Error('Invalid cue timing');
    const f=Math.min(fade,(end-start)/2);
    return ease((t-start)/f)*ease((end-t)/f);
  }
  function transition(t,boundary,width=1920,duration=.64,copyFade=.24){
    if(width<=0||duration<=0||copyFade<=0||copyFade>duration)throw Error('Invalid transition parameters');
    const start=boundary-duration/2,end=boundary+duration/2;
    const p=ease((t-start)/duration),edge=width*(1-p);
    return {p,edge,oldClip:`inset(0px ${width-edge}px 0px 0px)`,
      newClip:`inset(0px 0px 0px ${edge}px)`,
      oldCopy:1-ease((t-start)/copyFade),newCopy:ease((t-end)/copyFade)};
  }
  function validateCues(cues){
    const sorted=[...cues].sort((a,b)=>a.start-b.start);
    for(let i=0;i<sorted.length;i++){
      const c=sorted[i];
      if(!Number.isFinite(c.start)||!Number.isFinite(c.end)||c.start<0||c.end<=c.start)throw Error('Invalid cue '+c.id);
      if(i&&c.start<sorted[i-1].end)throw Error('Simultaneous highlights: '+sorted[i-1].id+' / '+c.id);
    }
    return true;
  }
  const api={clamp,ease,imageContentRect,mapHighlight,cueOpacity,transition,validateCues};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.Motion=api;
})(typeof window==='undefined'?globalThis:window);
