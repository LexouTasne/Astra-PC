const state = {
  view: 'chat',
  status: null,
  busy: false,
  running: { voice: false, gestures: false },
  logs: [],
  sessions: JSON.parse(localStorage.getItem('astra.sessions') || '[]'),
  currentSession: null,
  theme: localStorage.getItem('astra.theme') || 'dark',
}

const $ = sel => document.querySelector(sel)
const $$ = sel => [...document.querySelectorAll(sel)]

const titles = {
  chat: ['Chat', 'Qwen3 · local'],
  voice: ['Voz', 'Conversa local em tempo real'],
  gestures: ['Gestos', 'Controle seguro por visão'],
  devices: ['Dispositivos', 'Astra Mesh'],
  setup: ['Setup', 'Configuração do sistema'],
  logs: ['Atividade', 'Processos e diagnósticos'],
}

document.documentElement.dataset.theme = state.theme

function escapeHtml(value='') {
  return String(value)
    .replaceAll('&','&amp;').replaceAll('<','&lt;')
    .replaceAll('>','&gt;').replaceAll('"','&quot;')
}

function toast(message, type='info') {
  const el = document.createElement('div')
  el.className = `toast ${type}`
  el.innerHTML = `<i></i><span>${escapeHtml(message)}</span>`
  $('#toastStack').appendChild(el)
  requestAnimationFrame(() => el.classList.add('show'))
  setTimeout(() => {
    el.classList.remove('show')
    setTimeout(() => el.remove(), 250)
  }, 3200)
}

function log(text, kind='stdout', id='system') {
  const clean = String(text ?? '')
  if (!clean) return
  state.logs.push({ text: clean, kind, id, at: new Date().toISOString() })
  if (state.logs.length > 1000) state.logs.splice(0, state.logs.length - 1000)
  const pane = $('#activityLog')
  pane.textContent += clean
  pane.scrollTop = pane.scrollHeight
}

function setView(view) {
  state.view = view
  $$('.view').forEach(el => el.classList.toggle('active', el.id === `view-${view}`))
  $$('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === view))
  const [title, subtitle] = titles[view] || [view, 'Astra']
  $('#pageTitle').textContent = title
  $('#pageSubtitle').textContent = subtitle
  if (view === 'logs') {
    const pane = $('#activityLog')
    pane.scrollTop = pane.scrollHeight
  }
}

function setDot(id, ok, pending=false) {
  const dot = $(id)
  if (!dot) return
  dot.className = 'dot'
  if (pending) dot.classList.add('pending')
  else dot.classList.add(ok ? 'ok' : 'bad')
}

async function refreshStatus(silent=false) {
  try {
    const status = await window.astra.status()
    state.status = status
    const daemon = Boolean(status.daemon?.online)
    const starting = Boolean(status.daemon?.starting)
    const mesh = Boolean(status.mesh?.enabled || status.mesh?.online)
    const camera = Boolean(status.camera?.available)
    const voice = Boolean(status.voice?.configured)
    $('#statusDaemon').textContent = daemon ? 'Online' : (starting ? 'Iniciando' : 'Offline')
    $('#statusCamera').textContent = camera ? (status.camera.label || 'Pronta') : 'Indisponível'
    $('#statusVoice').textContent = voice ? 'Configurada' : 'Setup'
    $('#statusMesh').textContent = mesh ? 'Ativo' : 'Offline'
    setDot('#dotDaemon', daemon, starting)
    setDot('#dotCamera', camera)
    setDot('#dotVoice', voice)
    setDot('#dotMesh', mesh)
    $('#runtimePlatform').textContent = status.platform || 'Local'
    $('#runtimeModel').textContent = status.model || 'qwen3:0.6b'
    $('#voiceMic').textContent = status.voice?.microphone || 'Padrão do sistema'
    $('#voiceAsr').textContent = `${status.voice?.asr || 'small'} · pt-BR`
    $('#voiceTts').textContent = status.voice?.tts || 'Piper'
    const pill = $('#daemonPill')
    pill.classList.toggle('online', daemon)
    pill.classList.toggle('pending', starting)
    pill.querySelector('span').textContent = daemon ? 'Astra online' : (starting ? 'Iniciando' : 'Daemon offline')
    if (!silent && !status.ok) toast(status.error || 'Status parcial', 'warn')
  } catch (error) {
    if (!silent) toast('Não consegui ler o status da Astra', 'error')
  }
}

function saveSessions() {
  localStorage.setItem('astra.sessions', JSON.stringify(state.sessions.slice(0, 24)))
  renderRecents()
}

function renderRecents() {
  const list = $('#recentList')
  list.innerHTML = ''
  if (!state.sessions.length) {
    list.innerHTML = '<div class="recent-empty">Suas conversas aparecem aqui.</div>'
    return
  }
  for (const session of state.sessions.slice(0, 12)) {
    const button = document.createElement('button')
    button.className = 'recent-item'
    button.innerHTML = `<span>◌</span><div><strong>${escapeHtml(session.title || 'Conversa')}</strong><small>${new Date(session.updated).toLocaleDateString('pt-BR')}</small></div>`
    button.onclick = () => loadSession(session.id)
    list.appendChild(button)
  }
}

function currentSession() {
  if (!state.currentSession) {
    const session = { id: crypto.randomUUID(), title: 'Nova conversa', updated: Date.now(), messages: [] }
    state.sessions.unshift(session)
    state.currentSession = session.id
    saveSessions()
  }
  return state.sessions.find(s => s.id === state.currentSession)
}

function loadSession(id) {
  const session = state.sessions.find(s => s.id === id)
  if (!session) return
  state.currentSession = id
  setView('chat')
  renderMessages(session.messages)
}

function newSession() {
  state.currentSession = null
  $('#messages').innerHTML = ''
  $('#messages').appendChild(makeHero())
  $('#composerInput').focus()
}

function makeHero() {
  const template = document.createElement('template')
  template.innerHTML = `<div class="hero" id="chatHero">
    <div class="hero-orb"><span>A</span></div>
    <h1>O que vamos fazer?</h1>
    <p>Astra está no seu PC. Converse, controle o sistema ou abra uma ferramenta.</p>
    <div class="suggestions">
      <button data-prompt="O que você consegue fazer no meu PC?">O que você consegue fazer?</button>
      <button data-prompt="Analise o estado atual do meu sistema.">Ver status do PC</button>
      <button data-action="voice-start">Conversar por voz</button>
      <button data-view="gestures">Configurar gestos</button>
    </div>
  </div>`
  const node = template.content.firstElementChild
  bindDynamic(node)
  return node
}

function renderMessages(messages=[]) {
  const root = $('#messages')
  root.innerHTML = ''
  if (!messages.length) {
    root.appendChild(makeHero())
    return
  }
  for (const message of messages) appendMessage(message.role, message.text, false)
  root.scrollTop = root.scrollHeight
}

function appendMessage(role, text, persist=true) {
  $('#chatHero')?.remove()
  const root = $('#messages')
  const el = document.createElement('article')
  el.className = `message ${role}`
  el.innerHTML = role === 'user'
    ? `<div class="bubble user-bubble">${escapeHtml(text)}</div>`
    : `<div class="assistant-row"><div class="assistant-avatar">A</div><div class="assistant-content"><div class="assistant-name">Astra</div><div class="assistant-text">${escapeHtml(text).replaceAll('\n','<br>')}</div></div></div>`
  root.appendChild(el)
  root.scrollTop = root.scrollHeight
  if (persist) {
    const session = currentSession()
    session.messages.push({ role, text })
    session.updated = Date.now()
    if (role === 'user' && session.messages.filter(x => x.role === 'user').length === 1) {
      session.title = text.slice(0, 38) || 'Conversa'
    }
    saveSessions()
  }
  return el
}

function appendThinking() {
  $('#chatHero')?.remove()
  const root = $('#messages')
  const el = document.createElement('article')
  el.className = 'message assistant thinking'
  el.innerHTML = `<div class="assistant-row"><div class="assistant-avatar pulse">A</div><div class="assistant-content"><div class="assistant-name">Astra</div><div class="thinking-line"><i></i><i></i><i></i></div></div></div>`
  root.appendChild(el)
  root.scrollTop = root.scrollHeight
  return el
}

async function sendMessage(prefill=null) {
  if (state.busy) return
  const input = $('#composerInput')
  const text = String(prefill ?? input.value).trim()
  if (!text) return
  input.value = ''
  autoResize()
  appendMessage('user', text)
  const thinking = appendThinking()
  state.busy = true
  $('#sendButton').classList.add('busy')
  try {
    const result = await window.astra.ask(text)
    thinking.remove()
    if (result.ok && result.text) appendMessage('assistant', result.text.trim())
    else {
      appendMessage('assistant', 'Não consegui responder agora. Veja Atividade para o erro.')
      log((result.error || 'Erro desconhecido') + '\n', 'stderr', 'chat')
    }
  } catch (error) {
    thinking.remove()
    appendMessage('assistant', 'O backend da Astra não respondeu.')
    log(String(error) + '\n', 'stderr', 'chat')
  } finally {
    state.busy = false
    $('#sendButton').classList.remove('busy')
  }
}

async function runAction(action) {
  const actions = {
    'voice-start': () => toggleLong('voice', ['voice', '--engine', 'fast']),
    'voice-toggle': () => toggleLong('voice', ['voice', '--engine', 'fast']),
    'gesture-start': () => toggleLong('gestures', ['gestures', '--show-camera']),
    'gesture-tutorial': () => window.astra.run(['gestures', '--tutorial']),
    'gesture-setup': () => window.astra.run(['setup', 'gestures', '--yes']),
    'voice-setup': () => window.astra.run(['setup', 'voice', '--yes']),
    'camera-setup': () => window.astra.run(['setup', 'camera', '--yes']),
    'pair': async () => {
      setView('devices')
      const result = await window.astra.run(['mesh', 'pair-code'])
      $('#devicesOutput').textContent = result.stdout || result.stderr || 'Sem saída.'
    },
    'devices-refresh': async () => {
      const result = await window.astra.run(['mesh', 'devices'])
      $('#devicesOutput').textContent = result.stdout || result.stderr || 'Nenhum dispositivo.'
    },
    'screen': async () => {
      setView('chat')
      await sendMessage('O que está acontecendo na minha tela agora?')
    },
    'move-install': async () => {
      const folder = await window.astra.chooseFolder()
      if (!folder) return
      toast('Preparando instalação no novo local…')
      window.astra.run(['setup', 'location', folder, '--yes'])
      setView('logs')
    },
    'update': () => {
      window.astra.run(['desktop-update'])
      setView('logs')
    },
  }
  const fn = actions[action]
  if (!fn) return
  try { await fn() }
  catch (error) { toast(String(error), 'error') }
}

async function toggleLong(id, args) {
  const result = await window.astra.longToggle(id, args)
  state.running[id] = Boolean(result.running)
  if (id === 'voice') {
    const button = $('#voiceToggleButton')
    button.textContent = state.running.voice ? 'Parar voz' : 'Iniciar voz'
    button.classList.toggle('danger', state.running.voice)
  }
  toast(state.running[id] ? `${id === 'voice' ? 'Voz' : 'Gestos'} iniciado` : 'Processo encerrado')
}

function bindDynamic(root=document) {
  root.querySelectorAll?.('[data-view]').forEach(el => {
    el.addEventListener('click', e => {
      e.preventDefault()
      setView(el.dataset.view)
    })
  })
  root.querySelectorAll?.('[data-action]').forEach(el => {
    el.addEventListener('click', e => {
      e.preventDefault()
      runAction(el.dataset.action)
    })
  })
  root.querySelectorAll?.('[data-prompt]').forEach(el => {
    el.addEventListener('click', () => sendMessage(el.dataset.prompt))
  })
}

function autoResize() {
  const input = $('#composerInput')
  input.style.height = 'auto'
  input.style.height = Math.min(input.scrollHeight, 160) + 'px'
}

window.astra.onProcessLine(payload => {
  log(payload.text, payload.kind, payload.id)
  if (state.view !== 'logs' && payload.kind === 'stderr' && /error|traceback|failed/i.test(payload.text)) {
    toast('Um processo da Astra reportou erro. Veja Atividade.', 'warn')
  }
})
window.astra.onProcessExit(payload => {
  if (payload.id === 'voice' || payload.id === 'gestures') {
    state.running[payload.id] = false
    if (payload.id === 'voice') $('#voiceToggleButton').textContent = 'Iniciar voz'
  }
  refreshStatus(true)
})

$('#sendButton').onclick = () => sendMessage()
$('#composerInput').addEventListener('input', autoResize)
$('#composerInput').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
})
$('#newChat').onclick = newSession
$('#micButton').onclick = () => { setView('voice'); runAction('voice-toggle') }
$('#refreshStatus').onclick = () => refreshStatus()
$('#panelRefresh').onclick = () => refreshStatus()
$('#clearLogs').onclick = () => { state.logs = []; $('#activityLog').textContent = '' }
$('#clearHistory').onclick = () => {
  if (!confirm('Limpar o histórico local da GUI?')) return
  state.sessions = []
  state.currentSession = null
  saveSessions()
  newSession()
}
$('#themeToggle').onclick = () => {
  state.theme = state.theme === 'dark' ? 'light' : 'dark'
  document.documentElement.dataset.theme = state.theme
  localStorage.setItem('astra.theme', state.theme)
}
$('#sidebarCollapse').onclick = () => document.body.classList.toggle('sidebar-collapsed')
$('#mobileMenu').onclick = () => document.body.classList.toggle('sidebar-open')

document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'n') {
    event.preventDefault(); newSession()
  }
})
bindDynamic()
renderRecents()
renderMessages([])
refreshStatus(true)
setInterval(() => refreshStatus(true), 6000)
