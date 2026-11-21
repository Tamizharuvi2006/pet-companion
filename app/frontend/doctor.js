"use strict";
const statusNode=document.querySelector('#status'),deviceSelect=document.querySelector('#device'),reportNode=document.querySelector('#report'),loginForm=document.querySelector('#login'),passwordInput=document.querySelector('#password'),downloadButton=document.querySelector('#download'),cameraButton=document.querySelector('#camera'),cameraImage=document.querySelector('#camera-preview');
let reports=[],activeReport=null,cameraUrl=null;
const humanize=value=>String(value).replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
function draw(report){
 activeReport=report;reportNode.replaceChildren();
 const section=document.createElement('article');section.className='device';
 const title=document.createElement('h2');title.textContent=`${report.device_id} · ${report.overall}`;title.className=report.overall;section.append(title);
 const evidence=document.createElement('p');evidence.className='muted';evidence.textContent=report.evidence;section.append(evidence);
 const grid=document.createElement('div');grid.className='checks';
 for(const [name,check] of Object.entries(report.checks)){
  const card=document.createElement('div');card.className='check';const heading=document.createElement('strong');heading.className=check.status;heading.textContent=`${humanize(name)} · ${check.status}`;const detail=document.createElement('div');detail.textContent=check.detail;card.append(heading,detail);
  if(check.evidence!==undefined){const ev=document.createElement('div');ev.className='evidence';ev.textContent=`Evidence: ${typeof check.evidence==='object'?JSON.stringify(check.evidence):check.evidence}`;card.append(ev);}grid.append(card);
 }
 section.append(grid);reportNode.append(section);downloadButton.disabled=false;cameraButton.disabled=!report.device_id;
}
async function refresh(){
 statusNode.textContent='Refreshing device evidence…';
 try{const response=await fetch('/api/face/devices/doctor',{credentials:'same-origin',cache:'no-store'});
  if(response.status===401){loginForm.hidden=false;throw new Error('Sign in required.');}
  if(!response.ok)throw new Error(`Doctor request failed (${response.status}).`);
  reports=await response.json();loginForm.hidden=true;deviceSelect.replaceChildren();
  if(!reports.length){const option=document.createElement('option');option.textContent='No device token configured';deviceSelect.append(option);downloadButton.disabled=true;cameraButton.disabled=true;reportNode.textContent='Configure a device token in the server environment, then connect that device.';statusNode.textContent='No configured device is available.';return;}
  for(const report of reports){const option=document.createElement('option');option.value=report.device_id;option.textContent=report.device_id;deviceSelect.append(option);}
  const chosen=reports.find(item=>item.device_id===deviceSelect.value)||reports[0];deviceSelect.value=chosen.device_id;draw(chosen);statusNode.textContent=`Updated ${new Date().toLocaleTimeString()} · no paid APIs called.`;
 }catch(error){statusNode.textContent=error.message;}
}
deviceSelect.onchange=()=>{const selected=reports.find(item=>item.device_id===deviceSelect.value);if(selected)draw(selected);};
document.querySelector('#refresh').onclick=refresh;
downloadButton.onclick=()=>{if(!activeReport)return;const blob=new Blob([JSON.stringify(activeReport,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=`bella-doctor-${activeReport.device_id}-${new Date().toISOString().slice(0,10)}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
cameraButton.onclick=async()=>{if(!activeReport)return;cameraButton.disabled=true;statusNode.textContent='Requesting one camera frame…';try{const response=await fetch(`/api/face/${encodeURIComponent(activeReport.device_id)}/camera/capture`,{method:'POST',credentials:'same-origin'});if(!response.ok)throw new Error(`Camera unavailable (${response.status}).`);const blob=await response.blob();if(cameraUrl)URL.revokeObjectURL(cameraUrl);cameraUrl=URL.createObjectURL(blob);cameraImage.src=cameraUrl;cameraImage.hidden=false;statusNode.textContent='One requested JPEG received. No automatic capture will run.';await refresh();}catch(error){statusNode.textContent=error.message;}finally{cameraButton.disabled=false;}};
loginForm.onsubmit=async event=>{event.preventDefault();try{const response=await fetch('/auth/login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:passwordInput.value})});passwordInput.value='';if(!response.ok)throw new Error('Sign in failed.');loginForm.hidden=true;await refresh();}catch(error){statusNode.textContent=error.message;}};
void refresh();
