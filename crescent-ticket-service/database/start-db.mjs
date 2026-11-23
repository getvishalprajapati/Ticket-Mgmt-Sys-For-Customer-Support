#!/usr/bin/env node
// Crescent Motors - local PGlite PostgreSQL socket server.
//
// Runs an embedded PostgreSQL (PGlite, WebAssembly) with a persistent data
// directory and exposes it over the PostgreSQL wire protocol on localhost only.
//
// Usage (from the database/ directory):
//   node start-db.mjs                                   # app database
//   node start-db.mjs --data-dir ./pgdata/test --port 55433
//
// Options (CLI flag, then environment variable, then default):
//   --data-dir         PGLITE_DATA_DIR         ./pgdata/app (relative to this file)
//                      or "memory://" for a throwaway in-memory database
//   --host             PGLITE_HOST             127.0.0.1 (loopback addresses only)
//   --port             PGLITE_PORT             55432 (0 = pick a free port)
//   --max-connections  PGLITE_MAX_CONNECTIONS  4
//   --exit-on-stdin-close                      shut down cleanly when stdin closes
//                                              (used by the automated test harness)
import { closeSync, mkdirSync, openSync, readFileSync, rmSync, writeSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'

import { PGlite } from '@electric-sql/pglite'
import { PGLiteSocketServer } from '@electric-sql/pglite-socket'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const LOOPBACK_HOSTS = new Set(['127.0.0.1', '::1', 'localhost'])
let heldLockPath = null // released on shutdown and on startup failure

function fail(message) {
  console.error(`[pglite] ERROR: ${message}`)
  process.exit(2)
}

function loadConfig() {
  const { values } = parseArgs({
    options: {
      'data-dir': { type: 'string' },
      host: { type: 'string' },
      port: { type: 'string' },
      'max-connections': { type: 'string' },
      'exit-on-stdin-close': { type: 'boolean', default: false },
    },
    strict: true,
  })

  const rawDataDir = values['data-dir'] ?? process.env.PGLITE_DATA_DIR ?? './pgdata/app'
  const inMemory = rawDataDir === 'memory://'
  const dataDir = inMemory ? rawDataDir : path.resolve(HERE, rawDataDir)

  const host = values.host ?? process.env.PGLITE_HOST ?? '127.0.0.1'
  if (!LOOPBACK_HOSTS.has(host)) {
    fail(`refusing to bind to "${host}". Only localhost addresses are allowed: ${[...LOOPBACK_HOSTS].join(', ')}`)
  }

  const port = Number.parseInt(values.port ?? process.env.PGLITE_PORT ?? '55432', 10)
  if (!Number.isInteger(port) || port < 0 || port > 65535) fail('port must be an integer between 0 and 65535')

  const maxConnections = Number.parseInt(
    values['max-connections'] ?? process.env.PGLITE_MAX_CONNECTIONS ?? '4',
    10,
  )
  if (!Number.isInteger(maxConnections) || maxConnections < 1 || maxConnections > 16) {
    fail('max-connections must be an integer between 1 and 16')
  }

  return { dataDir, inMemory, host, port, maxConnections, exitOnStdinClose: values['exit-on-stdin-close'] }
}

function isProcessAlive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (err) {
    return err.code === 'EPERM'
  }
}

// PGlite must never have two processes writing the same data directory.
function acquireLock(dataDir) {
  const lockPath = `${dataDir}.lock`
  mkdirSync(path.dirname(lockPath), { recursive: true })
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const fd = openSync(lockPath, 'wx')
      writeSync(fd, String(process.pid))
      closeSync(fd)
      heldLockPath = lockPath
      return lockPath
    } catch (err) {
      if (err.code !== 'EEXIST') throw err
      const owner = Number.parseInt(readFileSync(lockPath, 'utf8'), 10)
      if (Number.isInteger(owner) && owner !== process.pid && isProcessAlive(owner)) {
        fail(`data directory ${dataDir} is already in use by process ${owner}`)
      }
      rmSync(lockPath, { force: true }) // stale lock from a crashed process
    }
  }
  fail(`could not acquire lock file ${lockPath}`)
}

async function main() {
  const config = loadConfig()
  const lockPath = config.inMemory ? null : acquireLock(config.dataDir)

  console.log(`[pglite] opening database: ${config.dataDir}`)
  const db = await PGlite.create(config.inMemory ? undefined : config.dataDir)
  const server = new PGLiteSocketServer({
    db,
    host: config.host,
    port: config.port,
    maxConnections: config.maxConnections,
  })

  let shuttingDown = false
  const shutdown = async (reason) => {
    if (shuttingDown) return
    shuttingDown = true
    console.log(`[pglite] shutting down (${reason})`)
    let exitCode = 0
    try {
      await server.stop()
    } catch (err) {
      exitCode = 1
      console.error('[pglite] error while stopping socket server:', err)
    }
    try {
      await db.close() // flushes the data directory to disk
    } catch (err) {
      exitCode = 1
      console.error('[pglite] error while closing database:', err)
    }
    if (lockPath) rmSync(lockPath, { force: true })
    console.log('[pglite] stopped')
    process.exit(exitCode)
  }

  for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(signal, () => shutdown(signal))
  }
  if (config.exitOnStdinClose) {
    process.stdin.on('end', () => shutdown('stdin closed'))
    process.stdin.on('error', () => shutdown('stdin error'))
    process.stdin.resume()
  }
  server.addEventListener('error', (event) => {
    console.error('[pglite] socket server error:', event.detail?.message ?? event.detail)
  })

  await server.start()
  const [host, port] = server.getServerConn().split(/:(?=\d+$)/)
  const version = (await db.query('select version() as v')).rows[0].v
  console.log(`[pglite] ${version}`)
  console.log(`[pglite] max connections: ${config.maxConnections}`)
  // The test harness waits for this exact line.
  console.log(`[pglite] READY host=${host} port=${port}`)
}

main().catch((err) => {
  console.error(`[pglite] failed to start: ${err?.message ?? err}`)
  if (heldLockPath) rmSync(heldLockPath, { force: true })
  process.exit(1)
})
