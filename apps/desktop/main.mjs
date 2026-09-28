import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ASTRA_ROOT = process.env.ASTRA_ROOT || path.resolve(__dirname, '../..')
const ASTRA_PYTHON = process.env.ASTRA_PYTHON || process.env.PYTHON || 'python3'
const processes = new Map()
let mainWindow = null

if (process.platform === 'linux' && process.env.WAYLAND_DISPLAY) {
  app.commandLine.appendSwitch('ozone-platform-hint', 'auto')
}

function emit(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, payload)
}

function runAstra(args, { id = null, stream = true, timeout = 0 } = {}) {
  return new Promise((resolve) => {
    const child = spawn(ASTRA_PYTHON, ['-m', 'astra_pc', ...args], {
      cwd: ASTRA_ROOT,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const processId = id || `run-${Date.now()}`
    processes.set(processId, child)
    let stdout = ''
    let stderr = ''
    let timer = null

    const forward = (kind, chunk) => {
      const text = chunk.toString()
      if (kind === 'stdout') stdout += text
      else stderr += text
      if (stream) emit('astra:process-line', { id: processId, kind, text })
    }
    child.stdout.on('data', chunk => forward('stdout', chunk))
    child.stderr.on('data', chunk => forward('stderr', chunk))

    if (timeout > 0) {
      timer = setTimeout(() => {
        try { child.kill('SIGTERM') } catch {}
      }, timeout)
    }

    child.on('close', code => {
      if (timer) clearTimeout(timer)
      processes.delete(processId)
      emit('astra:process-exit', { id: processId, code })
      resolve({ id: processId, code, stdout, stderr })
    })
    child.on('error', error => {
      if (timer) clearTimeout(timer)
      processes.delete(processId)
      resolve({ id: processId, code: -1, stdout, stderr: String(error) })
    })
  })
}

function spawnLong(id, args) {
  const old = processes.get(id)
  if (old && !old.killed) {
    try { old.kill('SIGTERM') } catch {}
    processes.delete(id)
    return { running: false, stopped: true }
  }
  const child = spawn(ASTRA_PYTHON, ['-m', 'astra_pc', ...args], {
    cwd: ASTRA_ROOT,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  processes.set(id, child)
  const forward = (kind, chunk) => emit('astra:process-line', { id, kind, text: chunk.toString() })
  child.stdout.on('data', chunk => forward('stdout', chunk))
  child.stderr.on('data', chunk => forward('stderr', chunk))
  child.on('close', code => {
    processes.delete(id)
    emit('astra:process-exit', { id, code })
  })
  return { running: true, pid: child.pid }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1420,
    height: 900,
    minWidth: 1000,
    minHeight: 680,
    backgroundColor: '#0d0f13',
    title: 'Astra',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  mainWindow.loadFile(path.join(__dirname, 'index.html'))
  mainWindow.on('closed', () => { mainWindow = null })
}

ipcMain.handle('astra:status', async () => {
  const result = await runAstra(['desktop-status'], { stream: false, timeout: 5000 })
  try { return JSON.parse(result.stdout.trim()) }
  catch { return { ok: false, error: result.stderr || result.stdout || 'status unavailable' } }
})

ipcMain.handle('astra:ask', async (_event, text) => {
  const result = await runAstra(['ask', String(text)], { stream: false, timeout: 90000 })
  return { ok: result.code === 0, text: result.stdout.trim(), error: result.stderr.trim() }
})

ipcMain.handle('astra:run', async (_event, args) => {
  return await runAstra(Array.isArray(args) ? args.map(String) : [], { stream: true })
})

ipcMain.handle('astra:long-toggle', (_event, id, args) => {
  return spawnLong(String(id), Array.isArray(args) ? args.map(String) : [])
})

ipcMain.handle('astra:stop', (_event, id) => {
  const child = processes.get(String(id))
  if (!child) return false
  try { child.kill('SIGTERM'); return true } catch { return false }
})

ipcMain.handle('astra:choose-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, { properties: ['openDirectory', 'createDirectory'] })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('astra:open-external', async (_event, url) => {
  await shell.openExternal(String(url))
  return true
})

app.whenReady().then(createWindow)
app.on('window-all-closed', () => {
  for (const child of processes.values()) {
    try { child.kill('SIGTERM') } catch {}
  }
  if (process.platform !== 'darwin') app.quit()
})
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})
