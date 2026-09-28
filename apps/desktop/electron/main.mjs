import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import { spawn } from 'node:child_process'
import crypto from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(__dirname, '..')
const astraRoot = process.env.ASTRA_ROOT || path.resolve(desktopRoot, '..', '..')
const python = process.env.ASTRA_PYTHON || 'python'
const running = new Map()

let mainWindow = null

function pythonArgs(args) {
  return ['-m', 'astra_pc', ...args]
}

function spawnAstra(args, { id = crypto.randomUUID(), interactive = false } = {}) {
  const child = spawn(python, pythonArgs(args), {
    cwd: astraRoot,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      ASTRA_DESKTOP: '1'
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    detached: false
  })

  running.set(id, child)

  const emit = (stream, chunk) => {
    mainWindow?.webContents.send('astra:process', {
      id,
      stream,
      text: chunk.toString()
    })
  }

  child.stdout?.on('data', chunk => emit('stdout', chunk))
  child.stderr?.on('data', chunk => emit('stderr', chunk))
  child.on('exit', code => {
    running.delete(id)
    mainWindow?.webContents.send('astra:process', {
      id,
      stream: 'exit',
      code: code ?? 0,
      text: ''
    })
  })

  if (!interactive) {
    child.stdin?.end()
  }
  return { id, child }
}

function collectAstra(args, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, pythonArgs(args), {
      cwd: astraRoot,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        ASTRA_DESKTOP: '1'
      },
      stdio: ['ignore', 'pipe', 'pipe']
    })

    let stdout = ''
    let stderr = ''
    const timer = setTimeout(() => {
      child.kill('SIGTERM')
      reject(new Error(stderr.trim() || `Astra demorou mais de ${timeoutMs / 1000}s`))
    }, timeoutMs)

    child.stdout.on('data', chunk => { stdout += chunk.toString() })
    child.stderr.on('data', chunk => { stderr += chunk.toString() })
    child.on('error', error => {
      clearTimeout(timer)
      reject(error)
    })
    child.on('close', code => {
      clearTimeout(timer)
      if (code === 0) resolve(stdout.trim())
      else reject(new Error(stderr.trim() || stdout.trim() || `Astra saiu com código ${code}`))
    })
  })
}

const actionMap = {
  voice: ['voice', '--engine', 'fast'],
  gestures: ['gestures'],
  'gestures-tutorial': ['gestures', '--tutorial'],
  'gestures-safe-preview': ['gestures', '--show-camera'],
  awareness: ['awareness'],
  'setup-voice': ['setup', 'voice', '--yes'],
  'setup-gestures': ['setup', 'gestures', '--yes'],
  'setup-camera': ['setup', 'camera'],
  'mesh-pair': ['mesh', 'pair-code'],
  benchmark: ['benchmark', '--rounds', '2']
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1380,
    height: 880,
    minWidth: 980,
    minHeight: 680,
    backgroundColor: '#08090c',
    title: 'Astra',
    frame: false,
    titleBarStyle: 'hidden',
    trafficLightPosition: { x: 18, y: 16 },
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  })

  mainWindow.loadFile(path.join(desktopRoot, 'dist', 'index.html'))
  mainWindow.once('ready-to-show', () => mainWindow?.show())
  mainWindow.on('closed', () => { mainWindow = null })
}

ipcMain.handle('astra:status', async () => {
  try {
    const raw = await collectAstra(['desktop-status'], 5000)
    return JSON.parse(raw)
  } catch (error) {
    return {
      ok: false,
      error: error.message,
      daemon: { online: false, starting: false },
      camera: { available: false, label: 'Indisponível' },
      voice: { configured: false, microphone: '—', asr: '—', tts: '—' },
      mesh: { enabled: true, online: false },
      model: '—',
      platform: process.platform
    }
  }
})

ipcMain.handle('astra:ask', async (_event, prompt) => {
  const text = String(prompt || '').trim()
  if (!text) return { ok: false, error: 'Mensagem vazia.' }
  try {
    const answer = await collectAstra(['ask', text], 45000)
    return { ok: true, answer }
  } catch (error) {
    return { ok: false, error: error.message }
  }
})

ipcMain.handle('astra:run', async (_event, payload) => {
  const action = String(payload?.command || '')
  const base = actionMap[action]
  if (!base) return { ok: false, error: 'Ação não permitida pela GUI.' }

  const extra = Array.isArray(payload?.args)
    ? payload.args.map(value => String(value)).filter(value => value.length < 300)
    : []

  const { id } = spawnAstra([...base, ...extra])
  return { ok: true, id }
})

ipcMain.handle('astra:stop', async (_event, id) => {
  const child = running.get(String(id))
  if (!child) return { ok: false, error: 'Processo não encontrado.' }
  try {
    child.kill('SIGINT')
    setTimeout(() => {
      if (!child.killed) child.kill('SIGTERM')
    }, 1200)
    return { ok: true }
  } catch (error) {
    return { ok: false, error: error.message }
  }
})

ipcMain.handle('astra:update', async () => {
  try {
    const output = await collectAstra(['desktop-update'], 60000)
    return { ok: true, output }
  } catch (error) {
    return { ok: false, error: error.message }
  }
})

ipcMain.handle('astra:choose-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory', 'createDirectory']
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('astra:window', (_event, action) => {
  if (!mainWindow) return false
  if (action === 'minimize') mainWindow.minimize()
  if (action === 'maximize') {
    mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize()
  }
  if (action === 'close') mainWindow.close()
  return true
})

app.whenReady().then(createWindow)
app.on('window-all-closed', () => {
  for (const child of running.values()) {
    try { child.kill('SIGTERM') } catch {}
  }
  if (process.platform !== 'darwin') app.quit()
})
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})
