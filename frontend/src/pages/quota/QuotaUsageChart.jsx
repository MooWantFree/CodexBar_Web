import { useEffect, useMemo, useRef, useState } from "react";
import { formatDateTime } from "../../lib/format";
import { t } from "../../lib/i18n";
import { EmptyState } from "../../components/Shared";
import { percent, valueTime } from "./QuotaShared";

export function QuotaUsageChart({ observations }) {
  const plotRef = useRef(null);
  const [width, setWidth] = useState(800);
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    const plot = plotRef.current;
    if (!plot) return;
    const resize = () => setWidth(Math.max(280, plot.getBoundingClientRect().width || 800));
    resize();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(plot);
    return () => observer?.disconnect();
  }, []);

  const readings = useMemo(() => observations.map(row => ({ ...row, time: Date.parse(row.fetched_at), used: Number(row.used_percent) }))
    .filter(row => Number.isFinite(row.time) && row.used_percent != null && row.used_percent !== "" && Number.isFinite(row.used))
    .sort((a, b) => a.time - b.time), [observations]);
  const height = 280, left = 48, right = width - 16, top = 16, bottom = height - 48;
  const first = readings[0], last = readings.at(-1);
  const minimum = readings.reduce((value, row) => Math.min(value, Math.floor(row.used / 25) * 25), 0);
  const maximum = readings.reduce((value, row) => Math.max(value, Math.ceil(row.used / 25) * 25), 100);
  const x = time => first.time === last.time ? (left + right) / 2 : left + (time - first.time) / (last.time - first.time) * (right - left);
  const y = used => bottom - (used - minimum) / (maximum - minimum) * (bottom - top);
  const activeIndex = selected == null ? readings.length - 1 : Math.min(selected, readings.length - 1);
  const active = readings[activeIndex];
  const tickCount = first?.time === last?.time ? 1 : width < 520 ? 3 : 5;
  const timeTicks = first ? Array.from({ length: tickCount }, (_, index) => first.time + (last.time - first.time) * index / Math.max(1, tickCount - 1)) : [];

  function selectAtPointer(event) {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (!bounds.width || !first) return;
    const pointer = (event.clientX - bounds.left) / bounds.width * width;
    const time = first.time + (pointer - left) / (right - left) * (last.time - first.time);
    let nearest = 0;
    for (let index = 1; index < readings.length; index++) {
      if (Math.abs(readings[index].time - time) <= Math.abs(readings[nearest].time - time)) nearest = index;
    }
    setSelected(nearest);
  }
  function selectWithKeyboard(event) {
    let next;
    if (event.key === "ArrowLeft") next = Math.max(0, activeIndex - 1);
    else if (event.key === "ArrowRight") next = Math.min(readings.length - 1, activeIndex + 1);
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = readings.length - 1;
    else return;
    event.preventDefault();
    setSelected(next);
  }

  return <figure className="quota-usage-chart">
    <figcaption><span>{t("Used quota")}</span>{active && <output aria-live="polite" aria-atomic="true"><strong>{percent(active.used)}</strong><time dateTime={active.fetched_at}>{valueTime(active.fetched_at)}</time></output>}</figcaption>
    <div ref={plotRef} className="quota-usage-plot" role="group" aria-label={t("Quota usage over time")} tabIndex={active ? 0 : undefined} onKeyDown={selectWithKeyboard}>
      {active ? <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t("Quota usage over time")} onPointerMove={selectAtPointer} onPointerDown={selectAtPointer} onPointerLeave={() => setSelected(null)}>
        {Array.from({ length: 5 }, (_, index) => {
          const used = minimum + (maximum - minimum) * index / 4;
          return <g key={used}><line className="quota-usage-grid" x1={left} x2={right} y1={y(used)} y2={y(used)} /><text className="quota-usage-axis" x={left - 10} y={y(used)} dy=".35em" textAnchor="end">{percent(used)}</text></g>;
        })}
        {timeTicks.map((time, index) => <text className="quota-usage-axis" key={index} x={x(time)} y={bottom + 20} textAnchor={tickCount === 1 ? "middle" : index === 0 ? "start" : index === tickCount - 1 ? "end" : "middle"}>
          <tspan x={x(time)}>{formatDateTime(time, { month: "2-digit", day: "2-digit" })}</tspan><tspan x={x(time)} dy="16">{formatDateTime(time, { hour: "2-digit", minute: "2-digit" })}</tspan>
        </text>)}
        <polyline className="quota-usage-line" points={readings.map(row => `${x(row.time)},${y(row.used)}`).join(" ")} />
        {readings.length <= 80 && readings.map((row, index) => <circle className="quota-usage-point" key={index} cx={x(row.time)} cy={y(row.used)} r="3"><title>{valueTime(row.fetched_at)} · {percent(row.used)}</title></circle>)}
        <line className="quota-usage-cursor" x1={x(active.time)} x2={x(active.time)} y1={top} y2={bottom} />
        <circle className="quota-usage-active" cx={x(active.time)} cy={y(active.used)} r="5" />
      </svg> : <EmptyState>{t(observations.length ? "No percentage readings are available." : "No snapshots are available for this cycle.")}</EmptyState>}
    </div>
  </figure>;
}
