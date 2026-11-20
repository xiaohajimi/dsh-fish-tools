// dsh-update-guard — remember the running DSH version, warn loudly when it changes,
// and remind the agent to refuse casual upgrades.
//
// Facts this plugin is built on (verified against a DSH Desktop install):
//   * DSH Desktop has no auto-updater component (checked app.asar/package.json, 196 deps,
//     no electron-updater / autoUpdater). Updating happens only when the user clicks
//     "check for updates" in Settings.
//   * So this plugin cannot block an installer. It does three things instead:
//     1) lock the current version into a state file
//     2) write an alert document when the version differs from the lock
//     3) inject a small system-prompt section telling the agent to stop and ask first
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export const name = 'update-guard'
export const inject = ['systemPrompt']

const BASE = process.env.UPDATE_GUARD_HOME || path.join(os.homedir(), '.dsh-update-guard')
const LOCK = path.join(BASE, 'version-lock.json')
const ALERT = path.join(BASE, 'version-changed.md')

// Where the running DSH package manifest may live. First existing one wins.
const CANDIDATES = [
  process.env.DSH_INSTALL_DIR,
  process.env.DSH_HOME ? path.join(process.env.DSH_HOME, 'resources', 'app.asar') : null,
].filter(Boolean)

function readJson(p) {
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'))
  } catch {
    return null
  }
}

function writeText(p, text) {
  fs.mkdirSync(path.dirname(p), { recursive: true })
  fs.writeFileSync(p, text, 'utf8')
}

function currentVersion() {
  for (const dir of CANDIDATES) {
    const j = readJson(path.join(dir, 'package.json'))
    if (j && j.version) return { name: j.name, version: j.version, dir }
  }
  return null
}

function readLock() {
  const j = readJson(LOCK)
  return j && j.version ? j : null
}

function saveLock(cur) {
  writeText(LOCK, JSON.stringify({
    version: cur.version,
    name: cur.name,
    dir: cur.dir,
    lockedAt: new Date().toISOString(),
  }, null, 2))
}

function writeAlert(cur, lock) {
  writeText(ALERT, [
    '# DSH version changed',
    '',
    '- detected at: ' + new Date().toISOString(),
    '- locked version: `' + lock.version + '`',
    '- running version: `' + cur.version + '`',
    '',
    '## What to do',
    '',
    '1. Confirm the upgrade was intentional.',
    '2. Back up the profile directory before rolling back:',
    '   - `%USERPROFILE%\\.dsh\\profiles\\desktop`',
    '3. If the new version is broken, restore the previous installation or package version.',
    '4. When the new version is accepted, delete the lock file and restart DSH:',
    '   - `' + LOCK + '`',
    '',
  ].join('\n'))
}

function guard() {
  const cur = currentVersion()
  if (!cur) return { ok: false, reason: 'cannot read the running DSH version' }
  const lock = readLock()
  if (!lock) {
    saveLock(cur)
    return { ok: true, action: 'locked', version: cur.version, lockPath: LOCK }
  }
  if (lock.version === cur.version) {
    return { ok: true, action: 'unchanged', version: cur.version }
  }
  writeAlert(cur, lock)
  return { ok: false, action: 'changed', from: lock.version, to: cur.version, alertPath: ALERT }
}

export function apply(ctx, config = {}) {
  let result
  try {
    result = guard()
  } catch (e) {
    result = { ok: false, reason: String(e && e.message ? e.message : e) }
  }

  if (result.action === 'locked') {
    ctx.logger?.info?.('update-guard: locked DSH ' + result.version)
  } else if (result.action === 'changed') {
    ctx.logger?.error?.(
      'update-guard: DSH changed from ' + result.from + ' to ' + result.to +
      ', alert written to ' + result.alertPath,
    )
  } else {
    ctx.logger?.info?.('update-guard: version ' + (result.version || result.reason))
  }

  const statusLine = result.action === 'changed'
    ? 'WARNING: DSH version changed from ' + result.from + ' to ' + result.to + '. Verify before continuing.'
    : 'DSH version locked at ' + (result.version || 'unknown') + '.'

  const text = [
    '[DSH update guard]',
    statusLine,
    'When the user proposes upgrading or reinstalling DSH:',
    '  1. mention that upgrades have broken this environment before',
    '  2. ask for a profile backup first (%USERPROFILE%\\.dsh\\profiles\\desktop)',
    '  3. ask which previously working version/installer is available for rollback',
    '  4. say plainly that you recommend not upgrading during active work',
    'State files: ' + LOCK + ' | ' + ALERT,
  ].join('\n')

  const order = Number.isFinite(config.order) ? config.order : 9100
  const sectionName = String(config.sectionName || 'user:update-guard')

  ctx.effect(() => {
    const dispose = ctx.systemPrompt.section({ name: sectionName, order, text })
    return () => {
      if (typeof dispose === 'function') dispose()
    }
  }, 'update-guard: system prompt section')
}
