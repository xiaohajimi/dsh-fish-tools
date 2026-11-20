// dsh-labor — dispatch mechanical work to local models through tool calls.
//
// The point: starting a local llama-server, posting a prompt and copying the answer
// back into a file costs more attention than the work itself. This plugin collapses
// those three steps into one tool call.
//
// Layout: register `labor_status`, `labor_start`, `labor_ask`, `labor_write`.
// Configuration comes from a JSON file (see README), never from hardcoded paths.
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export const name = 'labor'
export const inject = ['tools']

const BASE = process.env.LABOR_HOME || path.join(os.homedir(), '.dsh-labor')
const CONFIG_FILE = process.env.LABOR_CONFIG || path.join(BASE, 'labor.json')
const LOG_DIR = path.join(BASE, 'logs')

// Server binary: config overrides this, then PATH.
let SERVER = process.env.LLAMA_SERVER || 'llama-server'

// Allowed root for labor_write: paths outside it are refused.
let ALLOWED_ROOT = process.env.LABOR_WRITE_ROOT || os.homedir()

// Neutral placeholders; the config file replaces them entirely.
const PRESETS = {
  small: { label: 'small model', port: 8081, model: '', mmproj: '', ctx: 8192 },
  large: { label: 'large model', port: 8082, model: '', ctx: 8192 },
  reasoner: { label: 'reasoner', port: 8083, model: '', ctx: 8192 },
}

const SYSTEM = 'You are a local execution model. Output only the result: a complete code block for code, no explanation, no pleasantries.'

function loadConfig() {
  try {
    const cfg = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'))
    if (cfg.server) SERVER = String(cfg.server)
    if (cfg.writeRoot) ALLOWED_ROOT = String(cfg.writeRoot)
    for (const [key, val] of Object.entries(cfg.presets || {})) {
      if (!val) continue
      PRESETS[key] = Object.assign(PRESETS[key] || {}, val)
    }
    return { loaded: true, file: CONFIG_FILE }
  } catch (e) {
    return { loaded: false, file: CONFIG_FILE, reason: String(e && e.code ? e.code : e) }
  }
}

function preset(who) {
  const p = PRESETS[String(who || '').toLowerCase()]
  if (!p) throw new Error('unknown preset: ' + who + ' (available: ' + Object.keys(PRESETS).join(', ') + ')')
  if (!p.model) throw new Error('preset ' + who + ' has no model path; fill it in ' + CONFIG_FILE)
  return p
}

async function health(p, ms = 1500) {
  try {
    const r = await fetch('http://127.0.0.1:' + p.port + '/health', { signal: AbortSignal.timeout(ms) })
    if (!r.ok) return { up: false, status: r.status }
    const j = await r.json().catch(() => ({}))
    return { up: true, status: j.status || 'ok' }
  } catch (e) {
    return { up: false, error: String(e && e.message ? e.message : e) }
  }
}

async function chat(p, prompt, maxTokens, timeoutSec) {
  const body = {
    messages: [
      { role: 'system', content: SYSTEM },
      { role: 'user', content: prompt },
    ],
    max_tokens: maxTokens,
    temperature: 0.3,
    stream: false,
  }
  const r = await fetch('http://127.0.0.1:' + p.port + '/v1/chat/completions', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutSec * 1000),
  })
  if (!r.ok) throw new Error('HTTP ' + r.status + ': ' + (await r.text()).slice(0, 300))
  const j = await r.json()
  const m = (j.choices && j.choices[0] && j.choices[0].message) || {}
  const text = String(m.content || '').trim()
  const thinking = String(m.reasoning_content || '').trim()
  return { text: text || thinking, usedThinking: !text && !!thinking }
}

function extractCode(text) {
  const m = [...String(text).matchAll(/```(?:[a-zA-Z0-9_+-]*)?\s*\n([\s\S]*?)```/g)]
  if (m.length) return m.sort((a, b) => b[1].length - a[1].length)[0][1].trim()
  return String(text).trim()
}

function startServer(p) {
  const args = [
    '-m', p.model,
    '--host', '127.0.0.1',
    '--port', String(p.port),
    '--ctx-size', String(p.ctx || 8192),
    '-ngl', '99',
    '--jinja',
  ]
  if (p.mmproj && fs.existsSync(p.mmproj)) args.push('--mmproj', p.mmproj)
  fs.mkdirSync(LOG_DIR, { recursive: true })
  const log = path.join(LOG_DIR, 'labor-' + p.port + '.log')
  const out = fs.openSync(log, 'a')
  const child = spawn(SERVER, args, { detached: true, stdio: ['ignore', out, out], windowsHide: true })
  child.unref()
  return { pid: child.pid, log, args }
}

const textOut = (v) => [{ type: 'text', text: typeof v === 'string' ? v : JSON.stringify(v, null, 2) }]

export function apply(ctx) {
  const cfgState = loadConfig()

  ctx.effect(() => ctx.tools.register({
    name: 'labor_status',
    description: 'List the configured local models, whether each is up, their ports, and whether the config file was read. Call this before dispatching work.',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    output: { schema: {}, render: (_a, v) => textOut(v) },
    async execute() {
      const rows = []
      for (const [key, p] of Object.entries(PRESETS)) {
        const h = p.model ? await health(p) : { up: false, status: 'no model configured' }
        rows.push(key.padEnd(10) + String(p.label).padEnd(18) + ':' + p.port + '  ' + (h.up ? 'UP' : 'down'))
      }
      const cfgLine = cfgState.loaded
        ? 'config: ' + cfgState.file + ' (loaded)'
        : 'config: ' + cfgState.file + ' (missing: ' + cfgState.reason + ', using built-in placeholders)'
      return rows.join('\n') + '\n' + cfgLine
    },
  }), 'labor: status')

  ctx.effect(() => ctx.tools.register({
    name: 'labor_start',
    description: 'Start one configured local model server in the background (llama-server + a GGUF). Takes 30-90s to become ready.',
    parameters: {
      type: 'object',
      properties: { who: { type: 'string', description: 'preset key from the config file' } },
      required: ['who'],
      additionalProperties: false,
    },
    output: { schema: {}, render: (_a, v) => textOut(v) },
    async execute(args = {}) {
      const p = preset(args.who)
      const h = await health(p)
      if (h.up) return p.label + ' is already up on :' + p.port
      const r = startServer(p)
      await new Promise((res) => setTimeout(res, 6000))
      const h2 = await health(p, 2000)
      return [
        'started ' + p.label + ' (pid ' + r.pid + ') on :' + p.port,
        'log: ' + r.log,
        h2.up ? 'status: ready' : 'status: still loading (check labor_status in 30-60s)',
      ].join('\n')
    },
  }), 'labor: start')

  ctx.effect(() => ctx.tools.register({
    name: 'labor_ask',
    description: 'Send a task to a local model and return its answer. Good for boilerplate, batch edits, format conversion, medium-difficulty explanations.',
    parameters: {
      type: 'object',
      properties: {
        who: { type: 'string', description: 'preset key from the config file' },
        prompt: { type: 'string', description: 'the full task; the model cannot see this conversation' },
        maxTokens: { type: 'number', description: 'max generated tokens, default 1200' },
        timeoutSec: { type: 'number', description: 'request timeout in seconds, default 180' },
      },
      required: ['who', 'prompt'],
      additionalProperties: false,
    },
    output: { schema: {}, render: (_a, v) => textOut(v) },
    async execute(args = {}) {
      const p = preset(args.who)
      const h = await health(p)
      if (!h.up) return p.label + ' is not running. Call labor_start {"who":"' + args.who + '"} first.'
      const t0 = Date.now()
      const r = await chat(p, String(args.prompt || ''), Number(args.maxTokens) || 1200, Number(args.timeoutSec) || 180)
      const sec = ((Date.now() - t0) / 1000).toFixed(1)
      return '[' + p.label + '] ' + sec + 's' + (r.usedThinking ? ' (empty content, showing reasoning)' : '') + '\n\n' + r.text
    },
  }), 'labor: ask')

  ctx.effect(() => ctx.tools.register({
    name: 'labor_write',
    description: 'Have a local model write code and save it straight to a file, returning the path and a short preview. Verify the result yourself afterwards.',
    parameters: {
      type: 'object',
      properties: {
        who: { type: 'string', description: 'preset key from the config file' },
        prompt: { type: 'string', description: 'what to write, including function names and constraints' },
        path: { type: 'string', description: 'absolute output path inside the allowed write root' },
        maxTokens: { type: 'number', description: 'max generated tokens, default 2000' },
      },
      required: ['who', 'prompt', 'path'],
      additionalProperties: false,
    },
    output: { schema: {}, render: (_a, v) => textOut(v) },
    async execute(args = {}) {
      const p = preset(args.who)
      const target = path.resolve(String(args.path || ''))
      if (!target.startsWith(path.resolve(ALLOWED_ROOT) + path.sep)) {
        return 'refused: path must be inside ' + ALLOWED_ROOT
      }
      const h = await health(p)
      if (!h.up) return p.label + ' is not running. Call labor_start {"who":"' + args.who + '"} first.'
      const t0 = Date.now()
      const r = await chat(p, String(args.prompt || ''), Number(args.maxTokens) || 2000, 240)
      const code = extractCode(r.text)
      fs.mkdirSync(path.dirname(target), { recursive: true })
      fs.writeFileSync(target, code.endsWith('\n') ? code : code + '\n', 'utf8')
      const bytes = fs.statSync(target).size
      const preview = code.split('\n').slice(0, 12).join('\n')
      return [
        '[' + p.label + '] ' + ((Date.now() - t0) / 1000).toFixed(1) + 's',
        'written: ' + target + ' (' + bytes + ' bytes)',
        'first 12 lines:',
        preview,
        '',
        'verify: syntax, function names, edge cases.',
      ].join('\n')
    },
  }), 'labor: write')
}
