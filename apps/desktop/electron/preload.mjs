import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('astra', {
  status: () => ipcRenderer.invoke('astra:status'),
  ask: payload => ipcRenderer.invoke('astra:ask', payload),
  chooseImage: () => ipcRenderer.invoke('astra:choose-image'),
  dictate: () => ipcRenderer.invoke('astra:dictate'),
  run: (command, args = []) => ipcRenderer.invoke('astra:run', { command, args }),
  stop: id => ipcRenderer.invoke('astra:stop', id),
  update: () => ipcRenderer.invoke('astra:update'),
  chooseFolder: () => ipcRenderer.invoke('astra:choose-folder'),
  window: action => ipcRenderer.invoke('astra:window', action),
  onProcess: callback => {
    const handler = (_event, payload) => callback(payload)
    ipcRenderer.on('astra:process', handler)
    return () => ipcRenderer.removeListener('astra:process', handler)
  }
})
