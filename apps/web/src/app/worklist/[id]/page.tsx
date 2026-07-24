"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { ApiError, get } from "@/lib/api";
import type { ReferralWorklistItem, TriageVerdict } from "@/lib/types";
import FeatureTable from "@/components/FeatureTable";
import VerdictPanel from "@/components/VerdictPanel";
import WorklistCopilot from "@/components/WorklistCopilot";
import { SandboxBadge } from "@/components/badges";

export default function ReferralDetailPage() {
  const params = useParams<{ id: string }>();
  const referralId = params.id;
  const [item, setItem] = useState<ReferralWorklistItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    get<ReferralWorklistItem>(`/referrals/${referralId}`)
      .then((data) => {
        if (!cancelled) setItem(data);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError && err.status === 404
              ? "Referral not found."
              : "Could not load this referral."
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [referralId]);

  function handleVerdictUpdated(v: TriageVerdict) {
    setItem((prev) => (prev ? { ...prev, verdict: v } : prev));
  }

  return (
    <div>
      <Link href="/worklist" className="text-sm text-slate-500 hover:underline">
        ← Back to worklist
      </Link>

      {error && (
        <p className="mt-4 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          {error}
        </p>
      )}

      {!error && !item && <p className="mt-4 text-sm text-slate-400">Loading…</p>}

      {item && (
        <div className="mt-4 space-y-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{item.patient_name}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {item.source} · received {new Date(item.created_at).toLocaleString()}
            </p>
            {item.sandbox?.sandboxed && (
              <div className="mt-2">
                <SandboxBadge sandbox={item.sandbox} />
              </div>
            )}
          </div>

          <div>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Source text
            </h2>
            <p className="whitespace-pre-wrap rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
              {item.raw_text}
            </p>
          </div>

          <div>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Extracted features
            </h2>
            <FeatureTable features={item.features} />
          </div>

          <div>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Verdict
            </h2>
            {item.verdict ? (
              <VerdictPanel
                referralId={item.referral_id}
                verdict={item.verdict}
                onUpdated={handleVerdictUpdated}
              />
            ) : (
              <p className="rounded-lg border border-dashed border-slate-300 px-4 py-6 text-center text-sm text-slate-500 dark:border-slate-700">
                No verdict yet for this referral.
              </p>
            )}
          </div>

          {/* Nurse copilot — reads this referral's verdict, dispatches
              approve/escalate with human confirmation. Mounted only once the
              item has loaded so the readable context is never empty. */}
          <WorklistCopilot item={item} onUpdated={handleVerdictUpdated} />
        </div>
      )}
    </div>
  );
}
