"use strict";
const http = require("http");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { spawn } = require("child_process");
const { WebSocketServer } = require("ws");

// TLS certs
const PORT = parseInt(process.env.PORT || "3000");
const WORKDIR = process.env.WORKDIR || "/home/claude";
const PASSWORD = process.env.PASSWORD || "claude";

// ── auth ──
const sessions = new Map();
const TTL = 30 * 24 * 60 * 60 * 1000;
function auth(req) {
  const m = (req.headers.cookie || "").match(/token=([a-f0-9]+)/);
  if (!m) return false;
  const exp = sessions.get(m[1]);
  return exp && exp > Date.now();
}

// ── claude process ──
let proc = null, claudeBuf = "", sessionId = null, currentCwd = "";

function killClaude() { if (proc) { try { proc.kill(); } catch {} proc = null; } }

function sendCmd(cwd, text, ws, resumeId) {
  killClaude();
  currentCwd = cwd;
  claudeBuf = "";

  const args = ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"];
  if (resumeId) args.push("--resume", resumeId);
  // Handle /effort: extract level and add --effort flag
  const effortMatch = text.match(/^\/effort\s+(\w+)/);
  if (effortMatch) { args.push("--effort", effortMatch[1]); text = text.replace(/^\/effort\s+\w+\s*/, ""); if (!text.trim()) text = "继续"; }

  proc = spawn("claude", args, {
    cwd,
    env: { ...process.env, HOME: process.env.HOME || "/home/claude", NO_COLOR: "1" },
    stdio: ["pipe", "pipe", "pipe"],
  });

  // Send message as JSON
  const input = JSON.stringify({ type: "user", message: { role: "user", content: text } }) + "\n";
  proc.stdin.write(input);

  proc.stdout.on("data", (d) => {
    claudeBuf += d.toString("utf-8");
    const lines = claudeBuf.split("\n");
    claudeBuf = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const msg = JSON.parse(line);
        if (ws.readyState === 1) ws.send(JSON.stringify({ type: "json", data: msg }));
        if (msg.type === "system" && msg.session_id) sessionId = msg.session_id;
        if (msg.type === "result" && msg.subtype === "success") proc = null;
      } catch {}
    }
  });

  proc.stderr.on("data", (d) => {
    if (ws.readyState === 1) ws.send(JSON.stringify({ type: "err", text: d.toString("utf-8") }));
  });

  proc.on("close", () => {
    proc = null;
    if (ws.readyState === 1) ws.send(JSON.stringify({ type: "done", sessionId }));
  });
}

// ── http server ──
const server = http.createServer((req, res) => {
  const u = new URL(req.url, "http://localhost");

  if (u.pathname === "/api/login" && req.method === "POST") {
    let b = "";
    req.on("data", (c) => (b += c));
    req.on("end", () => {
      try { if (JSON.parse(b).password !== PASSWORD) throw 0; }
      catch { res.writeHead(403); return res.end(); }
      const token = crypto.randomBytes(32).toString("hex");
      sessions.set(token, Date.now() + TTL);
      res.writeHead(200, { "set-cookie": `token=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${TTL / 1000}` });
      res.end(JSON.stringify({ ok: true }));
    });
    return;
  }

  if (u.pathname === "/api/dirs") {
    if (!auth(req)) return sendLogin(res);
    if (req.method === "GET") {
      const dirs = [];
      try { for (const f of fs.readdirSync(WORKDIR, { withFileTypes: true }))
        if (f.isDirectory() && !f.name.startsWith(".")) dirs.push({ name: f.name, path: path.join(WORKDIR, f.name) }); } catch {}
      res.writeHead(200, { "content-type": "application/json" });
      return res.end(JSON.stringify(dirs));
    }
    if (req.method === "POST") {
      let b = "";
      req.on("data", (c) => (b += c));
      req.on("end", () => {
        try { const d = path.join(WORKDIR, JSON.parse(b).name); fs.mkdirSync(d, { recursive: true });
          res.writeHead(200); return res.end(JSON.stringify({ ok: true, path: d })); }
        catch (e) { res.writeHead(500); return res.end(JSON.stringify({ error: e.message })); }
      });
      return;
    }
  }

  if (!auth(req)) return sendLogin(res);
  if (u.pathname === "/") {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    return res.end(HTML.replace("__WORKDIR__", WORKDIR));
  }
  res.writeHead(404); res.end();
});

function sendLogin(res) {
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(LOGIN_HTML);
}

// ── websocket ──
const wss = new WebSocketServer({ noServer: true });
server.on("upgrade", (req, socket, head) => {
  wss.handleUpgrade(req, socket, head, (ws) => {
    wss.emit("connection", ws, req);
  });
});
wss.on("connection", (ws) => {
  ws.on("message", (raw) => {
    let d;
    try { d = JSON.parse(raw.toString()); } catch { return; }
    if (d.type === "start") { sessionId = null; currentCwd = d.cwd || WORKDIR; ws.send(JSON.stringify({ type: "ready" })); }
    else if (d.type === "send") sendCmd(currentCwd, d.text, ws, sessionId);
    else if (d.type === "new-session") { sessionId = null; ws.send(JSON.stringify({ type: "ready" })); }
    else if (d.type === "stop") killClaude();
  });
  ws.send(JSON.stringify({ type: "ready" }));
});

// ── html ──
const LOGIN_HTML = `<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude Code</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{display:flex;justify-content:center;align-items:center;min-height:100vh;background:#1a1a2e;font-family:-apple-system,sans-serif}
form{background:#16213e;padding:40px;border-radius:12px;width:340px;max-width:90vw}
h1{color:#e0e0e0;text-align:center;margin-bottom:24px;font-size:20px}
input{width:100%;padding:12px;margin-bottom:12px;border:1px solid #333;border-radius:6px;background:#0f3460;color:#e0e0e0;font-size:16px;outline:none}
input:focus{border-color:#e94560}
button{width:100%;padding:12px;background:#e94560;color:#fff;border:none;border-radius:6px;font-size:16px;cursor:pointer}
#err{color:#e94560;text-align:center;margin-bottom:12px;display:none}
</style></head><body>
<form onsubmit="return L(event)"><h1>Claude Code</h1>
<p id="err">密码错误</p><input type="password" id="pw" placeholder="密码" autofocus><button type="submit">登录</button></form>
<script>async function L(e){e.preventDefault()
const r=await fetch("/api/login",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({password:document.getElementById("pw").value})})
r.ok?location.reload():document.getElementById("err").style.display="block"}</script></body></html>`;

const HTML = `<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude Code</title>
<style>
:root{--bg:#1a1a2e;--side:#16213e;--inp:#0f3460;--red:#e94560;--t:#e0e0e0;--m:#888}
*{margin:0;padding:0;box-sizing:border-box}
body{display:flex;height:100vh;background:var(--bg);color:var(--t);font-family:-apple-system,system-ui,sans-serif;overflow:hidden}
#side{width:200px;background:var(--side);padding:10px;display:flex;flex-direction:column;gap:6px;flex-shrink:0;overflow-y:auto}
#side{width:240px}
#side h2{font-size:13px;color:var(--red);cursor:pointer}
#side h2.collapsed+.secBody{display:none}
#side button{width:100%;padding:5px 8px;border:1px solid #333;border-radius:3px;background:var(--inp);color:var(--t);cursor:pointer;text-align:left;font-size:11px;margin-bottom:2px}
#side button:hover{background:#1a3a6e}
#side button.on{background:var(--red);border-color:var(--red)}
#side .secBody{margin-bottom:6px}
#side .secBody button{padding:3px 8px;font-size:10px}
#side .badge{display:inline-block;padding:2px 6px;margin:1px;background:#222;border-radius:3px;font-size:9px;color:var(--m)}
#newd{display:flex;gap:3px}
#newd input{flex:1;padding:5px;border:1px solid #333;border-radius:3px;background:var(--inp);color:var(--t);font-size:11px}
#newd button{padding:5px 8px;width:auto}
#side .inf{font-size:10px;color:var(--m);text-align:center;margin-top:auto}
#main{flex:1;display:flex;flex-direction:column;min-width:0}
#msgs{flex:1;overflow-y:auto;padding:16px}
.msg{margin-bottom:14px}
.msg.user .bubble{background:var(--red);color:#fff;display:inline-block;padding:8px 12px;border-radius:12px;max-width:85%;font-size:14px;float:right;clear:both}
.msg.assistant .text{font-size:14px;line-height:1.6;white-space:pre-wrap}
.msg.assistant .thinking{background:#111;border-left:3px solid #61afef;padding:6px 10px;margin:6px 0;font-size:11px;color:var(--m)}
.msg .tools{font-size:11px;color:var(--m);margin:4px 0}
.msg .cost{font-size:10px;color:var(--m);text-align:center;margin:8px 0}
.spinner{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--red);animation:s 1s infinite;margin-left:3px;vertical-align:middle}
@keyframes s{0%,100%{opacity:0.3}50%{opacity:1}}
#bar{display:flex;gap:5px;padding:6px 10px;border-top:1px solid #333;background:var(--side);align-items:flex-end}
#bar textarea{flex:1;padding:6px 10px;border:1px solid #333;border-radius:4px;background:var(--inp);color:var(--t);font-size:13px;font-family:inherit;resize:none;min-height:34px;max-height:80px;outline:none}
#bar textarea:focus{border-color:var(--red)}
#bar button{padding:6px 14px;background:var(--red);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px;white-space:nowrap;height:34px}
#bar button:disabled{opacity:0.3}
#bar button.sec{background:#333}
@media(max-width:600px){#side{display:none}}
</style></head><body>

<div id="side">
  <h2 onclick="this.classList.toggle('collapsed')">📁 目录</h2>
  <div class="secBody"><div id="list"></div>
  <div id="newd"><input id="dname" placeholder="新建..."><button onclick="C()">＋</button></div>
  <button onclick="NS()" style="color:var(--red);margin-top:4px">新会话</button></div>

  <h2 onclick="this.classList.toggle('collapsed')">⚡ 命令</h2>
  <div class="secBody" id="cmds"><span class="badge">连接后加载</span></div>

  <h2 onclick="this.classList.toggle('collapsed')">🔌 MCP</h2>
  <div class="secBody" id="mcpSec"><span class="badge">连接后加载</span></div>

  <h2 onclick="this.classList.toggle('collapsed')">🧩 Skills</h2>
  <div class="secBody" id="skillSec"><span class="badge">连接后加载</span></div>

  <h2 onclick="this.classList.toggle('collapsed')">🔧 Tools</h2>
  <div class="secBody" id="toolSec"><span class="badge">连接后加载</span></div>

  <div class="inf" id="st">未连接</div>
</div>

<div id="main">
  <div id="msgs"><div class="msg" style="text-align:center;color:var(--m);font-size:12px">选择左侧目录开始</div></div>
  <div id="bar">
    <textarea id="inp" rows="1" placeholder="输入消息或命令 · Enter 发送"
      onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();S()}"></textarea>
    <button id="btn" onclick="S()" disabled>发送</button>
    <button class="sec" onclick="ST()">停止</button>
  </div>
  <div style="display:flex;gap:4px;padding:4px 10px;flex-wrap:wrap;background:#111;border-top:1px solid #222">
    <button onclick="cmd('/init')" style="padding:2px 8px;background:#222;color:#61afef;border:1px solid #333;border-radius:3px;cursor:pointer;font-size:11px">/init</button>
    <button onclick="cmd('/compact')" style="padding:2px 8px;background:#222;color:#61afef;border:1px solid #333;border-radius:3px;cursor:pointer;font-size:11px">/compact</button>
    <button onclick="cmd('/review')" style="padding:2px 8px;background:#222;color:#61afef;border:1px solid #333;border-radius:3px;cursor:pointer;font-size:11px">/review</button>
    <button onclick="cmd('/clear')" style="padding:2px 8px;background:#222;color:#61afef;border:1px solid #333;border-radius:3px;cursor:pointer;font-size:11px">/clear</button>
    <button onclick="cmd('/new')" style="padding:2px 8px;background:#222;color:#61afef;border:1px solid #333;border-radius:3px;cursor:pointer;font-size:11px">/new</button>
    <span style="color:#444;font-size:11px;padding:2px 4px">| 也可直接输入/命令</span>
  </div>
</div>

<script>
function $(id){return document.getElementById(id)}
const $msgs=$("msgs"),$inp=$("inp"),$btn=$("btn"),$list=$("list"),$st=$("st");
let ws=null,cwd="",sid=null,loading=false;

(async function(){
  const r=await fetch("/api/dirs"),dirs=await r.json();
  $list.innerHTML="";
  dirs.forEach(d=>{
    const b=document.createElement("button");
    b.textContent=d.name;b.onclick=function(){X(d.path)};
    $list.appendChild(b)
  });
  $st.textContent=dirs.length+" 目录";
})();

async function C(){const n=document.getElementById("dname").value.trim();if(!n)return
  await fetch("/api/dirs",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({name:n})});location.reload()}

function NS(){sid=null;$msgs.innerHTML='<div class="msg" style="text-align:center;color:var(--m);font-size:12px">新会话</div>';if(ws)ws.send(JSON.stringify({type:"new-session"}))}

function X(dir){
  cwd=dir;sid=null;$msgs.innerHTML='<div class="msg" style="text-align:center;color:var(--m);font-size:12px">启动 Claude in '+dir.split("/").pop()+'...</div>';
  document.querySelectorAll("#list button").forEach(b=>b.classList.remove("on"));
  // Highlight selected
  const btns=document.querySelectorAll("#list button");
  for(let i=0;i<btns.length;i++){if(btns[i].textContent===dir.split("/").pop())btns[i].classList.add("on")}
  if(ws)try{ws.close()}catch{}
  connect();
}

function connect(){
  ws=new WebSocket((location.protocol==="https:"?"wss:":"ws:")+"//"+location.host+"/ws");
  ws.onopen=()=>{ws.send(JSON.stringify({type:"start",cwd}));$btn.disabled=false;$st.textContent="就绪"}
  ws.onmessage=(e)=>{const d=JSON.parse(e.data);
    if(d.type==="json")handleJson(d.data);
    else if(d.type==="err")addMsg("assistant","<div class='text'>"+esc(d.text)+"</div>");
    else if(d.type==="done"){loading=false;$btn.disabled=false;$st.textContent="完成";if(d.sessionId)sid=d.sessionId}
    else if(d.type==="ready"){$btn.disabled=loading}
  };
  ws.onclose=()=>{$btn.disabled=true;$st.textContent="断开";setTimeout(connect,3000)}
}
function handleJson(msg){
  if(msg.type==="system"){
    // Populate sidebar on init
    if(msg.slash_commands){$("cmds").innerHTML=msg.slash_commands.map(c=>'<button onclick="cmd(\'/'+esc(c)+'\')">/'+esc(c)+'</button>').join("")}
    if(msg.mcp_servers){const s=msg.mcp_servers;$("mcpSec").innerHTML=s.length?s.map(m=>'<span class="badge">'+esc(m.name||m)+'</span>').join(""):'<span class="badge">无</span>'}
    if(msg.skills){$("skillSec").innerHTML=msg.skills.map(s=>'<button onclick="cmd(\''+esc(s)+'\')">'+esc(s)+'</button>').join("")}
    if(msg.tools){$("toolSec").innerHTML=msg.tools.map(t=>'<span class="badge">'+esc(t)+'</span>').join(" ")}
    return;
  }
  if(msg.type==="assistant"){
    const c=msg.message.content||[];
    for(const item of c){
      if(item.type==="thinking")addMsg("assistant","<details class='thinking'><summary>思考</summary>"+esc(item.thinking)+"</details>");
      else if(item.type==="text")addMsg("assistant","<div class='text'>"+esc(item.text)+"</div>");
      else if(item.type==="tool_use")addMsg("assistant","<div class='tools'>🔧 "+esc(item.name)+" "+esc(JSON.stringify(item.input||{}).substring(0,150))+"</div>");
    }
  }else if(msg.type==="result"){
    loading=false;$btn.disabled=false;
    addMsg("assistant","<div class='cost'>"+(msg.is_error?"❌":"✅")+" · "+msg.duration_ms+"ms · $"+msg.total_cost_usd+"</div>");
    $st.textContent="完成";
  }
}
function addMsg(cls,html){const d=document.createElement("div");d.className="msg "+cls;d.innerHTML=html;$msgs.appendChild(d);$msgs.scrollTop=$msgs.scrollHeight}
function esc(s){return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}

function cmd(c){$inp.value=c;$inp.focus()}
function S(){
  const t=$inp.value.trim();if(!t||!ws||ws.readyState!==1)return;
  addMsg("user","<div class='bubble'>"+esc(t)+"</div>");
  $inp.value="";loading=true;$btn.disabled=true;$st.textContent="运行中...";
  // Local-only commands
  if(t==="/new"){NS();loading=false;$btn.disabled=false;return}
  if(t==="/clear"){$msgs.innerHTML="";loading=false;$btn.disabled=false;return}
  // Everything else → Claude Code (including /init, /review, /compact, /effort, etc.)
  ws.send(JSON.stringify({type:"send",text:t}));
}
function ST(){if(ws)ws.send(JSON.stringify({type:"stop"}));loading=false;$btn.disabled=false;$st.textContent="已停止"}
</script></body></html>`;

const proto = useTLS ? "https" : "http";
server.listen(PORT, () => console.log(`${proto}://localhost:${PORT} · ${WORKDIR}`));
