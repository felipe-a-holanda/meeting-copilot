// Assigns consistent colors to speaker IDs.
// Each new speaker gets the next color from the palette; the same speaker always gets the same color.

const SPEAKER_COLORS = [
  '#60a5fa', // blue-400
  '#34d399', // emerald-400
  '#f472b6', // pink-400
  '#fbbf24', // amber-400
  '#a78bfa', // violet-400
  '#fb923c', // orange-400
  '#2dd4bf', // teal-400
  '#f87171', // red-400
  '#38bdf8', // sky-400
  '#c084fc', // purple-400
  '#4ade80', // green-400
  '#facc15', // yellow-400
];

const speakerColorMap = new Map<string, string>();

export function getSpeakerColor(speaker: string): string {
  const existing = speakerColorMap.get(speaker);
  if (existing) return existing;

  const color = SPEAKER_COLORS[speakerColorMap.size % SPEAKER_COLORS.length];
  speakerColorMap.set(speaker, color);
  return color;
}

export function resetSpeakerColors(): void {
  speakerColorMap.clear();
}
