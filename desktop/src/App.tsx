import { useEffect, useRef, useState } from "react";
import "./style.css";
type Conversation = { id: string; title: string; updated_at?: string };
type Message = { role: "user" | "assistant"; content: string; created_at?: string };
const API = "http://127.0.0.1:8765/api/v1";
export default function App() {
 const [conversations,setConversations]=useState<Conversation[]>([]);
 const [active,setActive]=useState<string|null>(null);
 const [messages,setMessages]=useState<Message[]>([]);
 const [draft,setDraft]=useState("");
 const [busy,setBusy]=useState(false);
 const [status,setStatus]=useState("Connecting to Evo…");
 const [model,setModel]=useState("—");
 const endRef=useRef<HTMLDivElement>(null);
 async function refreshConversations(){
  const r=await fetch(API+"/conversations"); if(!r.ok) throw new Error("Could not load conversations");
  setConversations(await r.json());
 }
 async function openConversation(id:string){
  setActive(id); const r=await fetch(API+"/conversations/"+encodeURIComponent(id)+"/messages");
  if(!r.ok) throw new Error("Could not load conversation"); setMessages(await r.json());
 }
 async function newConversation(){
  const r=await fetch(API+"/conversations",{method:"POST"}); if(!r.ok) throw new Error("Could not create conversation");
  const c=await r.json(); await refreshConversations(); setActive(c.id); setMessages([]);
 }
 useEffect(()=>{(async()=>{try{
  const h=await fetch(API+"/health"); if(!h.ok) throw new Error("API unavailable");
  const info=await h.json(); setModel(info.model); setStatus("Connected"); await refreshConversations();
 }catch{setStatus("API offline — start the Evo API server");}})();},[]);
 useEffect(()=>{endRef.current?.scrollIntoView({behavior:"smooth"});},[messages]);
 async function send(){
  const text=draft.trim(); if(!text||busy)return;
  let cid=active;
  if(!cid){const r=await fetch(API+"/conversations",{method:"POST"});if(!r.ok){setStatus("Could not create conversation");return;}const c=await r.json();cid=c.id;setActive(cid);}
  setDraft("");setBusy(true);
  setMessages(prev=>[...prev,{role:"user",content:text},{role:"assistant",content:""}]);
  try{
   const response=await fetch(API+"/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({conversation_id:cid,message:text})});
   if(!response.ok||!response.body)throw new Error("Chat request failed");
   const reader=response.body.getReader(),decoder=new TextDecoder();let buffer="";
   while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});
    const frames=buffer.split("\n\n");buffer=frames.pop()||"";
    for(const frame of frames){const event=frame.match(/^event: (.+)$/m)?.[1],data=frame.match(/^data: (.+)$/m)?.[1];if(!data)continue;
     const parsed=JSON.parse(data);
     if(event==="token")setMessages(prev=>{const next=[...prev],last=next[next.length-1];next[next.length-1]={...last,content:last.content+parsed};return next;});
     if(event==="error")throw new Error(parsed.message||"Evo error");
    }
   }
   await refreshConversations();
  }catch(e){const msg=e instanceof Error?e.message:String(e);setStatus(msg);setMessages(prev=>{const next=[...prev],last=next[next.length-1];if(last?.role==="assistant"&&!last.content)next.pop();return next;});}
  finally{setBusy(false);}
 }
 return <div className="shell">
  <aside className="sidebar">
   <div className="brand"><div className="brand-mark">E</div><div><strong>Evo</strong><small>PERSONAL AI</small></div></div>
   <button className="new-chat" onClick={()=>newConversation()}>＋ <span>New conversation</span></button>
   <div className="nav-label">WORKSPACE</div>
   <button className="nav-item selected">◫ <span>Chat</span></button>
   <button className="nav-item disabled" title="Not implemented yet">⌘ <span>Agents</span><em>Later</em></button>
   <button className="nav-item disabled" title="Not implemented yet">◈ <span>Memory</span><em>Later</em></button>
   <button className="nav-item disabled" title="Not implemented yet">▥ <span>Hardware</span><em>Later</em></button>
   <button className="nav-item disabled" title="Not implemented yet">⌁ <span>Experiments</span><em>Later</em></button>
   <div className="history-head">RECENT CHATS</div>
   <div className="history">{conversations.map(c=><button key={c.id} className={active===c.id?"history-item active":"history-item"} onClick={()=>openConversation(c.id)}>{c.title}</button>)}</div>
   <div className="sidebar-bottom"><span className="status-dot"/><span>{status}</span></div>
  </aside>
  <main className="main">
   <header className="topbar"><div><span className="crumb">Workspace</span><span className="slash">/</span><strong>Chat</strong></div><div className="model-pill"><span className="status-dot"/>{model}</div></header>
   <section className="chat-area">
    {messages.length===0?<div className="welcome"><div className="welcome-icon">E</div><h1>What are we working on?</h1><p>Your local-first assistant. Persistent memory, private by default.</p></div>:
     <div className="message-list">{messages.map((m,i)=><article key={i} className={"message "+m.role}><div className="avatar">{m.role==="user"?"Y":"E"}</div><div className="message-body"><div className="message-role">{m.role==="user"?"You":"Evo"}</div><div className="message-content">{m.content||(busy&&i===messages.length-1?<span className="typing">Thinking…</span>:"")}</div></div></article>)}<div ref={endRef}/></div>}
    <div className="composer-wrap"><div className="composer"><textarea value={draft} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send();}}} placeholder="Message Evo…" rows={2}/><button onClick={send} disabled={busy||!draft.trim()} aria-label="Send message">↑</button></div><div className="composer-note">Enter to send · Shift + Enter for a new line · Runs on your configured provider</div></div>
   </section>
  </main>
 </div>;
}
