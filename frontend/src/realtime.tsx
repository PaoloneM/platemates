import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { io, type Socket } from 'socket.io-client'
import { useAuth } from './auth/context'

// One Socket.IO connection per signed-in session, at /websocket/ on the app's own origin (the
// session cookie is the login). Events are notices: one missed while disconnected is lost, so
// a screen reloads its state from the API on every (re)connection (`useOnConnect`).
type RealtimeState = { socket: Socket | null; connected: boolean }

const RealtimeContext = createContext<RealtimeState>({ socket: null, connected: false })

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth()
  const [state, setState] = useState<RealtimeState>({ socket: null, connected: false })
  // The server puts the connection in the rooms of the user's teams when it connects: a new
  // connection when they change (an invitation accepted, a team left).
  const teams = me?.authenticated ? me.teams.map((t) => t.id).sort().join(',') : ''

  useEffect(() => {
    if (!teams) return
    // Socket.IO reconnects by itself, waiting longer each time (up to 5 s here).
    const socket = io({ path: '/websocket/', reconnectionDelayMax: 5000 })
    const update = () => setState({ socket, connected: socket.connected })
    socket.on('connect', update)
    socket.on('disconnect', update)
    update()
    return () => {
      socket.off('connect', update)
      socket.off('disconnect', update)
      socket.disconnect()
    }
  }, [teams])

  return <RealtimeContext.Provider value={state}>{children}</RealtimeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useRealtimeConnected() {
  return useContext(RealtimeContext).connected
}

/** Call `handler` for every `event` the server sends to the user's teams. */
// eslint-disable-next-line react-refresh/only-export-components
export function useRealtimeEvent<T>(event: string, handler: (data: T) => void) {
  const { socket } = useContext(RealtimeContext)
  const latest = useRef(handler)
  useEffect(() => {
    latest.current = handler
  })
  useEffect(() => {
    if (!socket) return
    const listener = (data: T) => latest.current(data)
    socket.on(event, listener)
    return () => {
      socket.off(event, listener)
    }
  }, [socket, event])
}

/** Call `handler` whenever the connection is (re)established: time to reload what may have
 * changed while it was down. */
// eslint-disable-next-line react-refresh/only-export-components
export function useOnConnect(handler: () => void) {
  const { socket } = useContext(RealtimeContext)
  const latest = useRef(handler)
  useEffect(() => {
    latest.current = handler
  })
  useEffect(() => {
    if (!socket) return
    const listener = () => latest.current()
    socket.on('connect', listener)
    return () => {
      socket.off('connect', listener)
    }
  }, [socket])
}
