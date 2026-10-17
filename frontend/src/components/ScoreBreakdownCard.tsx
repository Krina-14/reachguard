import React from "react";
import type { ScoreBreakdown } from "../api/types";

interface ScoreBreakdownCardProps {
  score: number;
  breakdown: ScoreBreakdown;
}

export const ScoreBreakdownCard: React.FC<ScoreBreakdownCardProps> = ({
  score,
  breakdown,
}) => {
  const getScoreColor = (val: number) => {
    if (val >= 75) return "text-red-400 bg-red-500";
    if (val >= 45) return "text-amber-400 bg-amber-500";
    return "text-slate-400 bg-slate-400";
  };

  const scoreColor = getScoreColor(score);
  const formulaText =
    breakdown.formula || "round(100*(0.5*reach+0.3*severity+0.2*exposure))";

  return (
    <div className="bg-bg-surface border border-border rounded-xl p-4 shadow-sm space-y-3">
      {/* Score Header with Progress Bar */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
            Risk Score
          </span>
          <span className={`text-2xl font-bold font-mono ${scoreColor.split(" ")[0]}`}>
            {score}
            <span className="text-xs text-gray-500 font-sans font-normal ml-1">/ 100</span>
          </span>
        </div>
        <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${scoreColor.split(" ")[1]}`}
            style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
          />
        </div>
      </div>

      {/* Breakdown Small Table */}
      <div className="overflow-hidden border border-border/70 rounded-lg">
        <table className="w-full text-left text-xs">
          <thead className="bg-bg-card text-gray-400 border-b border-border/70 text-[11px]">
            <tr>
              <th className="py-1.5 px-2.5 font-medium">Factor</th>
              <th className="py-1.5 px-2.5 font-medium text-right">Value</th>
              <th className="py-1.5 px-2.5 font-medium text-right">Weight</th>
              <th className="py-1.5 px-2.5 font-medium text-right">Weighted</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/40 font-mono text-[11px]">
            <tr>
              <td className="py-1.5 px-2.5 text-gray-300 font-sans">Reachability</td>
              <td className="py-1.5 px-2.5 text-right text-gray-200">
                {breakdown.reach.toFixed(2)}
              </td>
              <td className="py-1.5 px-2.5 text-right text-gray-400">50%</td>
              <td className="py-1.5 px-2.5 text-right text-accent font-semibold">
                {(breakdown.reach * 0.5 * 100).toFixed(1)}
              </td>
            </tr>
            <tr>
              <td className="py-1.5 px-2.5 text-gray-300 font-sans">Severity</td>
              <td className="py-1.5 px-2.5 text-right text-gray-200">
                {breakdown.severity.toFixed(2)}
              </td>
              <td className="py-1.5 px-2.5 text-right text-gray-400">30%</td>
              <td className="py-1.5 px-2.5 text-right text-accent font-semibold">
                {(breakdown.severity * 0.3 * 100).toFixed(1)}
              </td>
            </tr>
            <tr>
              <td className="py-1.5 px-2.5 text-gray-300 font-sans">Exposure</td>
              <td className="py-1.5 px-2.5 text-right text-gray-200">
                {breakdown.exposure.toFixed(2)}
              </td>
              <td className="py-1.5 px-2.5 text-right text-gray-400">20%</td>
              <td className="py-1.5 px-2.5 text-right text-accent font-semibold">
                {(breakdown.exposure * 0.2 * 100).toFixed(1)}
              </td>
            </tr>
            <tr className="bg-bg-card/50 font-semibold text-white">
              <td className="py-1.5 px-2.5 font-sans">Final Score</td>
              <td colSpan={2} className="py-1.5 px-2.5 text-right text-gray-400 text-[10px] font-sans">
                round(sum)
              </td>
              <td className="py-1.5 px-2.5 text-right text-white font-bold">
                {score}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Formula text from API */}
      <div className="bg-bg-card/60 p-2 rounded-lg border border-border/50">
        <span className="text-[10px] uppercase font-mono text-gray-400 block mb-0.5">
          Scoring Formula
        </span>
        <code className="text-[11px] font-mono text-cyan-300 break-all">
          {formulaText}
        </code>
      </div>
    </div>
  );
};
