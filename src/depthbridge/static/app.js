import {CloudView, multiplyMatrices, transformPoint} from './cloud.js';

const $ = id => document.getElementById(id);
let frame=null,state=null,selected=null,images={},imageMode='color',live=false,liveTimer=null,captureEpoch=0,boardObservation=null;
const cloud=new CloudView($('cloud-canvas'));
const titles={workbench:['采集与定位','INSPECT'],calibration:['坐标标定','CALIBRATE'],validation:['误差验证','VALIDATE'],guide:['真机准备','CONNECT']};
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
  document.querySelectorAll('.tab').forEach(e=>e.classList.toggle('active',e.id===`tab-${name}`));
  document.querySelectorAll('.nav').forEach(e=>e.classList.toggle('active',e.dataset.tab===name));
  $('page-title').innerHTML=`${titles[name][0]}<span> / ${titles[name][1]}</span>`;
  requestAnimationFrame(()=>cloud.draw());
}
document.querySelectorAll('[data-tab]').forEach(e=>e.addEventListener('click',()=>setTab(e.dataset.tab)));
function stopLive(){live=false;clearTimeout(liveTimer);captureEpoch++;$('live-toggle').textContent='实时预览';}
function loadImage(src){return new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(new Error('图像加载失败'));image.src=src;});}
async function applyPacket(packet,epoch=captureEpoch){
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
  selected=null;
  setState(packet.state);drawImage();
  updateImageModeLabel();
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
  $('source-name').textContent=state.source==='demo'?'离线合成场景':state.source==='realsense'?(frame?.description.split(' · ')[0]||'Intel RealSense'):state.source==='import'?'RGB-D 文件包':'设备已断开';
  $('source-desc').textContent=state.source==='realsense'?state.source_id.replace('realsense:','序列号 '):state.source==='demo'?'无需相机，先熟悉完整流程':'当前数据独立保存标定配置';
  $('source-dot').className=`dot ${session.synthetic?'amber':'mint'}`;
  $('source-banner').className=`source-banner${session.synthetic?'':' real'}`;
  $('source-banner').querySelector('.badge').className=`badge ${session.synthetic?'amber':'mint'}`;
  $('source-banner').querySelector('.badge').textContent=session.synthetic?'SYNTHETIC':state.source==='realsense'?'LIVE CAMERA':'RECORDED';
  $('banner-text').textContent=session.synthetic?'当前是合成场景。坐标与变换用于演示，连接相机后单独标定。':state.source==='realsense'?'真实相机数据。相机固定后采集对应点；移动相机后需要重新标定。':'已导入记录帧。请核对采集来源，并为当前数据加载对应标定。';
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
}
function renderSelection(){
  const point=selected?.camera_m,base=currentBase();
  $('selected-label').textContent=selected?`P${state.session.selections.findIndex(p=>p.id===selected.id)+1} / 已选中`:'尚未选择';
  $('selected-pixel').textContent=selected?`像素 (${selected.pixel.join(', ')}) · 帧 #${selected.frame_id}`:'点击 RGB 或深度图';
  ['x','y','z'].forEach((axis,i)=>{$(`camera-${axis}`).textContent=point?fmt(point[i]*1000):'—';$(`base-${axis}`).textContent=base?fmt(base[i]*1000):'—';});
  $('base-hint').textContent=state.base_from_camera?'使用当前变换计算 · 单位 mm':state.session.mode==='eye_in_hand'&&state.session.extrinsic?'请填写当前机器人位姿':'尚未标定，请采集对应点并求解';
  $('depth-spread').textContent=selected?`${fmt(selected.spread_mm)} mm`:'—';$('point-warning').textContent=selected?.warning||'';
  $('use-for-calibration').disabled=!selected;$('use-for-validation').disabled=!selected;
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
    if(p.frame_id!==frame.frame_id)continue;const [x,y]=p.pixel;
    ctx.beginPath();ctx.arc(x,y,selected?.id===p.id?7:4,0,Math.PI*2);ctx.strokeStyle=selected?.id===p.id?'#b5ffe7':'#e0b777';ctx.lineWidth=2;ctx.stroke();
    ctx.beginPath();ctx.moveTo(x-12,y);ctx.lineTo(x+12,y);ctx.moveTo(x,y-12);ctx.lineTo(x,y+12);ctx.stroke();
  }
  if(boardObservation?.frame_id===frame.frame_id){ctx.fillStyle='#92ffe0';for(const [x,y] of boardObservation.corners){ctx.beginPath();ctx.arc(x,y,2,0,Math.PI*2);ctx.fill();}}
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
  const result=await api('/api/selections','POST',{frame_id:frame.frame_id,u,v,radius:Number($('sample-radius').value)});
  selected=result.selection;setState(result.state);drawImage();
}));
$('capture-frame').onclick=run(async()=>{stopLive();await capture();});
$('live-toggle').onclick=()=>{if(live){stopLive();return;}live=true;$('live-toggle').textContent='暂停预览';liveLoop();};
$('load-demo').onclick=run(async()=>{stopLive();await applyPacket(await api('/api/sources','POST',{source:'demo'}));toast('已切回离线示例');});
$('detect-devices').onclick=run(async()=>{
  const result=await api('/api/devices');$('device-message').textContent=result.message;
  $('device-select').innerHTML='<option value="">自动选择已连接设备</option>';
  for(const d of result.devices){const option=new Option(`${d.name} / ${d.serial}`,d.serial);$('device-select').add(option);}
  toast(result.devices.length?`发现 ${result.devices.length} 台设备`:result.message,!result.devices.length);
});
$('connect-camera').onclick=run(async()=>{
  stopLive();$('connect-camera').disabled=true;
  try{await applyPacket(await api('/api/sources','POST',{source:'realsense',serial:$('device-select').value}));toast('相机已连接，请检查 RGB 与深度，再采集标定点');cloud.reset();}
  catch(error){setState(await api('/api/status'));throw error;}
  finally{$('connect-camera').disabled=false;}
});
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
  try{const response=await fetch('/api/frames/import',{method:'POST',headers:{'Content-Type':'application/zip'},body:file});const result=await response.json();if(!response.ok)throw new Error(result.detail);await applyPacket(result);toast('RGB-D 文件已导入，当前数据使用独立标定配置');cloud.reset();}
  finally{e.target.value='';}
});
async function readJsonInput(event,endpoint,method){const file=event.target.files[0];if(!file)return;try{setState(await api(endpoint,method,JSON.parse(await file.text())));toast('导入成功');}finally{event.target.value='';}}
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
await run(async()=>{await capture();}) ();
