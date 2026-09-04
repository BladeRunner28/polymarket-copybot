import Link from "next/link";
import { readdirSync, statSync, readFileSync } from "fs";
import { join } from "path";
import { Card, Empty } from "@/components/ui";

export const dynamic = "force-dynamic";

const DRAFTS_DIR = join(process.cwd(), "drafts");

function fmtDate(ms: number): string {
  const d = new Date(ms);
  return d.toISOString().slice(0, 10) + " " + d.toISOString().slice(11, 16);
}

function titleOf(name: string): string {
  // "octagon-audit.md" -> "Octagon audit"
  return name
    .replace(/\.md$/i, "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function loadDrafts(): { slug: string; name: string; title: string; size: number; mtime: number }[] {
  try {
    return readdirSync(DRAFTS_DIR)
      .filter((f) => f.endsWith(".md"))
      .map((f) => {
        const st = statSync(join(DRAFTS_DIR, f));
        return { slug: f.replace(/\.md$/i, ""), name: f, title: titleOf(f), size: st.size, mtime: st.mtimeMs };
      })
      .sort((a, b) => b.mtime - a.mtime);
  } catch {
    return [];
  }
}

export default function DraftsIndex() {
  const drafts = loadDrafts();
  if (drafts.length === 0) {
    return <Empty message="drafts/ is empty or unreadable." />;
  }
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-bold mb-1">Deliverables — audits, design notes &amp; drafts</h1>
        <p className="text-sm text-dim">
          Working documents produced by the research pipeline (sibling of the draft files in the repo
          root). Newest first · {drafts.length} docs
        </p>
      </div>
      <Card>
        <ul className="divide-y divide-edge">
          {drafts.map((d) => (
            <li key={d.slug}>
              <Link
                href={`/drafts/${d.slug}`}
                className="flex items-center justify-between gap-3 py-2.5 group"
              >
                <span className="flex items-center gap-2 min-w-0">
                  <span className="text-accent/70 group-hover:text-accent shrink-0">📄</span>
                  <span className="text-sm text-ink group-hover:text-accent truncate">{d.title}</span>
                </span>
                <span className="text-xs text-dim font-mono shrink-0">
                  {fmtDate(d.mtime)} · {Math.max(1, Math.round(d.size / 1024))} KB
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
