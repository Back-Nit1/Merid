"use client";

import { useCopilotAction, useCopilotReadable } from "@copilotkit/react-core";
import { CopilotSidebar } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";
import { post } from "@/lib/api";
import { RULE_RATIONALE } from "@/lib/ruleRationale";
import type { ReferralWorklistItem, TriageVerdict } from "@/lib/types";

/**
 * The nurse-facing copilot for a single referral.
 *
 * Scope, deliberately narrow:
 *   - It EXPLAINS a verdict using data already on the page (which rules fired,
 *     what was extracted, what is missing).
 *   - It DISPATCHES the same approve/escalate endpoints the buttons call.
 *   - It does NOT triage, does not set urgency, and does not diagnose. Urgency
 *     comes from the deterministic rule engine; the copilot only reports it.
 *
 * Every mutating action uses renderAndWaitForResponse, so a human physically
 * confirms before anything is signed (invariant #4 — the agent prepares,
 * humans commit). The LLM cannot approve a verdict on its own.
 */
export default function WorklistCopilot({
  item,
  onUpdated,
}: {
  item: ReferralWorklistItem;
  onUpdated: (v: TriageVerdict) => void;
}) {
  const verdict = item.verdict;

  // --- readable context ---------------------------------------------------
  // Grounds the copilot in this referral's real data so it answers from the
  // verdict rather than from the model's own clinical priors.
  useCopilotReadable({
    description:
      "The referral currently open in the nurse worklist, including its " +
      "extracted features, the deterministic triage verdict, and which rules fired.",
    value: {
      referral_id: item.referral_id,
      patient_name: item.patient_name,
      source: item.source,
      extracted_features: item.features,
      source_refs: item.features.source_refs,
      extraction_confidence: item.features.extraction_confidence,
      parsed_in_sandbox: item.sandbox?.sandboxed ?? false,
      verdict: verdict
        ? {
            verdict_id: verdict.id,
            urgency: verdict.urgency,
            disposition: verdict.disposition,
            rule_version: verdict.rule_version,
            rules_fired: verdict.rules_fired.map((id) => ({
              rule_id: id,
              rationale: RULE_RATIONALE[id] ?? null,
            })),
            missing_features: verdict.missing_features,
            approved_by: verdict.approved_by,
            booked_slot: verdict.booked_slot,
          }
        : null,
    },
  });

  // --- approve ------------------------------------------------------------
  useCopilotAction({
    name: "approveVerdict",
    description:
      "Approve the triage verdict for the referral currently open. This confirms " +
      "the booking and is signed by the named nurse. Requires human confirmation.",
    parameters: [
      {
        name: "actor",
        type: "string",
        description: "Full name of the approving nurse. Required.",
        required: true,
      },
      {
        name: "slot",
        type: "string",
        description:
          "Appointment slot, ISO-ish, e.g. '2026-07-28T09:00 urgent clinic'. Optional.",
        required: false,
      },
    ],
    renderAndWaitForResponse: ({ args, respond, status }) => {
      if (status === "complete") {
        return <div className="text-sm text-emerald-700">Approval submitted.</div>;
      }
      return (
        <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm">
          <p className="font-semibold text-emerald-900">Confirm approval</p>
          <p className="mt-1 text-emerald-800">
            Approve <code>{item.referral_id}</code>
            {verdict ? ` (${verdict.urgency})` : ""} as{" "}
            <strong>{args.actor || "—"}</strong>
            {args.slot ? ` for ${args.slot}` : ""}?
          </p>
          <p className="mt-1 text-xs text-emerald-700">
            This is signed and recorded with your name and a hash of the verdict.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700"
              onClick={async () => {
                if (!verdict) {
                  respond?.("No verdict on this referral; nothing to approve.");
                  return;
                }
                if (!args.actor?.trim()) {
                  respond?.("Refused: an approving nurse name is required.");
                  return;
                }
                try {
                  const res = await post<{
                    approval_hash: string;
                    approved_at: string;
                    slack?: string;
                    calendar?: string;
                  }>(
                    `/referrals/${item.referral_id}/verdicts/${verdict.id}/approve`,
                    { actor: args.actor.trim(), slot: args.slot?.trim() || undefined }
                  );
                  onUpdated({
                    ...verdict,
                    approved_by: args.actor.trim(),
                    approved_at: res.approved_at,
                    approval_hash: res.approval_hash,
                    booked_slot: args.slot?.trim() || verdict.booked_slot,
                  });
                  respond?.(
                    `Approved. Signed by ${args.actor.trim()}. ` +
                      `Slack: ${res.slack ?? "n/a"}. Calendar: ${res.calendar ?? "n/a"}.`
                  );
                } catch (e) {
                  respond?.(
                    `Approval failed: ${e instanceof Error ? e.message : "unknown error"}`
                  );
                }
              }}
            >
              Confirm
            </button>
            <button
              className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600"
              onClick={() => respond?.("Nurse cancelled the approval.")}
            >
              Cancel
            </button>
          </div>
        </div>
      );
    },
  });

  // --- escalate -----------------------------------------------------------
  useCopilotAction({
    name: "escalateVerdict",
    description:
      "Send this referral back for further human review with a reason. Use when " +
      "data is missing, contradictory, or the nurse is not comfortable approving.",
    parameters: [
      { name: "actor", type: "string", description: "Your full name.", required: true },
      {
        name: "reason",
        type: "string",
        description: "Why this needs another look. Required.",
        required: true,
      },
    ],
    renderAndWaitForResponse: ({ args, respond, status }) => {
      if (status === "complete") {
        return <div className="text-sm text-amber-700">Escalation submitted.</div>;
      }
      return (
        <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="font-semibold text-amber-900">Confirm escalation</p>
          <p className="mt-1 text-amber-800">
            Send <code>{item.referral_id}</code> back for review as{" "}
            <strong>{args.actor || "—"}</strong>?
          </p>
          <p className="mt-1 text-xs text-amber-700">Reason: {args.reason || "—"}</p>
          <div className="mt-3 flex gap-2">
            <button
              className="rounded bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700"
              onClick={async () => {
                if (!verdict) {
                  respond?.("No verdict on this referral; nothing to escalate.");
                  return;
                }
                if (!args.actor?.trim() || !args.reason?.trim()) {
                  respond?.("Refused: both a name and a reason are required.");
                  return;
                }
                try {
                  await post(
                    `/referrals/${item.referral_id}/verdicts/${verdict.id}/escalate`,
                    { actor: args.actor.trim(), reason: args.reason.trim() }
                  );
                  respond?.("Escalated for human review.");
                } catch (e) {
                  respond?.(
                    `Escalation failed: ${e instanceof Error ? e.message : "unknown error"}`
                  );
                }
              }}
            >
              Confirm
            </button>
            <button
              className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600"
              onClick={() => respond?.("Nurse cancelled the escalation.")}
            >
              Cancel
            </button>
          </div>
        </div>
      );
    },
  });

  return (
    <CopilotSidebar
      labels={{
        title: "Meridian assistant",
        initial:
          "I can explain this verdict — which rules fired and what the source " +
          "document said — and approve or escalate it once you confirm. I don't " +
          "diagnose or set urgency; that comes from the rule engine.",
      }}
      instructions={
        "You assist a triage nurse reviewing a GI referral in a DEMO system with " +
        "synthetic data.\n\n" +
        "HARD RULES:\n" +
        "1. Never state, suggest, or speculate about a diagnosis, condition name, " +
        "or likelihood. Not even to rule one out. If asked 'is this cancer?' or " +
        "'could this just be hemorrhoids?', say you cannot discuss conditions and " +
        "redirect to what the rules and extracted features actually say.\n" +
        "2. Never offer reassurance ('probably nothing', 'looks fine', 'wouldn't worry').\n" +
        "3. Never state or imply an urgency you derived yourself. Urgency comes " +
        "only from the deterministic rule engine — quote verdict.urgency and the " +
        "rules that fired. If asked whether the verdict is right, describe which " +
        "rule produced it and suggest escalation if the nurse disagrees.\n" +
        "4. Never approve or escalate without calling the corresponding action, " +
        "which requires explicit human confirmation.\n" +
        "5. Ground every answer in the readable referral context. If something " +
        "isn't there, say it's not in the record rather than inferring it.\n\n" +
        "You may: explain fired rules and their rationale, point at source_refs " +
        "for a feature, flag missing features, summarise what the nurse is being " +
        "asked to sign, and dispatch approve/escalate."
      }
    />
  );
}
