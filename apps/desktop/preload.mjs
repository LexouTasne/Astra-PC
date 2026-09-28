import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('astra', {
  status: () => ipcRenderer.invoke('astra:status'),
  ask: text => ipcRenderer.invoke('astra:ask', text),
  run: args => ipcRenderer.invoke('astra:run', args),
  longToggle: (id, args) => ipcRenderer.invoke('astra:long-toggle', id, args),
  stop: id => ipcRenderer.invoke('astra:stop', id),
  chooseFolder: () => ipcRenderer.invoke('astra:choose-folder'),
  openExternal: url => ipcRenderer.invoke('astra:open-external', url),
  onProcessLine: callback => ipcRenderer.on('astra:process-line', (_e, payload) => callback(payload)),
  onProcessExit: callback => ipcRenderer.on('astra:process-exit', (_e, payload) => callback(payload)),
})
