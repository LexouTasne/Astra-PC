import {
  Activity,
  Bot,
  Camera,
  ChevronRight,
  Circle,
  Cpu,
  Download,
  Eye,
  Hand,
  Headphones,
  History,
  ImagePlus,
  Laptop,
  Maximize2,
  Menu,
  MessageSquare,
  Mic2,
  Minimize2,
  Network,
  Play,
  Power,
  Radio,
  RefreshCw,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  TerminalSquare,
  Volume2,
  WandSparkles,
  Wifi,
  X,
  Zap
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

const NAV = [
  ['chat', 'Chat', MessageSquare],
  ['voice', 'Voz', Mic2],
  ['gestures', 'Gestos', Hand],
  ['mesh', 'Mesh', Network],
  ['system', 'Sistema', Activity],
  ['setup', 'Setup', Settings2],
]

const EMPTY_STATUS = {
  ok: false,
  daemon: { online: false, starting: false },
  camera: { available: false, label: '—' },
  voice: { configured: false, microphone: '—', asr: '—', tts: '—' },
  mesh: { enabled: true, online: false },
  ai: { online: false },
  model: '—',
  platform: '—'
}

function StatusDot({ online, pending }) {
  return <span className={`status-dot ${online ? 'good' : pending ? 'warn' : 'muted'}`} />
}

function WindowControls() {
  return (
    <div className="window-controls no-drag">
      <button onClick={() => window.astra.window('minimize')} aria-label="Minimizar"><Minimize2 size={14} /></button>
      <button onClick={() => window.astra.window('maximize')} aria-label="Maximizar"><Maximize2 size={13} /></button>
      <button className="close" onClick={() => window.astra.window('close')} aria-label="Fechar"><X size={15} /></button>
    </div>
  )
}

function AstraMark() {
  return (
    <div className="astra-mark">
      <div className="mark-orbit orbit-a" />
      <div className="mark-orbit orbit-b" />
      <div className="mark-core" />
    </div>
  )
}

function Sidebar({ page, setPage, collapsed, setCollapsed, status }) {
  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-top drag-region">
        <div className="brand no-drag" onClick={() => setCollapsed(false)}>
          <AstraMark />
          {!collapsed && <div><strong>ASTRA</strong><span>LOCAL INTELLIGENCE</span></div>}
        </div>
        <button className="icon-btn no-drag sidebar-toggle" onClick={() => setCollapsed(v => !v)}>
          <Menu size={17} />
        </button>
      </div>

      <nav className="nav-list">
        {NAV.map(([id, label, Icon]) => (
          <button
            key={id}
            className={`nav-item ${page === id ? 'active' : ''}`}
            onClick={() => setPage(id)}
            title={collapsed ? label : undefined}
          >
            <span className="nav-icon"><Icon size={18} strokeWidth={1.8} /></span>
            {!collapsed && <span>{label}</span>}
            {!collapsed && page === id && <ChevronRight className="nav-chevron" size={14} />}
          </button>
        ))}
      </nav>

      <div className="sidebar-spacer" />

      <div className="sidebar-foot">
        <div className="mini-status">
          <StatusDot online={!!status?.ai?.online} pending={!!status?.daemon?.starting} />
          {!collapsed && (
            <div>
              <strong>{status?.ai?.online ? 'IA local pronta' : 'IA local offline'}</strong>
              <span>{status?.ai?.online ? 'Ollama conectado' : 'Tentando iniciar'}</span>
            </div>
          )}
        </div>
        {!collapsed && <div className="build-label">ASTRA 0.9 · DESKTOP</div>}
      </div>
    </aside>
  )
}

function Titlebar({ title, subtitle }) {
  return (
    <div className="titlebar drag-region">
      <div className="titlebar-copy">
        <h1>{title}</h1>
        {subtitle && <span>{subtitle}</span>}
      </div>
      <WindowControls />
    </div>
  )
}

function Pill({ children, tone = 'neutral' }) {
  return <span className={`pill ${tone}`}>{children}</span>
}

function StatRow({ icon: Icon, label, value, online, pending }) {
  return (
    <div className="stat-row">
      <span className="stat-icon"><Icon size={15} /></span>
      <div className="stat-copy"><span>{label}</span><strong>{value}</strong></div>
      <StatusDot online={online} pending={pending} />
    </div>
  )
}

function RightRail({ status, onRefresh, visible, setVisible }) {
  if (!visible) {
    return (
      <button className="rail-restore" onClick={() => setVisible(true)} title="Mostrar painel">
        <Activity size={16} />
      </button>
    )
  }

  return (
    <aside className="right-rail">
      <div className="rail-head">
        <div><span>STATUS</span><strong>Astra agora</strong></div>
        <div className="rail-actions">
          <button className="icon-btn" onClick={onRefresh}><RefreshCw size={15} /></button>
          <button className="icon-btn" onClick={() => setVisible(false)}><X size={15} /></button>
        </div>
      </div>

      <div className="health-card">
        <div className="health-glow" />
        <div className="health-title">
          <div className={`health-orb ${status.daemon?.online ? 'online' : ''}`}><Zap size={18} /></div>
          <div>
            <span>NÚCLEO</span>
            <strong>{status.daemon?.online ? 'Pronto' : status.daemon?.starting ? 'Iniciando' : 'Offline'}</strong>
          </div>
        </div>
        <div className="health-meta">{status.model || 'Modelo local'} · {status.platform || 'Desktop'}</div>
      </div>

      <div className="rail-section">
        <span className="section-label">DISPOSITIVOS</span>
        <StatRow icon={Cpu} label="IA local" value={status.ai?.online ? status.model || 'Online' : 'Offline'} online={!!status.ai?.online} />
        <StatRow icon={Camera} label="Câmera" value={status.camera?.label || '—'} online={!!status.camera?.available} />
        <StatRow icon={Mic2} label="Microfone" value={status.voice?.microphone || '—'} online={!!status.voice?.configured} />
        <StatRow icon={Wifi} label="Mesh" value={status.mesh?.online ? 'Online' : 'Offline'} online={!!status.mesh?.online} />
      </div>

      <div className="rail-section">
        <span className="section-label">STACK</span>
        <div className="stack-chip"><Cpu size={13} /><span>{status.model || 'Qwen local'}</span></div>
        <div className="stack-chip"><Headphones size={13} /><span>{status.voice?.asr || 'ASR'} · {status.voice?.tts || 'TTS'}</span></div>
      </div>

      <div className="rail-note">
        <ShieldCheck size={16} />
        <div><strong>Privado por padrão</strong><span>Processamento local sempre que possível.</span></div>
      </div>
    </aside>
  )
}

function EmptyChat({ onPrompt, aiOnline }) {
  return (
    <div className="empty-chat">
      <div className="hero-mark"><AstraMark /></div>
      <Pill><Sparkles size={12} /> ASTRA</Pill>
      <h2>O que você quer fazer?</h2>
      <p>
        {aiOnline
          ? 'Converse com a Astra ou peça uma ação no seu PC.'
          : 'A IA local está iniciando. Você já pode tentar enviar uma mensagem.'}
      </p>
      <div className="suggestions">
        <button onClick={() => onPrompt('O que está aberto no meu PC?')}>O que está aberto no meu PC?</button>
        <button onClick={() => onPrompt('Fecha o Discord')}>Fecha o Discord</button>
        <button onClick={() => onPrompt('Como está o sistema?')}>Como está o sistema?</button>
      </div>
    </div>
  )
}

function loadStoredChat() {
  try {
    const raw = localStorage.getItem('astra.chat.messages')
    const parsed = JSON.parse(raw || '[]')
    return Array.isArray(parsed) ? parsed.slice(-40) : []
  } catch {
    return []
  }
}

function ChatPage({ ask, status, run }) {
  const [messages, setMessages] = useState(loadStoredChat)
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [attachment, setAttachment] = useState(null)
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  useEffect(() => {
    try {
      const serializable = messages.slice(-40).map(({ image, ...message }) => message)
      localStorage.setItem('astra.chat.messages', JSON.stringify(serializable))
    } catch {}
  }, [messages])

  const chooseImage = async () => {
    if (busy) return
    const picked = await window.astra.chooseImage()
    if (!picked) return
    if (picked.error) {
      setMessages(prev => [...prev, { role: 'assistant', text: picked.error }])
      return
    }
    setAttachment(picked)
  }

  const submit = async (override = null) => {
    const typed = String(override ?? value).trim()
    const selected = override === null ? attachment : null
    if ((!typed && !selected) || busy) return

    const prompt = typed || 'Analise esta imagem e descreva o que é importante.'
    if (override === null) {
      setValue('')
      setAttachment(null)
    }

    setMessages(prev => [...prev, {
      role: 'user',
      text: prompt,
      image: selected?.preview || null,
      imageName: selected?.name || null
    }])

    setBusy(true)
    const result = await ask({
      prompt,
      imagePath: selected?.path || null
    })
    setBusy(false)

    setMessages(prev => [...prev, {
      role: 'assistant',
      text: result.ok
        ? result.answer
        : (result.error || 'Astra local está indisponível. Tente novamente em alguns segundos.')
    }])
  }

  return (
    <div className="chat-page">
      <div className="chat-scroll">
        {messages.length === 0 ? <EmptyChat onPrompt={submit} aiOnline={!!status?.ai?.online} /> : (
          <div className="messages">
            {messages.map((message, index) => (
              <div key={index} className={`message ${message.role}`}>
                {message.role === 'assistant' && <div className="assistant-avatar"><AstraMark /></div>}
                <div className="message-body">
                  {message.image && (
                    <div className="message-image-wrap">
                      <img src={message.image} alt={message.imageName || 'Imagem enviada'} className="message-image" />
                      {message.imageName && <span>{message.imageName}</span>}
                    </div>
                  )}
                  <div>{message.text}</div>
                </div>
              </div>
            ))}
            {busy && (
              <div className="message assistant">
                <div className="assistant-avatar"><AstraMark /></div>
                <div className="typing"><i /><i /><i /></div>
              </div>
            )}
            <div ref={endRef} />
          </div>
        )}
      </div>

      <div className="composer-shell">
        {attachment && (
          <div className="attachment-card">
            <img src={attachment.preview} alt={attachment.name} />
            <div><strong>{attachment.name}</strong><span>Imagem pronta para enviar</span></div>
            <button onClick={() => setAttachment(null)} title="Remover imagem"><X size={14} /></button>
          </div>
        )}
        <div className="composer">
          <textarea
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            placeholder={attachment ? 'Pergunte algo sobre a imagem...' : 'Fale com a Astra...'}
            rows={1}
          />
          <div className="composer-actions">
            <button className="composer-tool" onClick={chooseImage} title="Enviar imagem" disabled={busy}>
              <ImagePlus size={17} />
            </button>
            <button className="composer-tool" onClick={() => run('voice')} title="Iniciar voz" disabled={busy}>
              <Mic2 size={17} />
            </button>
            <button
              className="send-btn"
              onClick={() => submit()}
              disabled={(!value.trim() && !attachment) || busy}
            >
              <Send size={16} />
            </button>
          </div>
        </div>
        <span className="composer-hint">Enter envia · Shift+Enter quebra linha · imagem e voz locais</span>
      </div>
    </div>
  )
}

function FeatureHero({ eyebrow, title, body, icon: Icon, children }) {
  return (
    <div className="feature-hero">
      <div className="feature-icon"><Icon size={24} /></div>
      <div className="feature-copy">
        <span>{eyebrow}</span>
        <h2>{title}</h2>
        <p>{body}</p>
      </div>
      <div className="feature-actions">{children}</div>
    </div>
  )
}

function ActionButton({ children, primary, danger, onClick, disabled }) {
  return (
    <button className={`action-btn ${primary ? 'primary' : ''} ${danger ? 'danger' : ''}`} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  )
}

function VoicePage({ run, processes, status }) {
  return (
    <div className="page-scroll">
      <FeatureHero
        eyebrow="VOICE CORE"
        title="Voz natural, local e rápida."
        body="Faster-Whisper para ouvir, Qwen local para pensar e Piper pt-BR para responder."
        icon={Volume2}
      >
        <ActionButton primary onClick={() => run('voice')}><Play size={15} /> Iniciar voz</ActionButton>
        <ActionButton onClick={() => run('setup-voice')}><WandSparkles size={15} /> Reconfigurar</ActionButton>
      </FeatureHero>

      <div className="metric-grid">
        <div className="metric-card"><span>MICROFONE</span><strong>{status.voice?.microphone || 'Padrão'}</strong><small>Entrada ativa</small></div>
        <div className="metric-card"><span>RECONHECIMENTO</span><strong>{status.voice?.asr || 'small'}</strong><small>Faster-Whisper pt-BR</small></div>
        <div className="metric-card"><span>VOZ</span><strong>{status.voice?.tts || 'Piper'}</strong><small>TTS neural local</small></div>
      </div>

      <div className="section-card">
        <div className="card-heading"><div><span>PERFIL RECOMENDADO</span><h3>Natural + baixa latência</h3></div><Pill tone="good">LOCAL</Pill></div>
        <div className="flow-line">
          {['Microfone', 'VAD', 'Whisper', 'Qwen', 'Piper'].map((item, index) => (
            <div key={item} className="flow-item"><strong>{item}</strong>{index < 4 && <ChevronRight size={14} />}</div>
          ))}
        </div>
      </div>
      <ProcessSummary processes={processes} filter="voice" />
    </div>
  )
}

function GesturesPage({ run, processes }) {
  return (
    <div className="page-scroll">
      <FeatureHero
        eyebrow="VISION CONTROL"
        title="Gestos em modo seguro."
        body="O padrão não move o mouse continuamente e não mantém drag. Primeiro você treina, depois libera o controle."
        icon={Hand}
      >
        <ActionButton primary onClick={() => run('gestures-tutorial')}><Eye size={15} /> Abrir tutorial</ActionButton>
        <ActionButton onClick={() => run('gestures-safe-preview')}><Camera size={15} /> Testar câmera</ActionButton>
      </FeatureHero>

      <div className="gesture-grid">
        {[
          ['🤏', 'Pinça', 'Clique esquerdo atômico'],
          ['✌️', 'Dois dedos', 'Scroll vertical'],
          ['👌', 'Polegar + médio', 'Clique direito'],
          ['🖐️', 'Palma', 'Pausar / retomar'],
          ['👐', 'Duas mãos', 'Zoom e rotação'],
          ['☝️', 'Indicador', 'Reconhecimento; air-mouse opcional']
        ].map(([emoji, title, desc]) => (
          <div className="gesture-card" key={title}><div className="gesture-emoji">{emoji}</div><strong>{title}</strong><span>{desc}</span></div>
        ))}
      </div>

      <div className="section-card safe-card">
        <div className="safe-icon"><ShieldCheck size={20} /></div>
        <div><h3>Fail-safe ativo</h3><p>Air-mouse e drag ficam desligados por padrão. Perdeu a mão, fechou ou deu erro: Astra força mouse-up.</p></div>
        <Pill tone="good">SAFE</Pill>
      </div>
      <ProcessSummary processes={processes} filter="gestures" />
    </div>
  )
}

function MeshPage({ run, processes, status }) {
  return (
    <div className="page-scroll">
      <FeatureHero
        eyebrow="ASTRA MESH"
        title="Um Astra em cada dispositivo."
        body="Pareamento local seguro entre PCs e Android, com permissões por dispositivo."
        icon={Network}
      >
        <ActionButton primary onClick={() => run('mesh-pair')}><Radio size={15} /> Gerar pareamento</ActionButton>
      </FeatureHero>
      <div className="section-card">
        <div className="card-heading"><div><span>REDE</span><h3>Mesh local</h3></div><Pill tone={status.mesh?.online ? 'good' : 'neutral'}>{status.mesh?.online ? 'ONLINE' : 'OFFLINE'}</Pill></div>
        <p className="muted-text">HTTPS + WebSocket + mDNS + pairing de uso único. Sem abrir porta pública.</p>
      </div>
      <ProcessSummary processes={processes} filter="mesh" />
    </div>
  )
}

function SystemPage({ status, refresh, run }) {
  return (
    <div className="page-scroll">
      <FeatureHero eyebrow="SYSTEM" title="Tudo que mantém a Astra viva." body="Diagnóstico rápido do núcleo local, dispositivos e modelos." icon={Laptop}>
        <ActionButton onClick={refresh}><RefreshCw size={15} /> Atualizar</ActionButton>
        <ActionButton onClick={() => run('benchmark')}><Activity size={15} /> Benchmark</ActionButton>
      </FeatureHero>
      <div className="system-grid">
        {[
          ['Daemon', status.daemon?.online ? 'Online' : status.daemon?.starting ? 'Iniciando' : 'Offline', Power, status.daemon?.online],
          ['IA local', status.ai?.online ? status.model || 'Online' : 'Offline', Cpu, status.ai?.online],
          ['Câmera', status.camera?.label || '—', Camera, status.camera?.available],
          ['Mesh', status.mesh?.online ? 'Online' : 'Offline', Wifi, status.mesh?.online],
          ['ASR', status.voice?.asr || '—', Headphones, status.voice?.configured],
          ['TTS', status.voice?.tts || '—', Volume2, status.voice?.configured],
        ].map(([title, value, Icon, ok]) => (
          <div className="system-card" key={title}><div className="system-card-icon"><Icon size={18} /></div><span>{title}</span><strong>{value}</strong><StatusDot online={!!ok} /></div>
        ))}
      </div>
    </div>
  )
}

function SetupPage({ run, update }) {
  const [updating, setUpdating] = useState(false)
  const [updateText, setUpdateText] = useState('')

  const doUpdate = async () => {
    setUpdating(true)
    const result = await update()
    setUpdating(false)
    setUpdateText(result.ok ? (result.output || 'Atualizado.') : (result.error || 'Falha ao atualizar.'))
  }

  return (
    <div className="page-scroll">
      <FeatureHero eyebrow="SETUP CENTER" title="Arrume sem decorar comando." body="Repare os módulos da Astra por partes, com logs visíveis e ações claras." icon={Settings2} />
      <div className="setup-grid">
        <SetupCard icon={Mic2} title="Voz" body="Microfone, Whisper e Piper." action="Configurar" onClick={() => run('setup-voice')} />
        <SetupCard icon={Hand} title="Gestos" body="Câmera, MediaPipe e backend de input." action="Diagnosticar" onClick={() => run('setup-gestures')} />
        <SetupCard icon={Camera} title="Câmera" body="Webcam ou DroidCam." action="Reparar" onClick={() => run('setup-camera')} />
        <SetupCard icon={Network} title="Mesh" body="Pareie outro Astra." action="Parear" onClick={() => run('mesh-pair')} />
      </div>
      <div className="section-card update-card">
        <div><span className="section-label">UPDATE</span><h3>Atualizar Astra-PC</h3><p className="muted-text">Faz git pull no checkout atual. Reinicie a GUI depois.</p></div>
        <ActionButton onClick={doUpdate} disabled={updating}>{updating ? <RefreshCw className="spin" size={15} /> : <Download size={15} />} {updating ? 'Atualizando…' : 'Buscar atualização'}</ActionButton>
      </div>
      {updateText && <pre className="inline-log">{updateText}</pre>}
    </div>
  )
}

function SetupCard({ icon: Icon, title, body, action, onClick }) {
  return (
    <div className="setup-card">
      <div className="setup-icon"><Icon size={19} /></div>
      <h3>{title}</h3><p>{body}</p>
      <button onClick={onClick}>{action}<ChevronRight size={14} /></button>
    </div>
  )
}

function ProcessSummary({ processes, filter }) {
  const items = Object.values(processes).filter(item => item.action?.includes(filter))
  if (!items.length) return null
  return (
    <div className="section-card process-card">
      <div className="card-heading"><div><span>ATIVIDADE</span><h3>Processos recentes</h3></div><TerminalSquare size={18} /></div>
      {items.slice(-3).map(item => <div className="process-row" key={item.id}><StatusDot online={item.running} /><strong>{item.action}</strong><span>{item.running ? 'rodando' : `finalizado · ${item.code ?? 0}`}</span></div>)}
    </div>
  )
}

function ActivityDrawer({ logs, processes, onStop, open, setOpen }) {
  const running = Object.values(processes).filter(p => p.running)
  return (
    <div className={`activity-drawer ${open ? 'open' : ''}`}>
      <button className="activity-handle" onClick={() => setOpen(v => !v)}>
        <TerminalSquare size={15} />
        <span>Atividade</span>
        {running.length > 0 && <Pill tone="accent">{running.length} rodando</Pill>}
        <ChevronRight className={open ? 'rotate' : ''} size={15} />
      </button>
      {open && (
        <div className="activity-body">
          <div className="running-list">
            {running.map(proc => (
              <div className="running-item" key={proc.id}>
                <div><StatusDot online /><strong>{proc.action}</strong></div>
                <button onClick={() => onStop(proc.id)}><Square size={13} /> Parar</button>
              </div>
            ))}
          </div>
          <pre className="log-view">{logs.length ? logs.slice(-120).join('') : 'Nenhuma atividade ainda.'}</pre>
        </div>
      )}
    </div>
  )
}

function pageMeta(page) {
  return {
    chat: ['Chat', 'Converse com a Astra local'],
    voice: ['Voz', 'Reconhecimento e resposta neural'],
    gestures: ['Gestos', 'Visão e controle seguro'],
    mesh: ['Mesh', 'Dispositivos conectados'],
    system: ['Sistema', 'Saúde do núcleo local'],
    setup: ['Setup', 'Configuração e reparos']
  }[page]
}

export default function App() {
  const [page, setPage] = useState('chat')
  const [collapsed, setCollapsed] = useState(false)
  const [railVisible, setRailVisible] = useState(true)
  const [status, setStatus] = useState(EMPTY_STATUS)
  const [logs, setLogs] = useState([])
  const [processes, setProcesses] = useState({})
  const [activityOpen, setActivityOpen] = useState(false)

  const refresh = async () => {
    const next = await window.astra.status()
    setStatus(next || EMPTY_STATUS)
  }

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 3500)
    const remove = window.astra.onProcess(event => {
      setProcesses(prev => {
        const current = prev[event.id] || { id: event.id, action: 'Astra', running: true }
        if (event.stream === 'exit') return { ...prev, [event.id]: { ...current, running: false, code: event.code } }
        return prev
      })
      if (event.text) setLogs(prev => [...prev, event.text].slice(-500))
    })
    return () => { clearInterval(timer); remove?.() }
  }, [])

  const run = async (action, args = []) => {
    const result = await window.astra.run(action, args)
    if (result.ok) {
      setProcesses(prev => ({ ...prev, [result.id]: { id: result.id, action, running: true } }))
      setActivityOpen(true)
    } else {
      setLogs(prev => [...prev, `[GUI] ${result.error}\n`])
      setActivityOpen(true)
    }
    return result
  }

  const stop = async id => window.astra.stop(id)
  const ask = prompt => window.astra.ask(prompt)
  const update = () => window.astra.update()

  const [title, subtitle] = pageMeta(page)

  const content = useMemo(() => ({
    chat: <ChatPage ask={ask} status={status} run={run} />,
    voice: <VoicePage run={run} processes={processes} status={status} />,
    gestures: <GesturesPage run={run} processes={processes} />,
    mesh: <MeshPage run={run} processes={processes} status={status} />,
    system: <SystemPage status={status} refresh={refresh} run={run} />,
    setup: <SetupPage run={run} update={update} />
  }), [page, status, processes])

  return (
    <div className="app-shell">
      <div className="ambient ambient-a" />
      <div className="ambient ambient-b" />
      <Sidebar page={page} setPage={setPage} collapsed={collapsed} setCollapsed={setCollapsed} status={status} />
      <main className="main-shell">
        <Titlebar title={title} subtitle={subtitle} />
        <div className="workspace">
          <section className="content-pane">{content[page]}</section>
          <RightRail status={status} onRefresh={refresh} visible={railVisible} setVisible={setRailVisible} />
        </div>
        <ActivityDrawer logs={logs} processes={processes} onStop={stop} open={activityOpen} setOpen={setActivityOpen} />
      </main>
    </div>
  )
}
