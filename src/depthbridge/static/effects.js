// Bounded ambient renderer: no network assets, no pointer interception, 30 fps maximum.
const canvas=document.getElementById('ambient-particles');
const ctx=canvas.getContext('2d');
const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
const root=document.documentElement;
let stored={};
try{stored=JSON.parse(localStorage.getItem('depthbridge-appearance')||'{}');}catch{/* Storage may be disabled. */}
let motion=!reduced.matches&&(stored.motion??true),particles=stored.particles??true;
let raf=0,lastTime=0,width=0,height=0,pointer={x:-1000,y:-1000};
const dots=Array.from({length:180},(_,i)=>({x:(i%60)/59,row:Math.floor(i/60),r:.65+(i%5)*.13}));

function resize(){width=window.innerWidth;height=340;const ratio=Math.min(window.devicePixelRatio||1,1.5);canvas.width=width*ratio;canvas.height=height*ratio;ctx.setTransform(ratio,0,0,ratio,0,0);}
function tick(time){
  raf=0;if(!motion||!particles||document.hidden)return;
  const elapsed=time-lastTime;
  if(elapsed>=33){
    lastTime=time;ctx.clearRect(0,0,width,height);
    const compact=width<800,origin=compact?width*.55:width*.36,span=compact?width*.42:width*.43;
    for(const dot of dots){
      const x=origin+dot.x*span,phase=dot.x*9-time*.0005+dot.row*.4;
      const y=compact?155+Math.sin(phase)*14+dot.row*7:181+Math.sin(phase)*21+dot.row*9;
      const near=Math.max(0,1-Math.hypot(pointer.x-x,pointer.y-y)/150);
      const envelope=Math.sin(dot.x*Math.PI);
      ctx.fillStyle=`rgba(53,85,232,${envelope*(.17+near*.28)})`;
      ctx.beginPath();ctx.arc(x,y-near*8,dot.r+near*.5,0,Math.PI*2);ctx.fill();
    }
  }
  raf=requestAnimationFrame(tick);
}
function synchronize(){
  root.dataset.motion=motion?'on':'off';root.dataset.particles=motion&&particles?'on':'off';
  document.getElementById('motion-enabled').checked=motion;
  document.getElementById('particles-enabled').checked=particles;
  document.getElementById('particles-enabled').disabled=!motion;
  document.getElementById('motion-hint').textContent=reduced.matches?'已遵循系统的减少动态效果设置':'偏好自动保存在这台浏览器中';
  cancelAnimationFrame(raf);raf=0;ctx.clearRect(0,0,width,height);lastTime=0;
  if(motion&&particles&&!document.hidden)raf=requestAnimationFrame(tick);
  try{localStorage.setItem('depthbridge-appearance',JSON.stringify({motion,particles}));}catch{/* Keep controls usable without storage. */}
}
document.getElementById('motion-enabled').addEventListener('change',event=>{motion=event.target.checked&&!reduced.matches;synchronize();});
document.getElementById('particles-enabled').addEventListener('change',event=>{particles=event.target.checked;synchronize();});
reduced.addEventListener('change',event=>{if(event.matches)motion=false;synchronize();});
window.addEventListener('resize',resize,{passive:true});
document.addEventListener('visibilitychange',synchronize);
document.addEventListener('pointermove',event=>{pointer={x:event.clientX,y:event.clientY};},{passive:true});
document.addEventListener('pointerdown',event=>{
  if(!motion)return;
  const target=event.target.closest('button,.button');
  if(!target||target.disabled)return;
  const rect=target.getBoundingClientRect(),ripple=document.createElement('span');
  ripple.className='interaction-ripple';ripple.style.left=`${event.clientX-rect.left}px`;ripple.style.top=`${event.clientY-rect.top}px`;
  ripple.setAttribute('aria-hidden','true');target.append(ripple);ripple.addEventListener('animationend',()=>ripple.remove(),{once:true});
  // Closing a dialog or hiding a tab may cancel animationend; always release the node.
  setTimeout(()=>ripple.remove(),750);
},{passive:true});
resize();synchronize();
export const effects={
  get motion(){return motion;},
  reveal(element){if(motion&&element)element.animate([{opacity:.3},{opacity:1}],{duration:260,easing:'ease-out'});},
  flash(element){if(!motion||!element)return;element.classList.remove('frame-updated');void element.offsetWidth;element.classList.add('frame-updated');}
};
