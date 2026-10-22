// Explicit acceptance command, not part of offline unit tests. No real model/key.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { stripVTControlCharacters } from 'node:util';

const runtime = path.resolve(process.argv[2] ?? 'node_modules/openclaw');
const toolSearch = process.argv.includes('--tool-search');
const unlimited = process.argv.includes('--unlimited');
// Tool Search exposes both the dispatcher and target to native tool hooks.
const expectedEffects = unlimited ? (toolSearch ? 1 : 5) : toolSearch ? 1 : 2;
const version = JSON.parse(fs.readFileSync(path.join(runtime, 'package.json'), 'utf8')).version;
assert.equal(version, '2026.10.2', 'Use the pinned acceptance runtime; revalidate other versions separately');
const plugin = fileURLToPath(new URL('../agents/tool-budget', import.meta.url));
// Windows hosted runners expose an 8.3 TEMP path. The native transcript store
// compares canonical ownership paths, so pass it the resolved directory.
const root = fs.realpathSync.native(fs.mkdtempSync(path.join(os.tmpdir(), 'easel-budget-')));
const fixture = path.join(root, 'fixture');
const logPath = path.join(root, 'gateway.log');
const effectsPath = path.join(root, 'effects.jsonl');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate, timeout = 30000) {
  const end = performance.now() + timeout;
  while (!await predicate()) {
    if (performance.now() >= end) throw new Error('Native acceptance condition timed out');
    await sleep(50);
  }
}
const readLog = () => stripVTControlCharacters(fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : '');
const events = () => readLog().split('\n')
  .filter(line => line.includes('[plugins] {"event":"easel_budget_'))
  .map(line => JSON.parse(line.slice(line.indexOf('{"event"'))));
const stopped = reason => events().some(event => event.event === 'easel_budget_stop' &&
  event.stopReason === reason && event.stopStatus === 'confirmed');
const requests = { calls: 0, survivor: 0, thinking: 0 };
let thinkingClosed = false;
let fixtureError;
const server = http.createServer(async (req, res) => {
  try {
    let raw = '';
    for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw);
    const label = Object.keys(requests).find(name => JSON.stringify(body.messages).includes(`EASEL_FIXTURE_${name}`));
    assert.ok(label, 'Unexpected model request');
    requests[label]++;
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const chunk = (delta, finish_reason = null) => res.write('data: ' + JSON.stringify({
      id: `fixture-${label}-${requests[label]}`, object: 'chat.completion.chunk', created: 1,
      model: 'fixture', choices: [{ index: 0, delta, finish_reason }],
    }) + '\n\n');
    chunk({ role: 'assistant' });
    if (label === 'thinking') {
      res.once('close', () => { thinkingClosed = true; });
      if (unlimited) {
        await sleep(9000);
        assert.equal(res.destroyed, false, 'Unconfigured budget cancelled the model');
        chunk({ content: 'Completed beyond the opt-in deadline.' });
        chunk({}, 'stop');
        res.end('data: [DONE]\n\n');
      }
      return; // Hold the response open until the native deadline cancels it.
    }
    if (label === 'survivor') {
      await until(() => unlimited ? requests.calls >= 2 : stopped('call_budget_exhausted'));
      assert.equal(res.destroyed, false, 'Stopping another run cancelled the survivor');
      chunk({ content: 'Survivor completed after the other run stopped.' });
      chunk({}, 'stop');
    } else if (unlimited && requests.calls > 1) {
      chunk({ content: 'All unbudgeted tools completed.' });
      chunk({}, 'stop');
    } else {
      await until(() => requests.survivor > 0);
      chunk({ tool_calls: Array.from({ length: toolSearch ? 1 : 5 }, (_, index) => ({ index,
        id: `fixture-${requests.calls}-${index}`, type: 'function',
        function: { name: toolSearch ? 'tool_call' : 'budget_fixture',
          arguments: toolSearch ? JSON.stringify({ id: 'budget_fixture', args: {} }) : '{}' },
      })) });
      chunk({}, 'tool_calls');
    }
    res.end('data: [DONE]\n\n');
  } catch (error) { fixtureError = error; res.destroy(); }
});
let child, output;
try {
  fs.mkdirSync(fixture);
  fs.writeFileSync(path.join(fixture, 'package.json'), JSON.stringify({ name: 'easel-budget-fixture',
    version: '0.0.0', type: 'module', openclaw: { extensions: ['./index.mjs'] } }));
  fs.writeFileSync(path.join(fixture, 'openclaw.plugin.json'), JSON.stringify({ id: 'easel-budget-fixture',
    configSchema: { type: 'object', additionalProperties: false }, contracts: { tools: ['budget_fixture'] } }));
  fs.writeFileSync(path.join(fixture, 'index.mjs'), `import fs from 'node:fs';
export default {id:'easel-budget-fixture',register(api){api.registerTool(ctx=>({
  name:'budget_fixture',label:'Budget fixture',description:'Harmless local counter',
  parameters:{type:'object',properties:{},additionalProperties:false},
  async execute(){fs.appendFileSync(${JSON.stringify(effectsPath)},JSON.stringify({session:ctx.sessionKey})+'\\n');
    return {content:[{type:'text',text:'fixture success'}]};}
}),{name:'budget_fixture'});}};`);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const portProbe = http.createServer();
  await new Promise(resolve => portProbe.listen(0, '127.0.0.1', resolve));
  const port = portProbe.address().port;
  await new Promise(resolve => portProbe.close(resolve));
  const config = { logging: { consoleStyle: 'pretty', consoleLevel: 'info', file: path.join(root, 'structured.log') },
  gateway: { mode: 'local', port, bind: 'loopback',
    auth: { mode: 'token', token: 'easel-local-fixture-token' }, controlUi: { enabled: false } },
  agents: { defaults: { model: { primary: 'fixture/fixture' }, workspace: path.join(root, 'workspace'),
    skipBootstrap: true, timeoutSeconds: 40, maxConcurrent: 4 } },
  models: { mode: 'replace', providers: { fixture: { baseUrl: `http://127.0.0.1:${server.address().port}/v1`,
    apiKey: 'fixture-only', api: 'openai-completions', models: [{ id: 'fixture', name: 'Fixture', reasoning: false,
      input: ['text'], contextWindow: 64000, maxTokens: 1024,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] } } },
  tools: { allow: ['budget_fixture'], toolSearch },
  plugins: { allow: ['easel-tool-budget', 'easel-budget-fixture'], load: { paths: [plugin, fixture] }, entries: {
    'easel-tool-budget': { enabled: true, hooks: { allowConversationAccess: true },
      config: unlimited ? {} : { maxCalls: 2, timeoutMs: 8000 } },
    'easel-budget-fixture': { enabled: true }, 'memory-core': { enabled: false },
  } }, cron: { enabled: false }, update: { checkOnStart: false } };
  fs.writeFileSync(path.join(root, 'openclaw.json'), JSON.stringify(config));
  // Isolate both the CLI SDK and child gateway; never read the operator's profile.
  process.env.OPENCLAW_STATE_DIR = root;
  process.env.OPENCLAW_CONFIG_PATH = path.join(root, 'openclaw.json');
  process.env.OPENCLAW_NO_RESPAWN = '1';
  process.env.FORCE_COLOR = '0';
  output = fs.openSync(logPath, 'w');
  child = spawn(process.execPath, [path.join(runtime, 'openclaw.mjs'), 'gateway', 'run'],
    { env: process.env, stdio: ['ignore', output, output], windowsHide: true });
  let startupError;
  child.on('error', error => { startupError = error; });
  await until(async () => {
    if (startupError) throw startupError;
    if (child.exitCode !== null) throw new Error(`Gateway exited: ${child.exitCode}`);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/readyz`, { signal: AbortSignal.timeout(1000) });
      return response.ok;
    } catch { return false; }
  }, 120000);
  const { callGatewayFromCli } = await import(pathToFileURL(path.join(runtime, 'dist/plugin-sdk/gateway-runtime.js')));
  if (unlimited) {
    await assert.rejects(() => callGatewayFromCli('easel.toolBudget.capability', { timeout: '10000', json: true },
      { nonce: 'ab'.repeat(16) }, { progress: false }));
    const send = label => callGatewayFromCli('chat.send', { timeout: '20000', json: true }, {
      sessionKey: `agent:main:budget-${label}`, message: `EASEL_FIXTURE_${label}`,
      idempotencyKey: `fixture-${label}-${Date.now()}`,
    }, { progress: false });
    await Promise.all([send('calls'), send('survivor')]);
    await until(() => requests.calls >= 2);
    assert.ifError(fixtureError);
    const effects = fs.readFileSync(effectsPath, 'utf8').trim().split('\n').map(line => JSON.parse(line));
    assert.equal(effects.length, expectedEffects);
    assert.ok(effects.every(effect => effect.session === 'agent:main:budget-calls'));
    await send('thinking');
    await until(() => thinkingClosed, 15000);
    assert.ifError(fixtureError);
    assert.equal(requests.thinking, 1);
    assert.deepEqual(events(), [], 'Unconfigured plugin emitted budget lifecycle events');
    console.log(JSON.stringify({ runtime: version, toolSearch, unlimited: true, complete: true,
      toolEffects: effects.length, noBudgetDeadline: true, noBudgetHooks: true, modelRequests: requests }));
  } else {
    const capability = await callGatewayFromCli('easel.toolBudget.capability', { timeout: '10000', json: true },
      { nonce: 'ab'.repeat(16) }, { progress: false });
    assert.equal(capability.nonce, 'ab'.repeat(16));
    assert.equal(capability.runtime, version);
    assert.equal(capability.maxCalls, 2);
    assert.equal(capability.timeoutMs, 8000);
    assert.equal(capability.requestAdmissionToken, false);
    assert.deepEqual(requests, { calls: 0, survivor: 0, thinking: 0 }, 'Capability probe must not execute an agent');
    await assert.rejects(() => callGatewayFromCli('easel.toolBudget.send', { timeout: '10000', json: true }, {
      instanceId: 'previous-gateway', maxCalls: 2, timeoutMs: 8000,
      sessionKey: 'agent:main:rejected', message: 'must never reach the model', idempotencyKey: 'rejected-proof',
    }, { progress: false }));
    assert.deepEqual(requests, { calls: 0, survivor: 0, thinking: 0 });
    const send = label => callGatewayFromCli('easel.toolBudget.send', { timeout: '20000', json: true }, {
      instanceId: capability.instanceId, maxCalls: capability.maxCalls, timeoutMs: capability.timeoutMs,
      sessionKey: `agent:main:budget-${label}`, message: `EASEL_FIXTURE_${label}`,
      idempotencyKey: `fixture-${label}-${Date.now()}`,
    }, { progress: false });
    const accepted = await Promise.all([send('calls'), send('survivor')]);
    assert.ok(accepted.every(result => typeof result?.runId === 'string' && result.runId.length > 0),
      'Guarded admission must return the core run identity for outcome inspection');
    await until(() => stopped('call_budget_exhausted') && events().some(event =>
      event.event === 'easel_budget_end' && event.stopReason === 'run_finished'));
    assert.ifError(fixtureError);
    const effects = fs.readFileSync(effectsPath, 'utf8').trim().split('\n').map(line => JSON.parse(line));
    assert.equal(effects.length, expectedEffects, 'Native effects must match admitted dispatch depth');
    assert.ok(effects.every(effect => effect.session === 'agent:main:budget-calls'));
    assert.equal(requests.survivor, 1);
    const countAfterStop = requests.calls;
    await send('thinking');
    await until(() => stopped('time_budget_exhausted') && thinkingClosed);
    assert.ifError(fixtureError);
    await sleep(1000);
    assert.equal(requests.calls, countAfterStop, 'Cancelled model continued requesting tools');
    assert.equal(requests.thinking, 1, 'Deadline cancellation retried the model');
    assert.equal(fs.readFileSync(effectsPath, 'utf8').trim().split('\n').length, expectedEffects);
    assert.equal(events().filter(event => event.event === 'easel_budget_stop').length, 2);
    console.log(JSON.stringify({ runtime: version, toolSearch, complete: true, toolEffects: effects.length,
      callStopConfirmed: true, deadlineStopConfirmed: true, concurrentRunCompleted: true, modelRequests: requests }));
  }
} catch (error) {
  console.error(`Native budget acceptance failed; isolated diagnostics: ${root}`);
  // Startup phase names are useful on slow CI hosts and contain no config/input.
  console.error(JSON.stringify({ startupPhases: readLog().split('\n')
    .map(line => line.match(/startup phase: ([a-zA-Z0-9_.-]+)( starting)?/)?.[0])
    .filter(Boolean).slice(-12), gatewayReady: readLog().includes('[gateway] ready'),
    requests, budgetEvents: events(), fixtureFailed: Boolean(fixtureError),
    // Only extract errors from this fixture's isolated gateway, not raw logs.
    gatewayErrors: readLog().split('\n').map(line => line.match(/error="(.*?)" errorName=/)?.[1])
      .filter(Boolean).slice(-4).map(message => message.slice(0, 800)) }));
  throw error;
} finally {
  if (child && child.exitCode === null) {
    child.kill();
    await Promise.race([new Promise(resolve => child.once('exit', resolve)), sleep(3000)]);
    if (child.exitCode === null) child.kill('SIGKILL');
  }
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
  if (output !== undefined) fs.closeSync(output);
  // Keep isolated diagnostics for audit; never print raw model input/transcripts.
}
