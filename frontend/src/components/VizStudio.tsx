import React, { useMemo } from 'react';
import { AgCharts } from 'ag-charts-react';
import type { AgChartOptions } from 'ag-charts-community';
import {
  ModuleRegistry,
  BarSeriesModule,
  DonutSeriesModule,
  CategoryAxisModule,
  NumberAxisModule,
} from 'ag-charts-community';
import {
  TrendingUp,
  ShieldAlert,
  CheckCircle2,
  Zap,
  Sparkles,
  ArrowUpRight,
  Clock,
  AlertTriangle,
} from 'lucide-react';

// Register only required AG Charts community modules (tree-shaken)
ModuleRegistry.registerModules([
  BarSeriesModule,
  DonutSeriesModule,
  CategoryAxisModule,
  NumberAxisModule,
]);

interface VizStudioProps {
  cases?: any[];
}

export const VizStudio: React.FC<VizStudioProps> = ({ cases = [] }) => {
  // 1. Calculate Aggregate Recovery KPIs & Executive Insights
  const { kpis, insights, topDrivers, channelStats } = useMemo(() => {
    let totalRisk = 0;
    let totalRecovered = 0;
    let recoveredCount = 0;
    let escalatedCount = 0;

    const channelMap: Record<
      string,
      { channel: string; recovered: number; active: number; totalCount: number; recCount: number }
    > = {};

    const rawReasonMap: Record<string, { amount: number; count: number }> = {};
    const touchCounts = [
      { touch: '1st Touch', engaged: 0, recovered: 0 },
      { touch: '2nd Touch', engaged: 0, recovered: 0 },
      { touch: '3rd Touch', engaged: 0, recovered: 0 },
    ];

    cases.forEach((c) => {
      const amt = Number(c.amount || 0);
      const rec = Number(c.recovered_amount || 0);
      totalRisk += amt;
      totalRecovered += rec;

      const isRecovered = c.recovery_status === 'recovered';
      const isEscalated = c.recovery_status === 'escalated';

      if (isRecovered) recoveredCount++;
      if (isEscalated) escalatedCount++;

      // Channel metrics
      const rawAction = c.last_action_taken;
      const chKey = rawAction ? rawAction.replace(/^play_/, '') : 'pending_outreach';
      const chLabel = chKey
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (l: string) => l.toUpperCase());

      if (!channelMap[chLabel]) {
        channelMap[chLabel] = {
          channel: chLabel,
          recovered: 0,
          active: 0,
          totalCount: 0,
          recCount: 0,
        };
      }
      channelMap[chLabel].totalCount += 1;
      if (isRecovered) {
        channelMap[chLabel].recovered += rec;
        channelMap[chLabel].recCount += 1;
      } else {
        channelMap[chLabel].active += amt;
      }

      // Failure reason normalization (group verbose codes into 5 clean categories)
      let r = (c.failure_reason || 'INSUFFICIENT_FUNDS').replace(/_/g, ' ').trim();
      if (/card.*expire|mandate/i.test(r)) r = 'Card Expired / Mandate';
      else if (/insufficient.*fund/i.test(r)) r = 'Insufficient Funds';
      else if (/invoice.*overdue/i.test(r)) r = 'Invoice Overdue';
      else if (/abandon/i.test(r)) r = 'Checkout Abandoned';
      else if (/fraud|stolen|velocity/i.test(r)) r = 'Risk & Velocity Flags';
      else if (/declined|hold|processor/i.test(r)) r = 'Processor Declined';
      else r = r.replace(/\b\w/g, (l: string) => l.toUpperCase());

      if (!rawReasonMap[r]) rawReasonMap[r] = { amount: 0, count: 0 };
      rawReasonMap[r].amount += amt;
      rawReasonMap[r].count += 1;

      // Touch cadence tracking
      const attempts = Math.min(Math.max(Number(c.attempt_count || 1), 1), 3);
      const touchIdx = attempts - 1;
      touchCounts[touchIdx].engaged += 1;
      if (isRecovered) {
        touchCounts[touchIdx].recovered += 1;
      }
    });

    const activeCount = Math.max(0, cases.length - recoveredCount - escalatedCount);
    const rate = cases.length > 0 ? ((recoveredCount / cases.length) * 100).toFixed(1) : '0.0';

    // Top 4 Failure reasons + "Other"
    const sortedReasons = Object.entries(rawReasonMap).sort((a, b) => b[1].amount - a[1].amount);
    const top4 = sortedReasons.slice(0, 4);
    const otherSum = sortedReasons.slice(4).reduce((sum, [, d]) => sum + d.amount, 0);
    const otherCount = sortedReasons.slice(4).reduce((sum, [, d]) => sum + d.count, 0);

    const recommendedPlayMap: Record<string, string> = {
      'Card Expired / Mandate': 'Auto Card Updater + Instant Link',
      'Insufficient Funds': 'Scheduled Retry on Payday Cadence',
      'Invoice Overdue': 'Multi-Tier Friendly WhatsApp Nudge',
      'Checkout Abandoned': '1-Click PayPal Fastlane Re-engagement',
      'Risk & Velocity Flags': 'Human Merchant Review & KYC Check',
      'Processor Declined': 'Alternative Rail (Debit / Wallet / ACH)',
      'Other Declines': 'Automated Fallback Link',
    };

    const topDrivers = top4.map(([reason, d], idx) => ({
      rank: idx + 1,
      reason,
      amount: d.amount,
      count: d.count,
      pct: totalRisk > 0 ? Math.round((d.amount / totalRisk) * 100) : 0,
      playbook: recommendedPlayMap[reason] || 'Automated Outreach Flow',
    }));

    if (otherSum > 0) {
      topDrivers.push({
        rank: 5,
        reason: 'Other Declines',
        amount: otherSum,
        count: otherCount,
        pct: totalRisk > 0 ? Math.round((otherSum / totalRisk) * 100) : 0,
        playbook: 'General Fallback Play',
      });
    }

    // Dynamic Executive Insights
    const topChannel = Object.values(channelMap).sort((a, b) => b.recovered - a.recovered)[0];
    const topDecline = topDrivers[0];
    const touch1 = touchCounts[0];
    const touch1Share =
      recoveredCount > 0 ? Math.round((touch1.recovered / recoveredCount) * 100) : 0;

    const insights = [
      {
        icon: Sparkles,
        title: 'Top Performing Playbook',
        description: topChannel
          ? `${topChannel.channel} captured $${topChannel.recovered.toLocaleString()} across ${topChannel.recCount} recovered cases.`
          : 'Awaiting playbook dispatch telemetry.',
        color: 'text-emerald-400',
        bg: 'bg-emerald-500/10 border-emerald-500/20',
      },
      {
        icon: AlertTriangle,
        title: 'Primary Revenue Leakage',
        description: topDecline
          ? `${topDecline.reason} accounts for ${topDecline.pct}% ($${topDecline.amount.toLocaleString()}) of total at-risk capital.`
          : 'Zero critical risk concentrations detected.',
        color: 'text-amber-400',
        bg: 'bg-amber-500/10 border-amber-500/20',
      },
      {
        icon: Clock,
        title: 'Touchpoint Velocity',
        description:
          recoveredCount > 0
            ? `${touch1Share}% of all recovered cash settles on the 1st touch before drop-off occurs.`
            : 'Multi-touch cadences active across pipeline.',
        color: 'text-blue-400',
        bg: 'bg-blue-500/10 border-blue-500/20',
      },
    ];

    return {
      kpis: {
        totalRisk,
        totalRecovered,
        recoveredCount,
        activeCount,
        escalatedCount,
        rate,
      },
      insights,
      topDrivers,
      channelStats: Object.values(channelMap),
    };
  }, [cases]);

  // Shared dark theme styling matching Renvue's Graphite aesthetic
  const commonTheme: any = useMemo(
    () => ({
      baseTheme: 'ag-default-dark',
      palette: {
        fills: ['#4cc38a', '#f59e0b', '#3b82f6', '#a855f7', '#71717a'],
        strokes: ['#18181b', '#18181b', '#18181b', '#18181b', '#18181b'],
      },
      overrides: {
        common: {
          background: { fill: 'transparent' },
          title: {
            color: '#ededed',
            fontFamily: "'Geist Variable', -apple-system, BlinkMacSystemFont, sans-serif",
            fontSize: 12,
            fontWeight: 500,
          },
          subtitle: {
            color: '#8e8e93',
            fontFamily: "'Geist Variable', -apple-system, BlinkMacSystemFont, sans-serif",
            fontSize: 11,
          },
          legend: {
            item: {
              label: {
                color: '#8e8e93',
                fontFamily: "'Geist Variable', -apple-system, BlinkMacSystemFont, sans-serif",
                fontSize: 11,
              },
            },
          },
        },
      },
    }),
    []
  );

  // 2. Chart 1: Outreach Channel ROI (Grouped Bar)
  const channelChartOptions: AgChartOptions = useMemo(() => {
    const data = [...channelStats].sort((a, b) => b.recovered + b.active - (a.recovered + a.active));

    return {
      theme: commonTheme,
      data,
      series: [
        {
          type: 'bar',
          direction: 'horizontal',
          xKey: 'channel',
          yKey: 'recovered',
          yName: 'Recovered ($)',
          fill: '#4cc38a',
          stroke: '#18181b',
        },
        {
          type: 'bar',
          direction: 'horizontal',
          xKey: 'channel',
          yKey: 'active',
          yName: 'Active Pipeline ($)',
          fill: '#f59e0b',
          stroke: '#18181b',
        },
      ],
      axes: {
        x: {
          type: 'category',
          position: 'left',
          label: { color: '#8e8e93', fontSize: 11 },
          line: { stroke: 'rgba(255, 255, 255, 0.08)' },
        },
        y: {
          type: 'number',
          position: 'bottom',
          label: {
            color: '#8e8e93',
            fontSize: 11,
            formatter: (params: any) => `$${params.value?.toLocaleString?.() ?? params.value}`,
          },
          gridLine: { style: [{ stroke: 'rgba(255, 255, 255, 0.04)' }] },
          line: { stroke: 'rgba(255, 255, 255, 0.08)' },
        },
      },
    };
  }, [channelStats, commonTheme]);

  // 3. Chart 2: Focused 5-Segment Root Cause Donut
  const failureReasonOptions: AgChartOptions = useMemo(() => {
    return {
      theme: commonTheme,
      data: topDrivers,
      series: [
        {
          type: 'donut',
          calloutLabelKey: 'reason',
          angleKey: 'amount',
          legendItemKey: 'reason',
          innerRadiusRatio: 0.68,
          strokes: ['#141416'],
          strokeWidth: 2,
          calloutLabel: {
            color: '#ededed',
            fontSize: 10,
            formatter: (p: any) => `${p.datum.pct}%`,
          },
          tooltip: {
            renderer: (params: any) => ({
              heading: params.datum.reason,
              data: [
                {
                  label: 'Revenue at Risk',
                  value: `$${Number(params.datum.amount).toLocaleString()} USD`,
                },
                {
                  label: 'Share of Risk',
                  value: `${params.datum.pct}% (${params.datum.count} cases)`,
                },
              ],
            }),
          },
        },
      ],
    };
  }, [topDrivers, commonTheme]);

  // 4. Chart 3: Touch Cadence Velocity (Cases Engaged vs Recovered)
  const touchChartOptions: AgChartOptions = useMemo(() => {
    const touchStats = [
      { touch: '1st Touch', cases: 0, recovered: 0 },
      { touch: '2nd Touch', cases: 0, recovered: 0 },
      { touch: '3rd Touch', cases: 0, recovered: 0 },
    ];

    cases.forEach((c) => {
      const attempts = Math.min(Math.max(Number(c.attempt_count || 1), 1), 3);
      const idx = attempts - 1;
      touchStats[idx].cases += 1;
      if (c.recovery_status === 'recovered') {
        touchStats[idx].recovered += 1;
      }
    });

    return {
      theme: commonTheme,
      data: touchStats,
      series: [
        {
          type: 'bar',
          direction: 'vertical',
          xKey: 'touch',
          yKey: 'cases',
          yName: 'Cases Engaged',
          fill: '#3b82f6',
          stroke: '#18181b',
        },
        {
          type: 'bar',
          direction: 'vertical',
          xKey: 'touch',
          yKey: 'recovered',
          yName: 'Cases Recovered',
          fill: '#4cc38a',
          stroke: '#18181b',
        },
      ],
      axes: {
        x: {
          type: 'category',
          position: 'bottom',
          label: { color: '#8e8e93', fontSize: 11 },
          line: { stroke: 'rgba(255, 255, 255, 0.08)' },
        },
        y: {
          type: 'number',
          position: 'left',
          label: { color: '#8e8e93', fontSize: 11 },
          gridLine: { style: [{ stroke: 'rgba(255, 255, 255, 0.04)' }] },
          line: { stroke: 'rgba(255, 255, 255, 0.08)' },
        },
      },
    };
  }, [cases, commonTheme]);

  // 5. Chart 4: Amount Tier Win Rates
  const tierChartOptions: AgChartOptions = useMemo(() => {
    const tierMap: Record<string, { tier: string; total: number; rec: number }> = {
      'Micro (< $100)': { tier: 'Micro (< $100)', total: 0, rec: 0 },
      'Mid ($100 - $1k)': { tier: 'Mid ($100 - $1k)', total: 0, rec: 0 },
      'High ($1k - $5k)': { tier: 'High ($1k - $5k)', total: 0, rec: 0 },
      'Enterprise (> $5k)': { tier: 'Enterprise (> $5k)', total: 0, rec: 0 },
    };

    cases.forEach((c) => {
      const amt = Number(c.amount || 0);
      let key = 'Mid ($100 - $1k)';
      if (amt < 100) key = 'Micro (< $100)';
      else if (amt > 5000) key = 'Enterprise (> $5k)';
      else if (amt >= 1000) key = 'High ($1k - $5k)';

      tierMap[key].total += 1;
      if (c.recovery_status === 'recovered') tierMap[key].rec += 1;
    });

    const data = Object.values(tierMap).map((t) => ({
      tier: t.tier,
      volume: t.total,
      recoveredRate: t.total > 0 ? Math.round((t.rec / t.total) * 100) : 0,
    }));

    return {
      theme: commonTheme,
      data,
      series: [
        {
          type: 'bar',
          direction: 'horizontal',
          xKey: 'tier',
          yKey: 'recoveredRate',
          yName: 'Recovery Rate (%)',
          fill: '#06b6d4',
          stroke: '#18181b',
        },
      ],
      axes: {
        x: {
          type: 'category',
          position: 'left',
          label: { color: '#8e8e93', fontSize: 11 },
          line: { stroke: 'rgba(255, 255, 255, 0.08)' },
        },
        y: {
          type: 'number',
          position: 'bottom',
          min: 0,
          max: 100,
          label: {
            color: '#8e8e93',
            fontSize: 11,
            formatter: (p: any) => `${p.value}%`,
          },
          gridLine: { style: [{ stroke: 'rgba(255, 255, 255, 0.04)' }] },
          line: { stroke: 'rgba(255, 255, 255, 0.08)' },
        },
      },
    };
  }, [cases, commonTheme]);

  return (
    <div className="space-y-6">
      {/* Editorial Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-hairline">
        <div>
          <h2 className="text-xs font-medium text-primary uppercase tracking-wider">
            Recovery Telemetry & Yield Analytics
          </h2>
          <p className="text-xs text-muted mt-0.5">
            Real-time pipeline diagnostics across PayPal payment declines, outreach cadence, and resolution yield
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 text-[10px] font-mono rounded bg-raised border border-hairline text-secondary">
            {cases.length} Total Events
          </span>
          <span className="px-2 py-0.5 text-[10px] font-mono rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Live Telemetry
          </span>
        </div>
      </div>

      {/* Top Metric Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 rounded-lg border border-hairline bg-card">
          <div className="flex items-center justify-between text-muted mb-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider">Recovery Rate</span>
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <div className="text-xl font-semibold text-primary tabular font-mono">{kpis.rate}%</div>
          <div className="text-[11px] text-muted mt-0.5">
            {kpis.recoveredCount} of {cases.length} cases settled
          </div>
        </div>

        <div className="p-3.5 rounded-lg border border-hairline bg-card">
          <div className="flex items-center justify-between text-muted mb-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider">Recovered Dollars</span>
            <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <div className="text-xl font-semibold text-emerald-400 tabular font-mono">
            ${kpis.totalRecovered.toLocaleString()}
          </div>
          <div className="text-[11px] text-muted mt-0.5">Captured via automated plays</div>
        </div>

        <div className="p-3.5 rounded-lg border border-hairline bg-card">
          <div className="flex items-center justify-between text-muted mb-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider">Active Exposure</span>
            <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
          </div>
          <div className="text-xl font-semibold text-primary tabular font-mono">
            ${(kpis.totalRisk - kpis.totalRecovered).toLocaleString()}
          </div>
          <div className="text-[11px] text-muted mt-0.5">{kpis.activeCount} cases in recovery pipeline</div>
        </div>

        <div className="p-3.5 rounded-lg border border-hairline bg-card">
          <div className="flex items-center justify-between text-muted mb-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider">Human Escalations</span>
            <Zap className="w-3.5 h-3.5 text-rose-400" />
          </div>
          <div className="text-xl font-semibold text-rose-400 tabular font-mono">{kpis.escalatedCount}</div>
          <div className="text-[11px] text-muted mt-0.5">Paused pending merchant approval</div>
        </div>
      </div>

      {/* Dynamic Executive Insights Strip */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {insights.map((ins, i) => {
          const Icon = ins.icon;
          return (
            <div
              key={i}
              className={`p-3 rounded-lg border bg-card/70 flex items-start gap-2.5 transition-colors ${ins.bg}`}
            >
              <div className={`p-1.5 rounded bg-raised border border-hairline shrink-0 mt-0.5 ${ins.color}`}>
                <Icon className="w-3.5 h-3.5" />
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium text-primary">{ins.title}</div>
                <div className="text-[11px] text-muted mt-0.5 leading-snug">{ins.description}</div>
              </div>
            </div>
          );
        })}
      </div>

      {/* SECTION 1: Outreach & Cadence Yield (Asymmetric 7:5 Grid) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left: Playbook ROI (7 cols) */}
        <div className="lg:col-span-7 p-4 rounded-lg border border-hairline bg-card flex flex-col justify-between">
          <div className="mb-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-medium text-primary">Outreach Playbook Yield</h3>
              <span className="text-[10px] text-muted font-mono">Cash Settled vs Active Pipeline</span>
            </div>
            <p className="text-[11px] text-muted mt-0.5">
              Direct dollar comparison of revenue collected vs remaining exposure per recovery playbook
            </p>
          </div>

          <div className="min-h-[280px]">
            <AgCharts options={channelChartOptions} />
          </div>

          <div className="pt-3 border-t border-hairline flex flex-wrap items-center gap-2 text-[10px] text-muted">
            <span className="font-medium text-secondary">Channel Win Rates:</span>
            {channelStats.map((ch) => {
              const wr = ch.totalCount > 0 ? Math.round((ch.recCount / ch.totalCount) * 100) : 0;
              return (
                <span
                  key={ch.channel}
                  className="px-2 py-0.5 rounded bg-raised border border-hairline text-secondary font-mono"
                >
                  {ch.channel}: <strong className="text-emerald-400">{wr}%</strong> ({ch.recCount}/{ch.totalCount})
                </span>
              );
            })}
          </div>
        </div>

        {/* Right: Touch Cadence Velocity (5 cols) */}
        <div className="lg:col-span-5 p-4 rounded-lg border border-hairline bg-card flex flex-col justify-between">
          <div className="mb-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-medium text-primary">Touch Cadence Velocity</h3>
              <span className="text-[10px] text-muted font-mono">Sequential Drop-off</span>
            </div>
            <p className="text-[11px] text-muted mt-0.5">
              Case engagement vs settled outcomes as the 3-step outreach cadence progresses
            </p>
          </div>

          <div className="min-h-[280px]">
            <AgCharts options={touchChartOptions} />
          </div>

          <div className="pt-3 border-t border-hairline text-[11px] text-muted flex items-center justify-between">
            <span>💡 1st Touch drives primary cash settlement</span>
            <span className="text-secondary font-mono text-[10px]">Diminishing returns at Touch 3</span>
          </div>
        </div>
      </div>

      {/* SECTION 2: Root-Cause Diagnostics & Ticket Sizing (Asymmetric 7:5 Grid) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left: Failure Reason Diagnostics with 5-Slice Donut + Ranked Breakdown (7 cols) */}
        <div className="lg:col-span-7 p-4 rounded-lg border border-hairline bg-card flex flex-col justify-between">
          <div className="mb-2">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-medium text-primary">Primary Decline Drivers</h3>
              <span className="text-[10px] text-muted font-mono">Consolidated Root-Cause Analysis</span>
            </div>
            <p className="text-[11px] text-muted mt-0.5">
              Top 4 failure codes driving revenue risk, normalized into actionable operational categories
            </p>
          </div>

          {/* Side-by-side: Clean Donut (left) + Ranked Actionable Drivers (right) */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-4 items-center py-2">
            <div className="md:col-span-5 min-h-[240px]">
              <AgCharts options={failureReasonOptions} />
            </div>

            {/* Ranked Drivers Table */}
            <div className="md:col-span-7 space-y-2">
              {topDrivers.map((d) => (
                <div
                  key={d.reason}
                  className="p-2 rounded bg-raised border border-hairline text-xs flex flex-col gap-1"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 font-medium text-primary truncate">
                      <span className="w-4 h-4 rounded bg-deep border border-hairline flex items-center justify-center text-[10px] text-muted font-mono shrink-0">
                        {d.rank}
                      </span>
                      <span className="truncate">{d.reason}</span>
                    </div>
                    <div className="text-right shrink-0">
                      <span className="text-secondary font-mono font-medium">
                        ${d.amount.toLocaleString()}
                      </span>
                      <span className="text-muted text-[10px] ml-1.5 font-mono">({d.pct}%)</span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-[10px] text-muted pt-0.5 border-t border-hairline/60">
                    <span className="flex items-center gap-1 text-emerald-400">
                      <ArrowUpRight className="w-2.5 h-2.5" />
                      <span>{d.playbook}</span>
                    </span>
                    <span>{d.count} cases</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="pt-2 border-t border-hairline text-[11px] text-muted flex items-center justify-between">
            <span>Aggregated across all transaction decline codes</span>
            <span className="text-secondary font-mono text-[10px]">
              ${topDrivers.reduce((s, d) => s + d.amount, 0).toLocaleString()} Total Exposure
            </span>
          </div>
        </div>

        {/* Right: Ticket Size Tier Recovery Rates (5 cols) */}
        <div className="lg:col-span-5 p-4 rounded-lg border border-hairline bg-card flex flex-col justify-between">
          <div className="mb-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-medium text-primary">Win Rate by Ticket Size</h3>
              <span className="text-[10px] text-muted font-mono">Amount Tier Yield</span>
            </div>
            <p className="text-[11px] text-muted mt-0.5">
              Percentage of cases settled grouped by ticket value (Micro to Enterprise)
            </p>
          </div>

          <div className="min-h-[240px]">
            <AgCharts options={tierChartOptions} />
          </div>

          <div className="pt-3 border-t border-hairline text-[11px] text-muted flex items-center justify-between">
            <span>Low-ticket responds to instant WhatsApp links</span>
            <span className="text-secondary font-mono text-[10px]">Enterprise requires manual review</span>
          </div>
        </div>
      </div>

      {/* Footer System Line */}
      <div className="flex items-center justify-between pt-2 text-[11px] text-muted border-t border-hairline">
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          <span>Powered by AG Charts Community v14 · Embedded Analytics Engine</span>
        </div>
        <div>Aggregated over {cases.length} live and sandbox recovery events</div>
      </div>
    </div>
  );
};
