import {CloudView, multiplyMatrices, transformPoint} from './cloud.js';
import {effects} from './effects.js';

const $ = id => document.getElementById(id);
let frame=null,state=null,selected=null,images={},imageMode='color',live=false,liveTimer=null,captureEpoch=0,boardObservation=null;
const cloud=new CloudView($('cloud-canvas'));
const titles={workbench:['空间测量','INSPECT'],calibration:['坐标标定','CALIBRATE'],validation:['误差验证','VALIDATE']};
let toastTimer;
function toast(message,error=false){
  $('toast').textContent=message;$('toast').className=`visible${error?' error':''}`;clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>{$('toast').className='';},error?8500:4000);
}
function run(callback){return async(...args)=>{try{await callback(...args);}catch(error){toast(error.message||String(error),true);}};}
async function api(url,method='GET',body){
  const options={method};
  if(body!==undefined){options.headers={'Content-Type':'application/json'};options.body=JSON.stringify(body);}
  const response=await fetch(url,options);const value=await response.json();
  if(!response.ok){const detail=value.detail;throw new Error(typeof detail==='string'?detail:JSON.stringify(detail||value));}
  return value;
}
function fmt(value,digits=2){return Number.isFinite(value)?value.toFixed(digits):'—';}
function xyz(point){return point?point.map(v=>fmt(v*1000,1)).join(', '):'尚未标定';}
function escapeHtml(text){return String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function setTab(name){
  if(!titles[name])return;
  document.querySelectorAll('.tab').forEach(e=>e.classList.toggle('active',e.id===`tab-${name}`));
  document.querySelectorAll('.nav').forEach(e=>e.classList.toggle('active',e.dataset.tab===name));
  document.querySelectorAll('.nav').forEach(e=>e.setAttribute('aria-current',e.dataset.tab===name?'page':'false'));
  $('page-title').innerHTML=`${titles[name][0]}<span> / ${titles[name][1]}</span>`;
  requestAnimationFrame(()=>cloud.draw());
  effects.reveal($(`tab-${name}`));
}
document.querySelectorAll('[data-tab]').forEach(e=>e.addEventListener('click',()=>setTab(e.dataset.tab)));
function stopLive(){live=false;clearTimeout(liveTimer);captureEpoch++;$('live-toggle').textContent='实时预览';updateActivity();}
function closeDialogs(){document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());}
document.querySelectorAll('[data-open]').forEach(button=>button.addEventListener('click',()=>$(button.dataset.open).showModal()));
document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}}));
function clearFrame(){
  frame=null;images={};selected=null;boardObservation=null;
  $('image-canvas').getContext('2d').clearRect(0,0,$('image-canvas').width,$('image-canvas').height);
  cloud.frame=null;cloud.points=[];cloud.selection=null;cloud.draw();
  ['metric-resolution','metric-valid','metric-frame','metric-time','cloud-count'].forEach(id=>$(id).textContent='—');
  ['download-frame','download-cloud'].forEach(id=>{$(id).setAttribute('aria-disabled','true');$(id).tabIndex=-1;});
}
function loadImage(src){return new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(new Error('图像加载失败'));image.src=src;});}
async function applyPacket(packet,epoch=captureEpoch){
  if(!packet.frame){clearFrame();setState(packet.state);return;}
  const [color,depth]=await Promise.all([loadImage(packet.frame.color),loadImage(packet.frame.depth)]);
  if(epoch!==captureEpoch)return;
  frame=packet.frame;images={color,depth};boardObservation=null;
  $('image-canvas').width=frame.width;$('image-canvas').height=frame.height;
  $('metric-resolution').textContent=`${frame.width} × ${frame.height}`;
  $('metric-valid').textContent=`${frame.valid_percent.toFixed(1)} %`;
  $('metric-frame').textContent=`# ${String(frame.frame_id).padStart(4,'0')}`;
  $('metric-time').textContent=new Date(frame.timestamp*1000).toLocaleTimeString();
  $('frame-source-label').textContent=state?.source==='import'?'导入数据':frame.source==='demo'?'合成数据':frame.serial;
  $('cloud-count').textContent=`${frame.points.length.toLocaleString()} points`;
  $('download-frame').href=`/api/frames/${frame.frame_id}/archive`;
  $('download-cloud').href=`/api/frames/${frame.frame_id}/cloud.ply`;
  ['download-frame','download-cloud'].forEach(id=>{$(id).removeAttribute('aria-disabled');$(id).tabIndex=0;});
  selected=null;
  setState(packet.state);drawImage();
  updateImageModeLabel();
  effects.flash(document.querySelector('.image-panel'));
}
async function capture(){const epoch=captureEpoch;await applyPacket(await api('/api/frames','POST'),epoch);}
async function liveLoop(){
  if(!live)return;
  try{await capture();}catch(error){stopLive();toast(error.message,true);}
  if(live)liveTimer=setTimeout(liveLoop,400);
}
function currentBase(){
  if(!selected)return null;
  if(state.session.mode==='eye_in_hand'){
    if(!selected.base_from_tool_at_capture||!state.session.extrinsic)return null;
    return transformPoint(multiplyMatrices(selected.base_from_tool_at_capture,state.session.extrinsic),selected.camera_m);
  }
  return state.base_from_camera?transformPoint(state.base_from_camera,selected.camera_m):null;
}
function setState(value){
  state=value;const session=state.session;
  if(selected&&!session.selections.some(p=>p.id===selected.id))selected=null;
  const connected=state.source==='realsense',idle=['idle','disconnected'].includes(state.source);
  document.body.dataset.source=state.source;
  $('source-name').textContent=connected?(frame?.description.split(' · ')[0]||'Intel RealSense D435'):state.source==='demo'?'示例模式':state.source==='import'?'RGB-D 文件回放':'连接深度相机';
  $('source-desc').textContent=connected?state.source_id.replace('realsense:','SN '):state.source==='demo'?'合成 RGB-D · 独立会话':state.source==='import'?'记录帧 · 独立会话':'Intel RealSense · RGB-D';
  $('source-dot').className=`dot ${connected?'mint':session.synthetic?'amber':''}`;
  $('source-status').textContent=connected?'已连接':state.source==='demo'?'示例':state.source==='import'?'回放':'待连接';
  $('source-status').classList.toggle('connected',connected);
  $('header-device-name').textContent=connected?'RealSense D435':'连接相机';
  $('device-launch').classList.toggle('connected',connected);
  $('device-controls').hidden=connected;$('disconnect-camera').hidden=!connected;
  $('device-message').textContent=connected?'深度已对齐 RGB · 设备就绪':idle?'选择相机后连接，开始采集真实空间':'可随时连接相机，返回真实测量';
  if(connected){const serial=state.source_id.replace('realsense:','');if(!Array.from($('device-select').options).some(o=>o.value===serial))$('device-select').add(new Option(`D435 / ${serial}`,serial));$('device-select').value=serial;}
  $('source-banner').className=`source-banner ${idle?'idle':session.synthetic?'demo':'real'}`;
  $('source-banner').querySelector('.badge').className=`badge ${session.synthetic?'amber':idle?'':'mint'}`;
  $('source-banner').querySelector('.badge').textContent=idle?'WAITING':session.synthetic?'SYNTHETIC':connected?'LIVE CAMERA':'RECORDED';
  $('image-empty').hidden=!!frame;$('cloud-empty').hidden=!!frame;
  $('capture-frame').disabled=idle;
  $('source-session-count').textContent=`${session.selections.length} 个测量点`;
  $('live-toggle').disabled=state.source!=='realsense';
  $('metric-transform').textContent=session.extrinsic?session.label:'尚未标定';$('metric-transform').className='long';
  $('metric-direction').textContent=session.mode==='eye_to_hand'?'相机 → 机械臂基座':'相机 → 末端 → 基座';
  $('transform-label').textContent=session.label;
  $('mount-mode').value=session.mode;updateMountDescription();
  if(document.activeElement!==$('transform-matrix'))$('transform-matrix').value=session.extrinsic?JSON.stringify(session.extrinsic.map(r=>r.map(v=>Number(v.toFixed(8)))),null,0).replace(/\],\[/g,'],\n ['):'';
  if(document.activeElement!==$('robot-pose'))$('robot-pose').value=session.base_from_tool?JSON.stringify(session.base_from_tool):'';
  if(document.activeElement!==$('clearance'))$('clearance').value=session.clearance_mm;
  if(document.activeElement!==$('surface-offset'))$('surface-offset').value=session.surface_offset_mm;
  $('fit-rms').innerHTML=`${fmt(session.fit?.rms_mm,3)} <small>mm</small>`;
  $('calibration-count').textContent=session.pairs.filter(p=>p.role==='calibration').length;
  $('validation-count').textContent=state.validation.count;
  $('validation-rms').textContent=fmt(state.validation.rms_mm,3);$('validation-max').textContent=fmt(state.validation.max_mm,3);
  document.querySelectorAll('.demo-only').forEach(e=>e.hidden=state.source!=='demo');
  const recent=session.selections.slice(-6).reverse();
  $('recent-points').innerHTML=recent.length?recent.map((p,i)=>`<tr><td>P${session.selections.length-i}</td><td class="mono">${p.pixel.join(', ')}</td><td class="mono">${fmt(p.depth_m*1000)}</td><td class="mono">${xyz(p.camera_m)}</td><td class="mono">${xyz(p.base_m)}</td></tr>`).join(''):'<tr><td colspan="5" class="empty">点击图像开始测量</td></tr>';
  $('pairs-table').innerHTML=session.pairs.length?session.pairs.map((p,i)=>`<tr><td>${escapeHtml(p.label||`P${i+1}`)}</td><td><span class="${p.role==='validation'?'amber':'mint'}">${p.role==='validation'?'验证':'标定'}</span></td><td class="mono">${p.pixel.join(', ')}</td><td class="mono">${xyz(p.camera_m)}</td><td class="mono">${xyz(p.base_m)}</td><td class="mono">${fmt(p.error_mm,3)}</td><td><button class="text-button" data-delete-pair="${p.id}">移除</button></td></tr>`).join(''):'<tr><td colspan="7" class="empty">尚无对应点</td></tr>';
  $('pairs-table').querySelectorAll('[data-delete-pair]').forEach(e=>e.onclick=run(async()=>{setState(await api(`/api/pairs/${e.dataset.deletePair}`,'DELETE'));}));
  const errorPairs=session.pairs.filter(p=>Number.isFinite(p.error_mm)),maxError=Math.max(1,...errorPairs.map(p=>p.error_mm));
  $('error-chart').innerHTML=errorPairs.length?errorPairs.map((p,i)=>`<div class="error-row"><span>${escapeHtml(p.label||`P${i+1}`)} <small>${p.role==='validation'?'验证':'标定'}</small></span><div class="error-track"><div class="error-bar ${p.role}" style="width:${Math.max(.5,p.error_mm/maxError*100)}%"></div></div><span class="error-value">${fmt(p.error_mm,3)} mm</span></div>`).join(''):'<p class="empty">添加对应点并完成标定后查看误差</p>';
  $('observation-count').textContent=`${session.observations.length} 组观测`;
  $('observations-list').innerHTML=session.observations.map((o,i)=>`<span class="observation-chip">#${i+1} / 帧 ${o.frame_id}<button class="text-button" data-delete-observation="${o.id}">×</button></span>`).join('');
  $('observations-list').querySelectorAll('[data-delete-observation]').forEach(e=>e.onclick=run(async()=>setState(await api(`/api/handeye-observations/${e.dataset.deleteObservation}`,'DELETE'))));
  if(!state.base_from_camera&&$('cloud-coordinates').value==='base')$('cloud-coordinates').value='camera';
  $('cloud-coordinates').querySelector('[value="base"]').disabled=!state.base_from_camera;
  renderSelection();updateCloud();
  updateActivity();
}
function updateActivity(){
  if(!state)return;
  const idle=['idle','disconnected'].includes(state.source),connected=state.source==='realsense';
  document.body.dataset.playback=live?'live':'paused';
  const label=idle?'等待设备':state.source==='demo'?'示例数据':state.source==='import'?'记录帧回放':live?'实时预览':'测量模式';
  $('session-state').innerHTML=`<i class="dot ${connected?'mint':state.source==='demo'?'amber':''}"></i>${label}`;
  $('session-state').classList.toggle('streaming',live);
  $('banner-text').textContent=idle?'连接深度相机，开始采集真实空间。':state.source==='demo'?'正在查看合成示例，标定与测量记录独立保存。':state.source==='import'?'记录帧已载入，点选画面继续分析。':live?'画面持续更新 · 点击目标冻结当前帧并测量':selected?`已锁定显示帧 #${selected.frame_id} · 坐标基于该帧计算`:'相机就绪 · 开启实时预览，或采集一帧开始测量';
}
function renderSelection(){
  const point=selected?.camera_m,base=currentBase();
  $('selected-label').textContent=selected?`P${state.session.selections.findIndex(p=>p.id===selected.id)+1} / 已选中`:'选择一个测量点';
  $('selected-pixel').textContent=selected?`像素 (${selected.pixel.join(', ')}) · 帧 #${selected.frame_id}`:'点击 RGB 或深度图';
  ['x','y','z'].forEach((axis,i)=>{$(`camera-${axis}`).textContent=point?fmt(point[i]*1000):'—';$(`base-${axis}`).textContent=base?fmt(base[i]*1000):'—';});
  $('base-hint').textContent=state.base_from_camera?'使用当前变换计算 · 单位 mm':state.session.mode==='eye_in_hand'&&state.session.extrinsic?'请填写当前机器人位姿':'尚未标定，请采集对应点并求解';
  $('depth-spread').textContent=selected?`${fmt(selected.spread_mm)} mm`:'—';$('point-warning').textContent=selected?.warning||'';
  $('use-for-calibration').disabled=!selected;$('use-for-validation').disabled=!selected;
  $('copy-coordinates').disabled=!selected;
  $('base-details').open=!!state.base_from_camera;
  $('chain-pixel').textContent=selected?selected.pixel.join(', '):'选择像素';
  $('chain-depth').textContent=selected?fmt(selected.depth_m*1000):'—';$('chain-camera').textContent=point?xyz(point):'—';$('chain-base').textContent=base?xyz(base):'尚未标定';
  $('pair-selected').textContent=selected?`像素 (${selected.pixel.join(', ')}) · 相机 XYZ: [${xyz(point)}] mm`:'请先在“采集与定位”中选点';
}
function updateCloud(){
  if(!frame||!state)return;const coordinates=$('cloud-coordinates').value;
  $('cloud-label').textContent=coordinates==='base'?'ROBOT BASE FRAME':'CAMERA OPTICAL FRAME';
  cloud.update(frame,state,selected,coordinates);
}
function drawImage(){
  if(!frame||!images.color)return;
  const canvas=$('image-canvas'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);ctx.globalAlpha=1;
  ctx.drawImage(imageMode==='depth'?images.depth:images.color,0,0);
  if(imageMode==='overlay'){ctx.globalAlpha=.45;ctx.drawImage(images.depth,0,0);ctx.globalAlpha=1;}
  for(const p of state?.session.selections||[]){
    if(p.frame_id!==frame.frame_id||p.capture_key!==frame.capture_key)continue;const [x,y]=p.pixel;
    ctx.beginPath();ctx.arc(x,y,selected?.id===p.id?7:4,0,Math.PI*2);ctx.strokeStyle=selected?.id===p.id?'#dce6ff':'#e0b777';ctx.lineWidth=2;ctx.stroke();
    ctx.beginPath();ctx.moveTo(x-12,y);ctx.lineTo(x+12,y);ctx.moveTo(x,y-12);ctx.lineTo(x,y+12);ctx.stroke();
  }
  if(boardObservation?.frame_id===frame.frame_id){ctx.fillStyle='#94b5ff';for(const [x,y] of boardObservation.corners){ctx.beginPath();ctx.arc(x,y,2,0,Math.PI*2);ctx.fill();}}
}
function updateImageModeLabel(){
  const range=frame?.depth_range_m;
  const depthLabel=range?`DEPTH / ${range[0].toFixed(2)}–${range[1].toFixed(2)} m · AUTO`:'DEPTH / AUTO';
  $('image-mode').textContent={color:'RGB / COLOR',depth:depthLabel,overlay:'RGB + DEPTH / OVERLAY'}[imageMode];
}
document.querySelectorAll('[data-image]').forEach(e=>e.addEventListener('click',()=>{
  imageMode=e.dataset.image;document.querySelectorAll('[data-image]').forEach(b=>b.classList.toggle('active',b===e));
  updateImageModeLabel();drawImage();
}));
$('image-canvas').addEventListener('click',run(async e=>{
  if(!frame)return;stopLive();const canvas=$('image-canvas'),rect=canvas.getBoundingClientRect();
  // The canvas has the same aspect ratio as the source; no CSS object-fit crop.
  const u=Math.min(frame.width-1,Math.max(0,Math.floor((e.clientX-rect.left)/rect.width*frame.width)));
  const v=Math.min(frame.height-1,Math.max(0,Math.floor((e.clientY-rect.top)/rect.height*frame.height)));
  const result=await api('/api/selections','POST',{frame_id:frame.frame_id,capture_key:frame.capture_key,u,v,radius:Number($('sample-radius').value)});
  selected=result.selection;setState(result.state);drawImage();
}));
$('capture-frame').onclick=run(async()=>{stopLive();$('capture-frame').setAttribute('aria-busy','true');try{await capture();}finally{$('capture-frame').removeAttribute('aria-busy');}});
$('live-toggle').onclick=()=>{if(live){stopLive();return;}live=true;$('live-toggle').textContent='暂停预览';updateActivity();liveLoop();};
$('load-demo').onclick=run(async()=>{stopLive();await applyPacket(await api('/api/sources','POST',{source:'demo'}));closeDialogs();cloud.reset();toast('已打开示例场景，数据独立保存');});
async function refreshDevices(announce=true){
  const result=await api('/api/devices');$('device-message').textContent=result.message;
  $('device-select').innerHTML='<option value="">'+(result.devices.length?'选择已连接的设备':'未发现设备')+'</option>';
  for(const d of result.devices){const option=new Option(`${d.name} / ${d.serial}`,d.serial);$('device-select').add(option);}
  if(result.devices.length===1)$('device-select').value=result.devices[0].serial;
  if(announce)toast(result.devices.length?`发现 ${result.devices.length} 台设备`:result.message,!result.devices.length);
}
$('detect-devices').onclick=run(()=>refreshDevices());
$('connect-camera').onclick=run(async()=>{
  stopLive();$('connect-camera').disabled=true;$('connect-camera').setAttribute('aria-busy','true');$('source-status').textContent='连接中';
  try{await applyPacket(await api('/api/sources','POST',{source:'realsense',serial:$('device-select').value}));closeDialogs();toast('相机已连接，可以开始采集与测量');cloud.reset();}
  catch(error){setState(await api('/api/status'));throw error;}
  finally{$('connect-camera').disabled=false;$('connect-camera').removeAttribute('aria-busy');}
});
$('disconnect-camera').onclick=run(async()=>{stopLive();await applyPacket(await api('/api/sources','POST',{source:'idle'}));toast('相机已断开，本次设备会话仍保留');await refreshDevices(false);});
function choosePair(role){if(!selected)return;$('pair-role').value=role;setTab('calibration');$('measured-x').focus();}
$('use-for-calibration').onclick=()=>choosePair('calibration');$('use-for-validation').onclick=()=>choosePair('validation');
$('pair-form').onsubmit=run(async e=>{
  e.preventDefault();if(!selected)throw new Error('请先在图像中选点');
  const result=await api('/api/pairs','POST',{selection_id:selected.id,base_mm:['x','y','z'].map(a=>Number($(`measured-${a}`).value)),role:$('pair-role').value,label:$('pair-label').value});
  setState(result.state);toast('对应点已记录');$('pair-form').reset();
});
$('fill-demo-pair').onclick=()=>{
  if(!selected||!state.session.synthetic){toast('先在合成图像中选择一个点',true);return;}
  const base=state.demo_reference_transform?transformPoint(state.demo_reference_transform,selected.camera_m):null;if(!base){toast('请先切回内置合成场景',true);return;}
  ['x','y','z'].forEach((a,i)=>{$(`measured-${a}`).value=(base[i]*1000).toFixed(5);});
};
$('solve-points').onclick=run(async()=>{const result=await api('/api/calibrations','POST',{method:'pointfit'});setState(result.state);toast(`标定求解完成，拟合 RMS ${fmt(result.result.rms_mm,3)} mm；请再添加独立验证点`);});
function updateMountDescription(){const wrist=$('mount-mode').value==='eye_in_hand';$('robot-pose-wrap').hidden=!wrist;$('matrix-direction').textContent=`T_${wrist?'tool':'base'}_from_camera · 列向量 · 平移单位 m`;}
$('mount-mode').onchange=()=>{updateMountDescription();$('transform-matrix').value='';$('robot-pose').value='';};
function parseMatrix(id,optional=false){const text=$(id).value.trim();if(!text&&optional)return null;try{return JSON.parse(text);}catch{throw new Error('矩阵格式应为 JSON 二维数组，例如 [[1,0,0,0], ...]');}}
async function saveTransform(){
  const result=await api('/api/transforms','PUT',{mode:$('mount-mode').value,matrix:parseMatrix('transform-matrix',true),base_from_tool:parseMatrix('robot-pose',true),label:'手动变换 · 待独立验证',clearance_mm:Number($('clearance').value),surface_offset_mm:Number($('surface-offset').value)});
  setState(result);cloud.fit();cloud.draw();toast('变换与预览设置已更新');
}
$('apply-transform').onclick=run(saveTransform);
$('save-preview').onclick=run(async()=>{
  const result=await api('/api/transforms','PUT',{mode:state.session.mode,matrix:state.session.extrinsic,base_from_tool:state.session.base_from_tool,label:state.session.label,clearance_mm:Number($('clearance').value),surface_offset_mm:Number($('surface-offset').value)});
  setState(result);toast('预接近预览已更新');
});
$('cloud-coordinates').onchange=()=>{updateCloud();cloud.reset();};$('reset-view').onclick=()=>cloud.reset();
$('frame-file').onchange=run(async e=>{
  const file=e.target.files[0];if(!file)return;stopLive();
  try{const response=await fetch('/api/frames/import',{method:'POST',headers:{'Content-Type':'application/zip'},body:file});const result=await response.json();if(!response.ok)throw new Error(result.detail);await applyPacket(result);closeDialogs();toast('RGB-D 文件已导入，当前数据使用独立标定配置');cloud.reset();}
  finally{e.target.value='';}
});
async function readJsonInput(event,endpoint,method){const file=event.target.files[0];if(!file)return;try{setState(await api(endpoint,method,JSON.parse(await file.text())));closeDialogs();toast('导入成功');}finally{event.target.value='';}}
$('session-file').onchange=run(e=>readJsonInput(e,'/api/session','PUT'));
$('calibration-file').onchange=run(e=>readJsonInput(e,'/api/calibrations/import','POST'));
$('detect-board').onclick=run(async()=>{
  if(!frame)throw new Error('请先采集一帧');stopLive();
  boardObservation=await api('/api/board-observations/detection','POST',{frame_id:frame.frame_id,columns:Number($('board-columns').value),rows:Number($('board-rows').value),square_mm:Number($('board-square').value)});
  $('observation-board').value=JSON.stringify(boardObservation.camera_from_target);$('board-result').textContent=` 重投影 RMS ${fmt(boardObservation.reprojection_rms_px,3)} px`;drawImage();
});
$('add-observation').onclick=run(async()=>{
  if(!frame)throw new Error('请先采集一帧');
  const result=await api('/api/handeye-observations','POST',{frame_id:frame.frame_id,base_from_tool:parseMatrix('observation-robot'),camera_from_target:parseMatrix('observation-board')});setState(result.state);toast('手眼观测已记录');
});
$('solve-handeye').onclick=run(async()=>{const result=await api('/api/calibrations','POST',{method:'handeye'});setState(result.state);toast('手眼求解完成，请使用新数据验证');});
window.addEventListener('beforeunload',e=>{if(state?.session.pairs.length||state?.session.observations.length){e.preventDefault();e.returnValue='';}});
$('copy-coordinates').onclick=run(async()=>{if(!selected)return;const text=`X=${fmt(selected.camera_m[0]*1000)} mm, Y=${fmt(selected.camera_m[1]*1000)} mm, Z=${fmt(selected.camera_m[2]*1000)} mm`;await navigator.clipboard.writeText(text);toast('相机 XYZ 已复制（mm）');});
$('image-canvas').addEventListener('mousemove',event=>{if(!frame)return;const r=event.currentTarget.getBoundingClientRect();const u=Math.floor((event.clientX-r.left)/r.width*frame.width),v=Math.floor((event.clientY-r.top)/r.height*frame.height);$('hover-pixel').textContent=`u ${Math.max(0,Math.min(frame.width-1,u))} · v ${Math.max(0,Math.min(frame.height-1,v))}`;},{passive:true});
$('image-canvas').addEventListener('mouseleave',()=>{$('hover-pixel').textContent='点击选点 ⊕';});
document.addEventListener('keydown',event=>{
  if(event.ctrlKey||event.metaKey||event.altKey||event.target.closest('input,textarea,select,button,a,summary,[contenteditable="true"]')||document.querySelector('dialog[open]'))return;
  if(event.key==='?'){$('help-dialog').showModal();return;}
  if(event.code==='Space'&&state?.source==='realsense'){event.preventDefault();$('live-toggle').click();}
  if(event.key.toLowerCase()==='c'&&!$('capture-frame').disabled)$('capture-frame').click();
});
await run(async()=>{const initial=await api('/api/status');if(['idle','disconnected'].includes(initial.source)){clearFrame();setState(initial);await refreshDevices(false);}else{await capture();}effects.reveal(document.querySelector('main'));}) ();

document.getElementById('cloud-palette').addEventListener('change',event=>{cloud.palette=event.target.value;cloud.draw();});
