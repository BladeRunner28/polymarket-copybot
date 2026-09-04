import Link from "next/link";
import { notFound } from "next/navigation";
import { readFileSync, statSync } from "fs";
import { join } from "path";

export const dynamic = "force-dynamic";

const DRAFTS_DIR = join(process.cwd(), "drafts");

function titleOf(name: string): string {
  return name
    .replace(/\.md$/i, "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function DraftDetail({ params }: { params: { slug: string } }) {
  const slug = params.slug;
  // Path-traversal guard: drafts are plain filenames only.
  if (!/^[A-Za-z0-9._-]{1,120}$/.test(slug)) notFound();

  let content: string;
  let mtime: number;
  try {
    const file = join(DRAFTS_DIR, `${slug}.md`);
    content = readFileSync(file, "utf8");
    mtime = statSync(file).mtimeMs;
  } catch {
    notFound();
  }

  const lines = content.split("\n").length;
  const kb = Math.max(1, Math.round(content.length / 1024));

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h1 className="text-lg font-bold">{titleOf(slug)}</h1>
        <Link href="/drafts" className="text-xs text-accent hover:text-ink transition-colors">
          ← All deliverables
        </Link>
      </div>
      <div className="text-xs text-dim font-mono">
        {slug}.md · {lines} lines · {kb} KB · modified{" "}
        {new Date(mtime).toISOString().slice(0, 16).replace("T", " ")}
      </div>
      <article className="bg-panel border border-edge rounded-xl p-5">
        <pre className="whitespace-pre-wrap font-mono text-[13px] leading-relaxed text-ink/90">
          {content}
        </pre>
      </article>
    </div>
  );
}
