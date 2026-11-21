"use strict";
// Standalone visual preview: no audio, provider requests or device commands.
const states=['IDLE','HAPPY','EXCITED','LOVE','CURIOUS','SURPRISED','SAD','ANGRY','SLEEPY','WINK','LISTENING','THINKING','SPEAKING','OFFLINE','ERROR'];
const canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d');
const reduced=document.querySelector('#reduced');
const simulationController=new BellaExpressionController();let simulationSequence=0;
function simulate(expression,source,duration=3000){simulationController.apply({version:1,event_id:'simulation:'+ ++simulationSequence,session_id:'simulation',device_id:null,turn_id:null,destination:'simulation',source,sequence:simulationSequence,expression:expression.toLowerCase(),duration_ms:duration});}
function clearSimulationActivity(){for(const source of ['conversation','playback','connectivity','error'])simulate('idle',source);}
reduced.checked=matchMedia('(prefers-reduced-motion: reduce)').matches;
let status='IDLE',emotion='IDLE',until=0,lastTouch=-1000,time=0,last=performance.now(),blinkAt=2800;
const eyes=[{w:136,h:155,curve:0,angle:0,y:0},{w:136,h:155,curve:0,angle:0,y:0}];
let gaze=0,errorBlend=0,thinkingBlend=0;
let irisX=0,irisY=0,pointerX=0,pointerY=0,pointerUntil=0,lookAt=2200,lookX=0,lookY=0;
let curiousBlend=0,irisVelocityX=0,irisVelocityY=0;
const idleLooks=[[0,0],[12,-4],[-13,2],[6,-8],[0,0],[-7,-5]];
function settle(position,velocity,target,dt){const omega=12,decay=Math.exp(-omega*dt),offset=position-target,j=velocity+omega*offset;return [target+(offset+j*dt)*decay,(velocity-omega*j*dt)*decay];}
// Interior emotion channels interpolate independently of eyelid geometry.
const interior={radius:1,pupil:1,light:1,warm:0,focus:0,shine:1};
const interiorProfiles={
 IDLE:[1,1,1,0,0,1],HAPPY:[1.06,1.1,1.1,.25,0,1.2],
 EXCITED:[1.1,1.22,1.2,.35,0,1.35],LOVE:[1.12,1.2,1.1,1,0,1.3],
 CURIOUS:[1.03,.9,1,0,.25,1.1],SURPRISED:[.94,.72,1.15,.1,.2,1.2],
 SAD:[1.04,1.12,.82,0,0,.75],ANGRY:[.94,.76,.85,.65,.6,.65],
 SLEEPY:[1,1.1,.7,.15,0,.55],WINK:[1.04,1.1,1.1,.3,0,1.2],
 LISTENING:[1.04,1.08,1.08,.1,.5,1.15],THINKING:[.98,.85,.95,0,1,.9],
 SPEAKING:[1,1.02,1.05,.2,.2,1.1],OFFLINE:[1,1,.5,0,0,.3],ERROR:[1,.8,.8,.5,0,.5]
};
function pigment(cool,warm,blend){return `rgb(${cool.map((channel,i)=>Math.round(channel+(warm[i]-channel)*blend)).join(',')})`;}
const smoothstep=(a,b,v)=>{const t=Math.max(0,Math.min(1,(v-a)/(b-a)));return t*t*(3-2*t);};
canvas.addEventListener('pointermove',event=>{const box=canvas.getBoundingClientRect();pointerX=((event.clientX-box.left)/box.width-.5)*30;pointerY=((event.clientY-box.top)/box.height-.5)*20;pointerUntil=time+1600;});
canvas.addEventListener('pointerleave',()=>{pointerUntil=0;});
function buttons(id,items,fn){items.forEach((name,i)=>{const b=document.createElement('button');b.textContent=name;b.dataset.state=name;b.onclick=()=>fn(name,i);document.querySelector(id).append(b);});}
buttons('#emotions',states.slice(0,10),name=>{clearSimulationActivity();simulate(name,'preview');});
buttons('#pads',['1 · Happy','2 · Love','3 · Curious','4 · Wink'],(_,i)=>{if(time-lastTouch<250)return;lastTouch=time;simulate(['HAPPY','LOVE','CURIOUS','WINK'][i],'touch',1800);});
buttons('#voice',['IDLE','LISTENING','THINKING','SPEAKING','OFFLINE','ERROR'],name=>{clearSimulationActivity();simulate(name,name==='ERROR'?'error':name==='OFFLINE'?'connectivity':name==='SPEAKING'?'playback':'conversation',name==='ERROR'?2200:60000);});
function target(state,i){
 const t={w:136,h:155,curve:0,angle:0,y:0};
 switch(state){
 case 'HAPPY':Object.assign(t,{w:148,h:12,curve:-52,y:14});break;
 case 'EXCITED':Object.assign(t,{w:152,h:178,y:-8});break;
 case 'LOVE':Object.assign(t,{w:145,h:166,y:-3});break;
 case 'CURIOUS':Object.assign(t,{w:i?130:145,h:i?110:178,y:i?9:-13,angle:i?.055:-.055});break;
 case 'SURPRISED':Object.assign(t,{w:154,h:195,y:-10});break;
 case 'SAD':Object.assign(t,{w:140,h:96,angle:i?.16:-.16,y:15});break;
 case 'ANGRY':Object.assign(t,{w:145,h:85,angle:i?-.2:.2,y:8});break;
 case 'SLEEPY':Object.assign(t,{w:142,h:28,curve:14,y:22});break;
 case 'WINK':if(i===0)Object.assign(t,{w:140,h:10,curve:-24,y:10});break;
 case 'LISTENING':Object.assign(t,{w:140,h:172,y:-6});break;
 case 'THINKING':Object.assign(t,{w:126,h:i?110:142,y:i?-16:-24});break;
 case 'SPEAKING':Object.assign(t,{w:142,h:143});break;
 case 'OFFLINE':Object.assign(t,{w:116,h:9,curve:0,y:15});break;
 case 'ERROR':Object.assign(t,{w:120,h:100,angle:i?.08:-.08});break;
 }
 return t;
}
function frame(now){
 const dt=Math.min((now-last)/1000,.05);last=now;
 time+=dt*1000*Number(document.querySelector('#speed').value);
 const remote=window.bellaFaceBrowserVoice?window.BellaExpressions.controller.current().toUpperCase():window.bellaFaceConnected?window.bellaFaceRemoteExpression:null;
 const s=remote&&states.includes(remote)?remote:simulationController.current().toUpperCase();
 document.querySelector('#state').textContent=s;
 document.querySelectorAll('[data-state]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.state===s)));
 if(time>blinkAt+220)blinkAt=time+2400+Math.random()*3200;
 const phase=(time-blinkAt)/220;
 const blink=reduced.checked||phase<0||phase>=1?1:phase<.4?1-smoothstep(0,.4,phase):smoothstep(.4,1,phase);
 const a=reduced.checked?1:1-Math.exp(-9*dt);
 const profile=interiorProfiles[s];
 Object.keys(interior).forEach((key,i)=>{interior[key]+=(profile[i]-interior[key])*a;});
 curiousBlend+=((s==='CURIOUS'?1:0)-curiousBlend)*a;
 if(time>lookAt){lookAt=time+1900+Math.random()*2600;const pose=idleLooks[Math.floor(Math.random()*idleLooks.length)];lookX=pose[0];lookY=pose[1];}
 const follow=!reduced.checked&&time<pointerUntil;
 const desiredX=follow?pointerX:15*thinkingBlend+17*curiousBlend+lookX*(1-interior.focus)*(1-curiousBlend);
 const desiredY=follow?pointerY:-14*thinkingBlend-7*curiousBlend+lookY*(1-interior.focus)*(1-curiousBlend);
 // Critically damped motion: move deliberately, settle, then hold a pose.
 if(reduced.checked){irisX=0;irisY=0;irisVelocityX=0;irisVelocityY=0;}
 else{[irisX,irisVelocityX]=settle(irisX,irisVelocityX,desiredX,dt);[irisY,irisVelocityY]=settle(irisY,irisVelocityY,desiredY,dt);}
 errorBlend+=((s==='ERROR'?1:0)-errorBlend)*a;
 thinkingBlend+=((s==='THINKING'?1:0)-thinkingBlend)*a;
 gaze+=((s==='THINKING'?24+(reduced.checked?0:Math.sin(time/1100)*9):s==='CURIOUS'?13:0)-gaze)*a;
 ctx.clearRect(0,0,1000,500);
 const color=s==='LOVE'?'#f5a9df':s==='ERROR'?'#ff829c':s==='OFFLINE'?'#8fbaff':'#c5a2ff';
 ctx.fillStyle=color;ctx.strokeStyle=color;ctx.lineCap='round';
 eyes.forEach((eye,i)=>{
  const t=target(s,i);for(const key of Object.keys(t))eye[key]+=(t[key]-eye[key])*a;
  const bob=reduced.checked?0:s==='EXCITED'?Math.sin(time/180)*5:s==='SPEAKING'?Math.sin(time/145)*2:0;
  ctx.save();ctx.translate(350+i*300+gaze,235+eye.y+bob);ctx.rotate(eye.angle);
  // Anime eye anatomy: almond sclera, shaded iris, pupil and upper lashes.
  const h=Math.max(7,eye.h*blink),w=eye.w;
  ctx.shadowColor=color;ctx.shadowBlur=8;
  ctx.globalAlpha=1;
  ctx.beginPath();
  // A single quadratic ribbon morphs continuously from round eyes to smiling arcs.
  const c=eye.curve*blink;
  const detail=smoothstep(14,55,h)*(1-smoothstep(0,30,Math.abs(c)));
  // One continuous shape avoids the old abrupt switch between open/closed eyes.
  ctx.moveTo(-w*.57,0);
  ctx.bezierCurveTo(-w*.48,-h*.73-c,w*.36,-h*.77-c,w*.57,0);
  ctx.bezierCurveTo(w*.42,h*.58-c,-w*.38,h*.62-c,-w*.57,0);ctx.closePath();
  const palette=['#e7deee','#fffafd','#eee5f5'];
  const gradient=ctx.createLinearGradient(-w*.4,-h/2,w*.35,h/2);
  palette.forEach((stop,index)=>gradient.addColorStop(index/(palette.length-1),stop));
  ctx.fillStyle=gradient;ctx.fill();
  // Glassy depth is clipped to the eye silhouette, never a surrounding face.
  ctx.save();ctx.clip();ctx.shadowBlur=0;
  if(detail>.001){
   ctx.save();ctx.globalAlpha*=detail;
   const ix=irisX,iy=irisY+2,r=w*.37*interior.radius;
   // 1. Curved sclera with a cool peripheral shadow, not a flat white fill.
   const sclera=ctx.createRadialGradient(0,h*.1,w*.12,0,-h*.2,w*.7);
   sclera.addColorStop(0,'#fffdfc');sclera.addColorStop(.65,'#f2edf6');sclera.addColorStop(1,'#9f94b8');
   ctx.fillStyle=sclera;ctx.fillRect(-w,-h,w*2,h*2);
   // Error keeps the sclera/lids: only the interior crossfades to crossed pupils.
   ctx.save();ctx.globalAlpha*=1-errorBlend;
   // 2. Dark outer iris rim; all subsequent iris detail stays within its ellipse.
   ctx.save();ctx.beginPath();ctx.ellipse(ix,iy,r,h*.58,0,0,Math.PI*2);ctx.clip();
   // 3. Layered iris pigment, darker under the lid and luminous below.
   const iris=ctx.createLinearGradient(0,-h*.5,0,h*.5);
   iris.addColorStop(0,pigment([27,17,75],[78,19,80],interior.warm));
   iris.addColorStop(.35,pigment([70,44,161],[167,63,169],interior.warm));
   iris.addColorStop(.72,pigment([83,125,244],[240,138,208],interior.warm));iris.addColorStop(1,pigment([166,245,255],[255,209,239],interior.warm));
   ctx.fillStyle=iris;ctx.beginPath();ctx.ellipse(ix,iy,r,h*.58,0,0,Math.PI*2);ctx.fill();
   const depth=ctx.createRadialGradient(ix,iy,r*.2,ix,iy,r);
   depth.addColorStop(0,'#f4b9ef80');depth.addColorStop(.6,'#ad87df00');depth.addColorStop(.86,'#44356070');depth.addColorStop(1,'#231b3bd9');
   ctx.fillStyle=depth;ctx.fillRect(ix-r,iy-h,r*2,h*2);
   // 4. Deterministic fine iris fibers: no frame-to-frame random shimmer.
   ctx.lineWidth=.8;
   for(let k=0;k<64;k++){
    const angle=k*Math.PI*2/64,inner=.35+.07*Math.sin(k*2.7),outer=.86+.08*Math.sin(k*4.3);
    ctx.strokeStyle=k%3===0?'#e9c8f66b':'#4530635c';
    ctx.beginPath();ctx.moveTo(ix+Math.cos(angle)*r*inner,iy+Math.sin(angle)*h*.58*inner);
    ctx.quadraticCurveTo(ix+Math.cos(angle+.025)*r*.65,iy+Math.sin(angle+.025)*h*.58*.65,ix+Math.cos(angle)*r*outer,iy+Math.sin(angle)*h*.58*outer);ctx.stroke();
   }
   // 5. Deep pupil with a soft violet collar.
   const pupil=ctx.createRadialGradient(ix,iy-h*.06,r*.22,ix,iy-h*.06,r*.54);
   pupil.addColorStop(0,'#130f24');pupil.addColorStop(.72,'#20152e');pupil.addColorStop(1,'#77518e00');
   const breathing=reduced.checked?1:1+Math.sin(time/1600)*.015;
   const dilation=interior.pupil*breathing;
   ctx.fillStyle=pupil;ctx.beginPath();ctx.ellipse(ix,iy-h*.06,r*.54*dilation,h*.4*dilation,0,0,Math.PI*2);ctx.fill();
   ctx.fillStyle='#161024';ctx.beginPath();ctx.ellipse(ix,iy-h*.06,r*.35*dilation,h*.3*dilation,0,0,Math.PI*2);ctx.fill();
   // 6. Lower bounced light and the upper eyelid's cast shadow.
   const reflected=ctx.createRadialGradient(ix,iy+h*.36,1,ix,iy+h*.36,r*.8);
   reflected.addColorStop(0,'#b9faffd0');reflected.addColorStop(1,'#9acaff00');ctx.fillStyle=reflected;ctx.fillRect(ix-r,iy-h,r*2,h*2);
   const lidShadow=ctx.createLinearGradient(0,-h*.6,0,h*.1);
   lidShadow.addColorStop(0,'#171027b8');lidShadow.addColorStop(1,'#17102700');ctx.fillStyle=lidShadow;ctx.fillRect(ix-r,iy-h,r*2,h*2);
   // 7. Corneal reflections: broad soft light plus crisp catchlights.
   ctx.fillStyle='#ffffff24';ctx.beginPath();ctx.ellipse(ix-r*.3,iy-h*.25,r*.53,h*.23,-.35,0,Math.PI*2);ctx.fill();
   const glint=interior.shine;
   ctx.fillStyle='#fffaff';ctx.beginPath();ctx.ellipse(ix-r*.4-irisX*.12,iy-h*.27-irisY*.1,9*glint,14*glint,.35,0,Math.PI*2);ctx.fill();
   ctx.beginPath();ctx.arc(ix+r*.4,iy+h*.23,4.5,0,Math.PI*2);ctx.fill();
   ctx.fillStyle='#ffffffa0';ctx.beginPath();ctx.arc(ix+r*.19,iy+h*.35,2,0,Math.PI*2);ctx.fill();
   // 8. Inner collarette: an irregular pigment ring around the pupil.
   ctx.strokeStyle='#d7a5ed48';ctx.lineWidth=1;ctx.beginPath();
   for(let k=0;k<=72;k++){const angle=k*Math.PI*2/72,rad=.51+.025*Math.sin(k*2.1);const px=ix+Math.cos(angle)*r*rad,py=iy+Math.sin(angle)*h*.58*rad;if(k===0)ctx.moveTo(px,py);else ctx.lineTo(px,py);}ctx.stroke();
   // 9. Sparse pigment flecks remain fixed to the moving iris.
   ctx.fillStyle='#efd2ff55';for(let k=0;k<16;k++){const angle=k*2.39996,rad=.61+.15*Math.sin(k*3.2);ctx.beginPath();ctx.arc(ix+Math.cos(angle)*r*rad,iy+Math.sin(angle)*h*.58*rad,.65,0,Math.PI*2);ctx.fill();}
   // 10. Soft lower caustic arc, inside the corneal boundary.
   ctx.strokeStyle='#ffe8fc60';ctx.lineWidth=2;ctx.beginPath();ctx.ellipse(ix,iy,r*.77,h*.46,0,.65,2.45);ctx.stroke();
   // 11. A broad, translucent window reflection adds depth without glitter.
   ctx.fillStyle='#ffffff0d';ctx.save();ctx.translate(ix-r*.12,iy-h*.18);ctx.rotate(-.3);ctx.fillRect(-r*.1,-h*.13,r*.25,h*.27);ctx.restore();
   // Emotional exposure changes smoothly, without replacing the iris texture.
   ctx.fillStyle=interior.light<1?`rgba(20,15,35,${(1-interior.light)*.65})`:`rgba(255,229,250,${(interior.light-1)*.3})`;
   ctx.fillRect(ix-r,iy-h,r*2,h*2);
   // Reference-inspired emotional pupils stay attached to the moving iris.
   if(interior.warm>.65&&s==='LOVE'){
    ctx.save();ctx.globalAlpha*=(interior.warm-.65)/.35;ctx.fillStyle='#ffa9e2';
    ctx.beginPath();ctx.moveTo(ix,iy+23);ctx.bezierCurveTo(ix-39,iy-3,ix-23,iy-30,ix,iy-12);ctx.bezierCurveTo(ix+23,iy-30,ix+39,iy-3,ix,iy+23);ctx.fill();ctx.restore();
   }
   if(s==='EXCITED'){
    ctx.fillStyle='#fff4ac';ctx.beginPath();ctx.moveTo(ix,iy-27);ctx.quadraticCurveTo(ix+5,iy-5,ix+22,iy);ctx.quadraticCurveTo(ix+5,iy+5,ix,iy+27);ctx.quadraticCurveTo(ix-5,iy+5,ix-22,iy);ctx.quadraticCurveTo(ix-5,iy-5,ix,iy-27);ctx.fill();
   }
   ctx.restore();
   ctx.restore();
   if(errorBlend>.001){
    ctx.save();ctx.globalAlpha*=errorBlend;
    const cross=ctx.createLinearGradient(-20,-25,22,25);
    cross.addColorStop(0,'#bb6d98');cross.addColorStop(1,'#67486f');
    ctx.strokeStyle=cross;ctx.lineWidth=9;ctx.lineCap='round';
    ctx.beginPath();ctx.moveTo(-19,-23);ctx.lineTo(19,23);ctx.moveTo(19,-23);ctx.lineTo(-19,23);ctx.stroke();ctx.restore();
   }
   // 12. Scleral wet-line reflection follows the lower eyelid.
   ctx.strokeStyle='#fdf4ff66';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(-w*.45,h*.1);ctx.quadraticCurveTo(0,h*.47,w*.43,h*.12);ctx.stroke();
   ctx.restore();
  }
  const bloom=ctx.createRadialGradient(-w*.18,-h*.26,0,-w*.18,-h*.26,w*.72);
  bloom.addColorStop(0,'#ffffff14');bloom.addColorStop(1,'#ffffff00');
  ctx.fillStyle=bloom;ctx.fillRect(-w,-h,w*2,h*2);
  ctx.restore();
  if(detail>.001){
   ctx.globalAlpha*=detail;ctx.shadowBlur=0;ctx.strokeStyle='#21132f';ctx.lineWidth=10;
   ctx.beginPath();ctx.moveTo(-w*.57,0);ctx.bezierCurveTo(-w*.48,-h*.73-c,w*.36,-h*.77-c,w*.57,0);ctx.stroke();
   const side=i===0?-1:1;ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(side*w*.48,-h*.24);ctx.lineTo(side*w*.66,-h*.39);ctx.moveTo(side*w*.38,-h*.4);ctx.lineTo(side*w*.49,-h*.57);ctx.stroke();
   ctx.strokeStyle='#d7adeb';ctx.lineWidth=2.5;ctx.beginPath();ctx.moveTo(-w*.43,-h*.49);ctx.bezierCurveTo(-w*.19,-h*.75,w*.16,-h*.72,w*.35,-h*.53);ctx.stroke();
  }
  // Fine floating brows keep the silhouette readable at small display sizes.
  ctx.strokeStyle=color;ctx.lineWidth=2;ctx.globalAlpha=.8;ctx.beginPath();ctx.moveTo(-w*.33,-eye.h*.72-20);ctx.quadraticCurveTo(0,-eye.h*.86-25,w*.3,-eye.h*.73-20);ctx.stroke();
  ctx.restore();
 });
 if(thinkingBlend>.001){ctx.save();ctx.fillStyle=color;for(let i=0;i<3;i++){const pulse=reduced.checked?.65:.35+.65*(.5+.5*Math.sin(time/330-i*.9));ctx.globalAlpha=thinkingBlend*pulse;ctx.beginPath();ctx.arc(464+i*36,133,4+i,0,Math.PI*2);ctx.fill();}ctx.restore();}
 ctx.shadowBlur=0;ctx.fillStyle=color;ctx.globalAlpha=.8;
 const nx=500+gaze*.3;
 ctx.beginPath();ctx.moveTo(nx-7,329);ctx.quadraticCurveTo(nx,326,nx+7,329);ctx.quadraticCurveTo(nx+4,336,nx,338);ctx.quadraticCurveTo(nx-4,336,nx-7,329);ctx.fill();ctx.globalAlpha=1;
 requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
