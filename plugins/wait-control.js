// dsh-ctf-mode/wait-control
//
// Code-level enforcement for the CTF preset: the controller must not wait on
// subagents. The preset removes `wait_agent` from the tool surface
// (restriction) and denies any residual call (guard) with an actionable reason.
// Waiting that a command itself needs (build/download/request) is unaffected.

export const inject = ['tools'];

export function apply(ctx) {
  ctx.effect(() => {
    try {
      return ctx.tools.restrict({ deny: ['wait_agent'] });
    } catch {
      // Control tools may not be registered yet; the guard below still denies.
      return () => {};
    }
  });

  ctx.effect(() => ctx.tools.guard((exec) => {
    if (exec && exec.name === 'wait_agent') {
      return {
        reason: 'wait_agent is disabled in the CTF preset: do not wait on subagents. ' +
                'End your turn; subagent reports and completion notices arrive as messages. ' +
                'Blocking waits that a command itself needs (build/download/request) are normal.',
        info: { name: 'wait_agent', code: 'WAIT_AGENT_DISABLED' },
      };
    }
    return undefined;
  }));
}
