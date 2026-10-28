import PeerRadar from "../components/PeerRadar";
import ScheduleCard from "../components/ScheduleCard";
import { num, ratioLabel, ratioValue } from "../components/format";
import type { PeerBenchmark as PeerBenchmarkData, PeerCompany } from "../api/types";

export default function PeerBenchmark({
  benchmark,
  peers,
}: {
  benchmark: PeerBenchmarkData | null;
  peers: PeerCompany[];
}) {
  if (!benchmark || benchmark.peer_count === 0) {
    return (
      <ScheduleCard
        reference="Schedule 15"
        title="Peer benchmark"
        note="Attach a sourced peer set with POST /companies/{id}/peer-set. Until then the percentile field stays empty rather than reporting a position against nobody."
      >
        <p className="sheet-note">No peer set is attached to this company.</p>
      </ScheduleCard>
    );
  }

  const scored = Object.entries(benchmark.ratios);

  return (
    <div className="space-y-6">
      <ScheduleCard
        reference="Schedule 15"
        title="Standing against the peer set"
        aside={
          <span className="chip-neutral">
            {benchmark.peer_count} peer{benchmark.peer_count === 1 ? "" : "s"}
          </span>
        }
        note={benchmark.calculation_basis.interpretation_limit}
      >
        <div className="grid gap-4 px-4 py-4 md:grid-cols-[auto_minmax(0,1fr)] md:items-center">
          <div className="flex justify-center">
            <PeerRadar percentiles={benchmark.category_percentiles} />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">
              Weighted standing
            </p>
            <p className="font-mono text-4xl leading-tight text-foreground">
              {benchmark.industry_percentile === null ? "—" : num(benchmark.industry_percentile, 1)}
            </p>
            <p className="text-2xs text-muted-foreground">
              percentile, weighted by the health-score weights
            </p>
            <p className="mt-3 font-mono text-2xs leading-relaxed text-muted-foreground">
              {benchmark.calculation_basis.method}
            </p>
            <p className="mt-3 text-2xs leading-relaxed text-muted-foreground">
              {benchmark.calculation_basis.why_a_z_score_rather_than_a_rank}
            </p>
          </div>
        </div>
      </ScheduleCard>

      <ScheduleCard reference="Schedule 16" title="Per-ratio standing">
        <div className="overflow-x-auto">
          <table className="ledger">
            <thead>
              <tr>
                <th>Ratio</th>
                <th className="text-right">Company</th>
                <th className="text-right">Peer mean</th>
                <th className="text-right">σ</th>
                <th className="text-right">z</th>
                <th className="text-right">Percentile</th>
                <th className="text-right">Rank</th>
              </tr>
            </thead>
            <tbody>
              {scored.map(([key, entry]) => (
                <tr key={key} title={entry.reason ?? entry.extrapolation_note}>
                  <td className="text-foreground">
                    {ratioLabel(key)}
                    {!entry.higher_is_better && (
                      <span className="ml-1 font-mono text-2xs text-muted-foreground">lower is better</span>
                    )}
                  </td>
                  <td className="num">{ratioValue(key, entry.value)}</td>
                  <td className="num-dim">
                    {entry.peer_mean === undefined ? "—" : num(entry.peer_mean)}
                  </td>
                  <td className="num-dim">
                    {entry.peer_stdev === undefined ? "—" : num(entry.peer_stdev)}
                  </td>
                  <td className="num-dim">{entry.z_score === undefined ? "—" : num(entry.z_score)}</td>
                  <td className="num">
                    {entry.percentile === undefined ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      <>
                        {num(entry.percentile, 1)}
                        {entry.extrapolated && <span className="ml-1 font-semibold text-foreground">*</span>}
                      </>
                    )}
                  </td>
                  <td className="num-dim">{entry.peer_rank ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="sheet-note border-t border-border">
          <span className="font-semibold text-foreground">*</span> |z| above 2. Φ is being read in a tail this many peers
          cannot establish; read the rank instead. Ratios marked “—” had too few peers reporting them,
          or a peer set with no variance at all.
        </p>
      </ScheduleCard>

      <ScheduleCard reference="Schedule 17" title="The peer set, and where it came from">
        <div className="overflow-x-auto">
          <table className="ledger">
            <thead>
              <tr>
                <th>Peer</th>
                <th>Industry</th>
                <th className="text-right">FY</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {peers.map((peer) => (
                <tr key={peer.id}>
                  <td className="text-foreground">{peer.peer_name}</td>
                  <td>{peer.industry ?? "—"}</td>
                  <td className="num-dim">{peer.fiscal_year ?? "—"}</td>
                  <td className="text-2xs leading-relaxed">{peer.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ScheduleCard>
    </div>
  );
}
