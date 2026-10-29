// Lightweight offline point-cloud renderer. No external assets or WebGL dependency.
export function transformPoint(matrix, point) {
  return matrix.slice(0, 3).map(row => row[0]*point[0] + row[1]*point[1] + row[2]*point[2] + row[3]);
}

export function multiplyMatrices(a, b) {
  return a.map(row => b[0].map((_, j) => row.reduce((sum, value, k) => sum + value*b[k][j], 0)));
}

export class CloudView {
  constructor(canvas) {
    this.canvas = canvas; this.context = canvas.getContext('2d');
    this.frame = null; this.state = null; this.selection = null; this.coordinates = 'camera';
    this.yaw = -0.65; this.pitch = 0.65; this.zoom = 1; this.center = [0,0,0]; this.extent = 1;
    this.drag = null;
    canvas.addEventListener('pointerdown', e => { this.drag = [e.clientX,e.clientY]; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener('pointermove', e => {
      if (!this.drag) return;
      this.yaw += (e.clientX-this.drag[0])*.008;
      this.pitch = Math.max(-1.4, Math.min(1.4, this.pitch+(e.clientY-this.drag[1])*.008));
      this.drag = [e.clientX,e.clientY]; this.draw();
    });
    canvas.addEventListener('pointerup', () => { this.drag = null; });
    canvas.addEventListener('pointercancel', () => { this.drag = null; });
    canvas.addEventListener('wheel', e => { e.preventDefault(); this.zoom = Math.max(.25,Math.min(5,this.zoom*Math.exp(e.deltaY*.001))); this.draw(); }, {passive:false});
    canvas.addEventListener('dblclick', () => this.reset());
    this.observer = new ResizeObserver(() => this.draw()); this.observer.observe(canvas.parentElement);
  }
  update(frame, state, selection, coordinates = this.coordinates) {
    const refit = !this.frame || this.frame.source !== frame.source || this.coordinates !== coordinates;
    this.frame = frame; this.state = state; this.selection = selection; this.coordinates = coordinates;
    const matrix = this.matrix();
    this.points = frame.points.map(p => this.display(matrix ? transformPoint(matrix,p) : p));
    if (refit || !this.points.length) this.fit();
    this.draw();
  }
  matrix() { return this.coordinates === 'base' ? this.state?.base_from_camera : null; }
  display(p) { return this.coordinates === 'base' ? [...p] : [p[0],p[2],-p[1]]; }
  fit() {
    if (!this.points?.length) { this.center=[0,0,0]; this.extent=1; return; }
    const min=[Infinity,Infinity,Infinity], max=[-Infinity,-Infinity,-Infinity];
    for (const p of this.points) for(let i=0;i<3;i++){ min[i]=Math.min(min[i],p[i]); max[i]=Math.max(max[i],p[i]); }
    this.center=min.map((v,i)=>(v+max[i])/2); this.extent=Math.max(...min.map((v,i)=>max[i]-v),.15);
  }
  reset(){ this.yaw=-.65;this.pitch=.65;this.zoom=1;this.fit();this.draw(); }
  project(p){
    const [x,y,z]=p.map((v,i)=>v-this.center[i]); const cy=Math.cos(this.yaw),sy=Math.sin(this.yaw);
    const forward=sy*x+cy*y, horizontal=cy*x-sy*y;
    const vertical=Math.cos(this.pitch)*z-Math.sin(this.pitch)*forward;
    const depth=Math.cos(this.pitch)*forward+Math.sin(this.pitch)*z;
    const distance=this.extent*1.85*this.zoom;
    if(distance-depth<=.015)return null;
    const scale=Math.min(this.width,this.height)*1.3/(distance-depth);
    return [this.width/2+horizontal*scale,this.height*.5-vertical*scale,depth,scale];
  }
  line(a,b,color,width=1,dashed=false){
    const p=this.project(a),q=this.project(b);if(!p||!q)return;
    const ctx=this.context;ctx.strokeStyle=color;ctx.lineWidth=width;ctx.setLineDash(dashed?[4,5]:[]);
    ctx.beginPath();ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1]);ctx.stroke();ctx.setLineDash([]);
  }
  label(p,text,color='#bfd2de',offset=0){
    const q=this.project(p);if(!q)return;const ctx=this.context;ctx.font='9px Consolas, monospace';ctx.fillStyle=color;ctx.fillText(text,q[0]+7,q[1]-7+offset);
  }
  axis(origin,matrix,length,prefix){
    const colors=['#e98282','#70dbbc','#70b4e5'];
    const base=this.display(matrix?transformPoint(matrix,origin):origin);
    for(let i=0;i<3;i++){
      const end=[...origin];end[i]+=length;
      const point=this.display(matrix?transformPoint(matrix,end):end);
      this.line(base,point,colors[i],1.7);this.label(point,['X','Y','Z'][i],colors[i]);
    }
    this.label(base,prefix,'#8ba6b8',26);
  }
  draw(){
    const rect=this.canvas.parentElement.getBoundingClientRect();if(rect.width<1||rect.height<1)return;
    const dpr=window.devicePixelRatio||1;this.width=rect.width;this.height=rect.height;
    this.canvas.width=Math.round(rect.width*dpr);this.canvas.height=Math.round(rect.height*dpr);
    const ctx=this.context;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.fillStyle='#101922';ctx.fillRect(0,0,this.width,this.height);
    if(!this.frame)return;
    const floor=this.coordinates==='base'?0:this.center[2]-.14;
    const step=this.extent<1?.05:.1; const half=Math.max(.4,this.extent);
    for(let i=-10;i<=10;i++){
      const delta=i*step;
      this.line([this.center[0]-half,this.center[1]+delta,floor],[this.center[0]+half,this.center[1]+delta,floor],'#22333f');
      this.line([this.center[0]+delta,this.center[1]-half,floor],[this.center[0]+delta,this.center[1]+half,floor],'#22333f');
    }
    const projected=this.points.map((p,i)=>({p:this.project(p),c:this.frame.colors[i]})).filter(v=>v.p).sort((a,b)=>a.p[2]-b.p[2]);
    for(const {p,c} of projected){
      if(p[0]<-3||p[0]>this.width+3||p[1]<-3||p[1]>this.height+3)continue;
      ctx.fillStyle=`rgb(${c.join(',')})`;const size=Math.max(1.5,Math.min(4,this.extent*.008*p[3]));ctx.fillRect(p[0]-size/2,p[1]-size/2,size,size);
    }
    const matrix=this.matrix();
    this.axis([0,0,0],matrix,.07,'CAM');
    if(this.coordinates==='base')this.axis([0,0,0],null,.09,'BASE');
    if(this.selection){
      const selected=this.display(matrix?transformPoint(matrix,this.selection.camera_m):this.selection.camera_m);
      const q=this.project(selected);
      if(q){ctx.beginPath();ctx.arc(q[0],q[1],6,0,Math.PI*2);ctx.strokeStyle='#b3ffe6';ctx.lineWidth=2;ctx.stroke();ctx.fillStyle='#ecfff9';ctx.fillRect(q[0]-1.5,q[1]-1.5,3,3);this.label(selected,'SELECTED','#b3ffe6',18);}
      if(this.coordinates==='base' && matrix){
        const surface=[...selected];surface[2]+=(this.state.session.surface_offset_mm||0)/1000;
        const approach=[...surface];approach[2]+=(this.state.session.clearance_mm||0)/1000;
        this.line(surface,approach,'#edb974',1.5,true);this.label(approach,'APPROACH','#edb974');
        const half=.018;
        this.line([approach[0]-half,approach[1],approach[2]],[approach[0]+half,approach[1],approach[2]],'#edb974',2);
        for(const sign of [-1,1])this.line([approach[0]+sign*half,approach[1],approach[2]],[approach[0]+sign*half,approach[1],approach[2]-.025],'#edb974',2);
      }
    }
  }
}
