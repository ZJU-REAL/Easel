# Native tool budgets (opt in)

This plugin adds a per-run admission limit to the OpenClaw embedded agent used by
Easel. The limit is reserved synchronously **before** a tool executes. Failed
tools and later policy vetoes consume their reservation. A monotonic deadline
also runs while the model is thinking. Retries with the same run identity cannot
reset either limit.

The unit of admission is a native `before_tool_call` invocation. Tool Search
dispatchers and their target tools each consume a reservation; a budget of two
can execute one target through Tool Search or two directly exposed tools. A
parallel dispatcher burst can exhaust capacity before its targets begin. Limits
are conservative and are not a count of external API requests.

The plugin is optional; installing Easel does not enable it or alter existing
OpenClaw settings. **By default, Easel adds no tool-call count or total runtime
limit.** Loading this plugin with no `config` or an empty `{}` also registers no
budget hooks, deadline timers, capability method, or guarded submission method.
Only explicitly configuring both limits activates enforcement. Existing native
gateway timeouts and unrelated safety policies remain unchanged.
It does not cover Codex or ACP backends, CLI child processes,
or external side effects performed inside one admitted tool.

## Configuration

The native integration is tested against **OpenClaw 2026.10.2, Node 24.19**.
Use the same OpenClaw version for the CLI and gateway. Other versions and
alternative harnesses need their own acceptance run before enabling protection.

Merge the following entries into the existing **Easel profile** configuration
(normally `~/.openclaw-easel/openclaw.json`). Replace the path with the absolute
path to this directory. Preserve existing plugin allow entries, paths, and
configuration; do not replace the entire config with this fragment.

```json
{
  "plugins": {
    "allow": ["easel-tool-budget"],
    "load": { "paths": ["/absolute/path/to/Easel/agents/tool-budget"] },
    "entries": {
      "easel-tool-budget": {
        "enabled": true,
        "hooks": { "allowConversationAccess": true },
        "config": { "maxCalls": 40, "timeoutMs": 120000 }
      }
    }
  }
}
```

The `40` calls and `120000` ms above are an **opt-in example, not defaults**.
Omit `config` or use `"config": {}` to leave both limits disabled. To enable
budget enforcement, provide both `maxCalls` and `timeoutMs`; partial or invalid
configuration is rejected rather than silently disabling protection.
`maxCalls` must be an integer from 0 to 10000; `timeoutMs` must be an integer
from 1 to 3600000. With enforcement enabled, `maxCalls: 0` denies all tools; it
does not mean unlimited. Missing/invalid
run or call identities deny execution. Lifecycle hooks need OpenClaw's
`allowConversationAccess` setting; this plugin does not read or log messages,
tool parameters, or results. Without that setting, OpenClaw blocks those hooks
and every attempted tool is denied because its run was never admitted.

After saving, restart the Easel gateway and inspect the **same profile**:

```sh
openclaw --profile easel plugins inspect easel-tool-budget --runtime --json
```

Verify status `loaded`, no hook-blocking diagnostics, and all four typed hooks:
`before_agent_run`, `before_tool_call`, `after_tool_call`, and `agent_end`.
An enabled entry alone does not prove runtime enforcement. Keep the gateway's
own run timeout enabled as a separate bound.

## Stop semantics and limits

Admission closes immediately when a limit is exceeded. A separate, bounded
`chat.abort` request targets the exact agent, session, and run, with
`preserveSideRuns: true`. It never retries against a whole session. Only a reply
confirming that exact run is reported as `stopStatus: confirmed`; transport
errors, identity mismatches, and already-ended runs are `unconfirmed`.
An unconfirmed stop still denies further tools, but cannot guarantee that the
model has stopped. The logs distinguish these outcomes rather than reporting a
successful cancellation. An already-running tool may finish after the deadline;
the plugin cannot roll back its effects or forcibly terminate arbitrary tools.

The plugin logs aggregate admitted/pending/succeeded/failed/rejected counts and
the stop reason. It keeps at most 10000 run records per gateway process and
refuses new runs once full. Completed call identities are discarded after their
results settle. Retained run records prevent delayed callbacks from reopening
completed runs. Restart the gateway after draining active work to clear the
registry. Budgets are not durable across a gateway restart or plugin reload;
the plugin is not a crash-recovery or exactly-once mechanism.

Do not hot-reload the plugin during active work. Resumed/recovered native runs
may have identities that cannot be cancelled through the original chat request;
their abort result remains unconfirmed. These limitations must be considered
before enabling the plugin on an existing long-running gateway.

## Local checks

```sh
node --test tests/frontend/toolBudget.test.mjs tests/frontend/toolBudgetHooks.test.mjs
```

The core and hook-adapter tests require no model, credentials, network, or
OpenClaw installation. They cover concurrent reservations, failed calls,
deadline boundaries, identity errors, cancellation failure, late callbacks,
and registry exhaustion. They do not substitute for native gateway acceptance.

The acceptance script starts an isolated native gateway, a loopback fake model,
and a harmless counter tool. It asserts that a five-call burst executes exactly
two effects, stopping that run leaves a concurrent run able to finish, and the
deadline aborts a model response that never completes. It requires no real
credentials or model service. Run it with the pinned Node version:

```sh
npm install --prefix /tmp/easel-budget-runtime --ignore-scripts openclaw@2026.10.2
node scripts/verify_native_tool_budget.mjs /tmp/easel-budget-runtime/node_modules/openclaw
node scripts/verify_native_tool_budget.mjs /tmp/easel-budget-runtime/node_modules/openclaw --tool-search
node scripts/verify_native_tool_budget.mjs /tmp/easel-budget-runtime/node_modules/openclaw --unlimited
```

Use an equivalent temporary directory on Windows. Each invocation creates its
own temporary state and loopback ports; it never changes the user's profile.
Only aggregate acceptance results go to stdout. Failed runs identify a local
diagnostic directory. CI runs both direct tools and Tool Search on Linux and
Windows; it does not upload raw gateway logs or transcripts.
The `--unlimited` check loads the plugin with an empty configuration, verifies
that five direct tools run and a model response outlasts the opt-in example's
deadline, and confirms no budget lifecycle hooks or capability RPC are active.

## Active process capability evidence

The plugin registers the read-only Gateway RPC `easel.toolBudget.capability`
after its execution hooks have registered. Supply a fresh 32–128 character
lowercase hexadecimal `nonce`. The response echoes the nonce and includes a
registration-specific `instanceId`, the pinned runtime version, immutable
`maxCalls`/`timeoutMs`, and `durability: process_memory`. The method requires
`operator.read` and the Gateway's normal profile authorization.

The probe rejects unsupported runtime versions, disabled conversation hooks,
disabled plugins, unavailable active configuration, and configuration that no
longer matches the installed hooks. It neither runs a model nor executes tools.
The native acceptance script checks this response before exercising the actual
execution limits through the same isolated Gateway fixture.

This is active registration evidence, **not a request admission token**. A
client must not cache it as permission for a later request, silently reconnect
to another Gateway, or enable strict mode on the strength of this response
alone. Use the guarded entrypoint below when submitting with this evidence.

## Guarded task submission

`easel.toolBudget.send` accepts exactly `instanceId`, `maxCalls`, `timeoutMs`,
`sessionKey`, `message`, and `idempotencyKey`. The first three values must match
the current capability response and the still-active immutable hook policy.
Changing the Gateway registration, disabling the plugin, or changing the
configured limits invalidates the request before dispatch.

This method requires `operator.write` and normal Gateway profile authorization.
It forwards only the three chat fields through the pinned SDK's authenticated
**in-process** `dispatchGatewayMethod('chat.send', ...)`, which retains the
requester's scope and lifetime without constructing a synthetic operator or
opening another connection. Core chat authorization and idempotency still
apply. The response confirms core admission, not successful task completion;
observe the normal run events for the outcome.

There is no HTTP/CLI fallback. A dispatch timeout or connection loss can occur
after acceptance; the caller must inspect the original task before retrying,
and must not generate a fresh idempotency key to bypass an uncertain outcome.
The native acceptance script now exercises actual tools through this guarded
entrypoint and rejects a previous registration ID before any model request.
Existing Easel chat transports and the global strict-mode setting are not yet
wired to this endpoint; do not describe those transports as protected by this
new admission binding until that integration is installed and verified.
