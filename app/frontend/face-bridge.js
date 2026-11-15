"use strict";
// Opt-in polling avoids consuming the voice latch or changing offline simulation.
const panel=document.createElement('section');
panel.style.cssText='display:block;border:1px solid #41404c;padding:18px;border-radius:16px';
panel.innerHTML='<label>Mode <select id="face-mode"><option value="simulation">Simulation</option><option value="connected">Connected device</option></select></label><label>Device <select id="face-device"></select></label><form id="face-login" hidden><input type="password" autocomplete="current-password" aria-label="Bella password" placeholder="Bella access password"><button>Sign in</button></form><p id="face-connection" role="status">Simulation · no network connection</p><p id="face-device-state"></p>';
document.querySelector('canvas').after(panel);
const mode=document.querySelector('#face-mode'),device=document.querySelector('#face-device'),connection=document.querySelector('#face-connection'),deviceState=document.querySelector('#face-device-state'),login=document.querySelector('#face-login');
let polling=false,generation=0,connectedTimer;
window.bellaFaceConnected=false;
async function refresh(){
 if(mode.value!=='connected'||polling)return;
 polling=true;const epoch=generation;
 try{
  const response=await fetch('/api/face/devices',{credentials:'same-origin',cache:'no-store'});
  if(epoch!==generation)return;
  if(response.status===401){login.hidden=false;throw new Error('Sign in required');}
  if(!response.ok)throw new Error('Bridge unavailable');
  const records=await response.json();if(epoch!==generation)return;
  login.hidden=true;connection.textContent='Server connected · physical display remains unverified';
  const selected=device.value;device.replaceChildren();
  records.forEach(record=>{const option=document.createElement('option');option.value=record.device_id;option.textContent=record.device_id;device.append(option);});
  if(records.some(record=>record.device_id===selected))device.value=selected;
  const record=records.find(item=>item.device_id===device.value);
  const expression=record?.connected?record.face_expression:'offline';
  window.bellaFaceRemoteExpression=expression.toUpperCase();
  deviceState.textContent=record?`${record.connected?'Online':'Offline'} · heartbeat ${record.last_heartbeat||'none'} · face ${record.face_expression} · conversation ${record.state} · touch ${record.last_touch||'none'} · command ${record.command_status||'none'} (engine acceptance is not TFT delivery)`:'No provisioned device has connected';
 }catch(error){if(epoch===generation){connection.textContent=error.message;window.bellaFaceRemoteExpression='OFFLINE';}}
 finally{polling=false;}
}
mode.onchange=()=>{generation++;window.bellaFaceConnected=mode.value==='connected';clearInterval(connectedTimer);if(window.bellaFaceConnected){refresh();connectedTimer=setInterval(refresh,3000);}else{connection.textContent='Simulation · no network connection';deviceState.textContent='';login.hidden=true;}};
login.onsubmit=async event=>{event.preventDefault();const input=login.querySelector('input');try{const response=await fetch('/auth/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:input.value})});input.value='';if(!response.ok)throw new Error('Sign in failed');await refresh();}catch(error){connection.textContent=error.message;}};
document.querySelector('#emotions').addEventListener('click',async event=>{
 const expression=event.target.dataset.state;
 if(mode.value!=='connected'||!expression||!device.value)return;
 try{const response=await fetch(`/api/face/${encodeURIComponent(device.value)}/expression`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({expression:expression.toLowerCase(),duration_ms:1800})});if(!response.ok)throw new Error('Command rejected or device unavailable');connection.textContent='Command pending · awaiting device engine acknowledgement';}catch(error){connection.textContent=error.message;}
});
