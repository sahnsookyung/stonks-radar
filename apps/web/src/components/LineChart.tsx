export function LineChart({
  points,
  label
}: {
  points: { date: string; value: number }[];
  label: string;
}) {
  if (points.length < 2) return null;

  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 320;
  const height = 112;
  const padding = 12;
  const usableWidth = width - padding * 2;
  const usableHeight = height - padding * 2;
  const coords = points.map((point, index) => {
    const x = padding + (index / (points.length - 1)) * usableWidth;
    const y = padding + (1 - (point.value - min) / range) * usableHeight;
    return [x, y] as const;
  });
  const linePath = coords.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${coords[coords.length - 1][0].toFixed(1)} ${height - padding} L${coords[0][0].toFixed(1)} ${height - padding} Z`;

  return (
    <svg
      className="mt-3 h-28 w-full"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label}
      preserveAspectRatio="none"
    >
      <path d={areaPath} fill="rgba(103, 216, 239, 0.12)" />
      <path d={linePath} fill="none" stroke="#67d8ef" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" />
      <line x1={padding} x2={width - padding} y1={height - padding} y2={height - padding} stroke="rgba(147, 163, 183, 0.18)" />
    </svg>
  );
}
