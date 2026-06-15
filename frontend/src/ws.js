export function runJob(payload, { onLog, onDone, onError, onConflict }) {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const ws = new WebSocket(`${protocol}//${location.host}/ws/run`)

  ws.onopen = () => ws.send(JSON.stringify(payload))

  ws.onmessage = ({ data }) => {
    const msg = JSON.parse(data)
    if      (msg.type === 'log')        onLog(msg.text)
    else if (msg.type === 'done')     { onDone();               ws.close() }
    else if (msg.type === 'error')    { onError(msg.message);   ws.close() }
    else if (msg.type === 'conflict') { onConflict(msg.blocking); ws.close() }
  }

  ws.onerror = () => onError('WebSocket connection failed')

  return { cancel: () => ws.close() }
}
