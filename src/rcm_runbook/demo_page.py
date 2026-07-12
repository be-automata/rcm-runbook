"""Página de chat directo para demos con interesados (sin cuenta os.agno.com).

Un solo enlace con la llave incrustada (`/demo?key=...`) abre un chat mínimo
que conversa con el Facilitador RCM. Pensado para que un no-técnico solo pegue
la URL y escriba. La llave viaja en el enlace, no está incrustada en el HTML.
"""

from __future__ import annotations

DEMO_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Facilitador RCM — Demo</title>
<style>
  :root { --brand:#1F4E78; --bg:#f6f7f9; --user:#1F4E78; --bot:#fff; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:#1a1a1a; height:100dvh; display:flex; flex-direction:column; }
  header { background:var(--brand); color:#fff; padding:14px 18px; font-weight:600;
           display:flex; align-items:center; gap:10px; box-shadow:0 1px 4px rgba(0,0,0,.15); }
  header .dot { width:9px; height:9px; border-radius:50%; background:#8bd450; }
  header small { font-weight:400; opacity:.85; margin-left:auto; font-size:12px; }
  #log { flex:1; overflow-y:auto; padding:18px; display:flex; flex-direction:column; gap:12px; }
  .msg { max-width:min(680px,88%); padding:11px 14px; border-radius:14px; line-height:1.45;
         white-space:pre-wrap; word-wrap:break-word; box-shadow:0 1px 2px rgba(0,0,0,.08); }
  .user { align-self:flex-end; background:var(--user); color:#fff; border-bottom-right-radius:4px; }
  .bot  { align-self:flex-start; background:var(--bot); border-bottom-left-radius:4px; }
  .bot h1,.bot h2,.bot h3 { font-size:1em; margin:.4em 0 .2em; }
  .meta { align-self:center; font-size:12px; color:#888; }
  .tools { align-self:flex-start; font-size:12px; color:#6a7; background:#eefaef;
           padding:4px 10px; border-radius:10px; }
  form { display:flex; gap:8px; padding:12px; background:#fff; border-top:1px solid #e6e6e6; }
  #inp { flex:1; padding:12px 14px; border:1px solid #d0d5db; border-radius:12px; font-size:15px;
         resize:none; max-height:120px; font-family:inherit; }
  button { background:var(--brand); color:#fff; border:0; border-radius:12px; padding:0 18px;
           font-size:15px; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  .err { color:#c0392b; }
  .hint { align-self:center; color:#999; font-size:13px; text-align:center; max-width:520px; }
</style>
</head>
<body>
<header>
  <span class="dot"></span> Facilitador RCM
  <small>Análisis RCM asistido — demo</small>
</header>
<div id="log">
  <div class="hint">Cuéntele al facilitador qué equipo quiere analizar. Por ejemplo:
  «Hola, soy Carlos de mantenimiento. Queremos hacer el análisis RCM de la bomba P-101.»</div>
</div>
<form id="f">
  <textarea id="inp" rows="1" placeholder="Escriba su mensaje…" autocomplete="off"></textarea>
  <button id="send" type="submit">Enviar</button>
</form>
<script>
(function(){
  var log = document.getElementById('log');
  var inp = document.getElementById('inp');
  var send = document.getElementById('send');
  var form = document.getElementById('f');
  var key = new URLSearchParams(location.search).get('key') || '';
  var sessionId = 'demo-' + Math.random().toString(36).slice(2,10);

  function add(cls, text){
    var d = document.createElement('div');
    d.className = 'msg ' + cls;
    d.textContent = text;
    log.appendChild(d); log.scrollTop = log.scrollHeight;
    return d;
  }
  function note(cls, text){
    var d = document.createElement('div');
    d.className = cls; d.textContent = text;
    log.appendChild(d); log.scrollTop = log.scrollHeight;
    return d;
  }
  if(!key){ note('meta err', 'Falta la llave de acceso en el enlace (?key=...). Pídala a quien le compartió esta demo.'); send.disabled = true; }

  inp.addEventListener('input', function(){ inp.style.height='auto'; inp.style.height=Math.min(inp.scrollHeight,120)+'px'; });
  inp.addEventListener('keydown', function(e){ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); form.requestSubmit(); }});

  form.addEventListener('submit', async function(e){
    e.preventDefault();
    var text = inp.value.trim();
    if(!text || send.disabled) return;
    add('user', text);
    inp.value=''; inp.style.height='auto';
    send.disabled = true;
    var thinking = note('meta', 'El facilitador está escribiendo…');
    try {
      var fd = new FormData();
      fd.append('message', text);
      fd.append('stream', 'false');
      fd.append('session_id', sessionId);
      var r = await fetch('/agents/facilitador-rcm/runs', {
        method:'POST',
        headers: { 'Authorization': 'Bearer ' + key },
        body: fd
      });
      thinking.remove();
      if(r.status === 401){ note('meta err','Llave de acceso inválida. Pida un enlace nuevo.'); return; }
      if(!r.ok){ note('meta err','Error del servidor ('+r.status+'). Intente de nuevo en un momento.'); return; }
      var d = await r.json();
      var nTools = (d.tools && d.tools.length) || 0;
      if(nTools){ note('tools', '🔧 '+nTools+' herramienta(s) ejecutada(s)'); }
      add('bot', (d.content || '(sin respuesta)').trim());
    } catch(err) {
      thinking.remove();
      note('meta err', 'No se pudo conectar. Verifique su conexión e intente de nuevo.');
    } finally {
      send.disabled = false; inp.focus();
    }
  });
  inp.focus();
})();
</script>
</body>
</html>"""
