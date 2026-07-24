"use client";

import { CopilotKit } from "@copilotkit/react-core";

/**
 * App providers.
 *
 * CopilotKit is mounted here and backed by a real adapter in
 * src/app/api/copilotkit/route.ts (Fireworks via its OpenAI-compatible API).
 *
 * History worth knowing: a previous version mounted this provider against an
 * adapter-less route, which failed agent discovery with
 * `CopilotApiDiscoveryError` and broke page rendering. The route now returns a
 * valid response even with no API key configured, so a missing key degrades
 * the copilot to a no-op instead of taking the worklist down with it.
 *
 * The copilot is scoped deliberately: it reads verdict data made available via
 * useCopilotReadable and dispatches the same approve/escalate endpoints the
 * buttons use. It does not triage, and it cannot set urgency — that stays in
 * the deterministic rule engine (see CLAUDE.md, "LLMs extract. Rules decide.").
 */
export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <CopilotKit runtimeUrl="/api/copilotkit">
      {children}
    </CopilotKit>
  );
}
