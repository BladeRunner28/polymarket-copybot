import { readFileSync } from "fs";
import { join } from "path";
import { Card, Empty } from "@/components/ui";

export const dynamic = "force-dynamic";

interface RoadmapCard {
  id: string;
  title: string;
  column: string;
  effort?: string;
  dates?: string;
  gate?: string;
  note?: string;
  tags?: string[];
}

interface Roadmap {
  columns: string[];
  cards: RoadmapCard[];
}

function loadRoadmap(): Roadmap | null {
  try {
    const raw = JSON.parse(
      readFileSync(join(process.cwd(), "data", "roadmap.json"), "utf8")
    ) as Roadmap;
    if (!Array.isArray(raw.columns) || !Array.isArray(raw.cards)) return null;
    return raw;
  } catch {
    return null;
  }
}

const TAG_STYLES: Record<string, string> = {
  shipped: "bg-pos/15 text-pos border-pos/30",
  measuring: "bg-warn/15 text-warn border-warn/30",
  review: "bg-accent/15 text-accent border-accent/30",
  blocker: "bg-neg/15 text-neg border-neg/30",
};

export default function RoadmapPage() {
  const roadmap = loadRoadmap();
  if (!roadmap) return <Empty message="data/roadmap.json missing or unreadable — nothing to board." />;

  return (
    <div>
      <h1 className="text-lg font-bold mb-1">Roadmap — implementation phases</h1>
      <p className="text-sm text-dim mb-6">
        Kanban tracking for engineering phases. Source of truth:{" "}
        <code className="text-accent">data/roadmap.json</code> — evidence and revert
        paths live in <code className="text-accent">drafts/</code> audit docs.
      </p>
      <div className="flex gap-4 items-start overflow-x-auto pb-2">
        {roadmap.columns.map((col) => {
          const cards = roadmap.cards.filter((c) => c.column === col);
          return (
            <div key={col} className="w-72 shrink-0">
              <Card>
                <div className="flex items-center justify-between mb-2">
                  <h2 className="text-sm font-semibold text-dim uppercase tracking-wide">{col}</h2>
                  <span className="text-[10px] font-mono text-dim bg-edge px-1.5 py-0.5 rounded-full">
                    {cards.length}
                  </span>
                </div>
                <div className="space-y-3">
                  {cards.length === 0 && (
                    <div className="text-xs text-dim text-center py-4 border border-dashed border-edge rounded-lg">
                      empty
                    </div>
                  )}
                  {cards.map((c) => (
                    <div key={c.id} className="border border-edge rounded-lg p-3 bg-base">
                      <div className="text-sm font-semibold leading-snug">{c.title}</div>
                      {(c.dates || c.effort) && (
                        <div className="text-xs text-dim mt-1 font-mono">
                          {c.dates}
                          {c.dates && c.effort ? " · " : ""}
                          {c.effort}
                        </div>
                      )}
                      {c.gate && (
                        <div className="text-xs text-warn mt-1.5">
                          ⛔ gate: {c.gate}
                        </div>
                      )}
                      {c.note && <div className="text-xs text-dim mt-1.5">{c.note}</div>}
                      {c.tags && c.tags.length > 0 && (
                        <div className="flex gap-1 mt-2 flex-wrap">
                          {c.tags.map((t) => (
                            <span
                              key={t}
                              className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border ${
                                TAG_STYLES[t] ?? "bg-edge text-dim border-edge"
                              }`}
                            >
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          );
        })}
      </div>
    </div>
  );
}
