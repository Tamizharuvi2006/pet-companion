/* Shared, text-free expression contract. No fetch or provider calls. */
(function(root){
 'use strict';
 const states=['idle','happy','love','excited','curious','surprised','sad','angry','sleepy','wink','listening','thinking','speaking','offline','error'];
 const priorities={touch:10,preview:10,conversation:40,playback:60,connectivity:80,error:90};
 class ExpressionController {
  constructor(clock=()=>performance.now()){this.clock=clock;this.slots=new Map();this.sequences=new Map();this.retiredTurns=new Set();this.turn=null;this.destination='browser';}
  beginTurn(turn){if(this.retiredTurns.has(turn))return false;if(this.turn&&this.turn!==turn)this.retiredTurns.add(this.turn);if(this.retiredTurns.size>64)this.retiredTurns.delete(this.retiredTurns.values().next().value);this.turn=turn;this.slots.delete('playback');this.slots.delete('error');this.slots.delete('conversation');return true;}
  apply(event){
   if(event.version!==1||!states.includes(event.expression)||!Number.isSafeInteger(event.sequence)||event.sequence<0||!priorities[event.source]||!['browser','device','simulation'].includes(event.destination)||typeof event.session_id!=='string'||typeof event.event_id!=='string')return false;
   if(event.turn_id&&this.turn&&event.turn_id!==this.turn)return false;
   const key=event.session_id+':'+event.source;
   if(event.sequence<=(this.sequences.get(key)??-1))return false;
   this.sequences.set(key,event.sequence);if(this.sequences.size>64)this.sequences.delete(this.sequences.keys().next().value);
   const duration=Math.max(100,Math.min(60000,Number(event.duration_ms)||5000));
   if(event.expression==='idle'){this.slots.delete(event.source);return true;}
   this.slots.set(event.source,{...event,priority:priorities[event.source],expires:this.clock()+duration});
   return true;
  }
  current(){let chosen=null;for(const [source,event]of this.slots){if(event.expression!=='offline'&&event.expires<=this.clock()){this.slots.delete(source);continue;}if(!chosen||event.priority>chosen.priority)chosen=event;}return chosen?.expression||'idle';}
 }
 root.BellaExpressionController=ExpressionController;
 const session=globalThis.crypto?.randomUUID?.()||String(Date.now());let sequence=0,turn=null;
 const controller=new ExpressionController();
 let channel=null;try{if(typeof BroadcastChannel!=='undefined')channel=new BroadcastChannel('bella-expression-v1');}catch{/* Local file preview remains standalone. */}
 root.BellaExpressions={controller,beginTurn(id){turn=id;controller.beginTurn(id);},
  emit(expression,source='conversation',duration=60000){const event={version:1,event_id:session+':'+(++sequence),session_id:session,device_id:null,turn_id:turn,destination:'browser',source,sequence,priority:priorities[source],expression,duration_ms:duration,intensity:1};controller.apply(event);channel?.postMessage(event);root.dispatchEvent?.(new CustomEvent('bella-expression',{detail:event}));return event;}};
 channel&&(channel.onmessage=({data})=>{if(data?.destination!=='browser')return;if(data.source==='conversation'&&['listening','thinking'].includes(data.expression)&&data.turn_id!==controller.turn)controller.beginTurn(data.turn_id);if(controller.apply(data))root.dispatchEvent?.(new CustomEvent('bella-expression',{detail:data}));});
 if(typeof module!=='undefined')module.exports={ExpressionController};
})(typeof window==='undefined'?globalThis:window);
