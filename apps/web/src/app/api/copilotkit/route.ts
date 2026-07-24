// CopilotKit runtime endpoint.
//
// The adapter points at Fireworks, not OpenAI: Fireworks exposes an
// OpenAI-compatible /v1 surface, so OpenAIAdapter works against it with a
// baseURL override. That means the copilot reuses the FIREWORKS_API_KEY this
// project already provisions — no new vendor, no new key.
//
// The key is read from a NON-public env var and stays server-side. It must
// never be exposed via NEXT_PUBLIC_* (see CLAUDE.md deployment section).
//
// If no key is configured, this route degrades to the previous inert
// behaviour (valid empty response) rather than throwing
// CopilotApiDiscoveryError and breaking page rendering — which is what
// happened the last time a provider was mounted without an adapter.
import {
  CopilotRuntime,
  OpenAIAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import OpenAI from "openai";
import { NextRequest, NextResponse } from "next/server";

const FIREWORKS_API_KEY = process.env.FIREWORKS_API_KEY;
const FIREWORKS_MODEL =
  process.env.COPILOT_MODEL || "accounts/fireworks/models/llama-v3p1-70b-instruct";

export const POST = async (req: NextRequest) => {
  if (!FIREWORKS_API_KEY) {
    // Inert fallback — keeps a mounted <CopilotKit> provider from crashing
    // the page when no key is present (e.g. a fresh clone, or Vercel preview
    // without env vars set).
    return NextResponse.json({ data: null }, { status: 200 });
  }

  const openai = new OpenAI({
    apiKey: FIREWORKS_API_KEY,
    baseURL: "https://api.fireworks.ai/inference/v1",
  });

  const runtime = new CopilotRuntime();
  const serviceAdapter = new OpenAIAdapter({
    openai,
    model: FIREWORKS_MODEL,
  });

  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter,
    endpoint: "/api/copilotkit",
  });

  return handleRequest(req);
};

export const GET = async () => {
  return NextResponse.json({
    status: FIREWORKS_API_KEY ? "copilot runtime active" : "copilot runtime disabled (no key)",
  });
};
