"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export interface NavItem {
  href: string;
  label: string;
  external?: boolean;
}

export function TopNav({ items }: { items: NavItem[] }) {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1 text-sm flex-wrap">
      {items.map((n) => {
        const active = !n.external && (pathname === n.href || (n.href !== "/" && pathname.startsWith(n.href)));
        if (n.external) {
          return (
            <a
              key={n.href}
              href={n.href}
              className="px-3 py-1.5 rounded-md text-accent hover:text-ink hover:bg-edge/60 transition-colors"
            >
              {n.label}
            </a>
          );
        }
        return (
          <Link
            key={n.href}
            href={n.href}
            className={`px-3 py-1.5 rounded-md transition-colors ${
              active
                ? "bg-accent/15 text-accent border border-accent/25"
                : "text-dim hover:text-ink hover:bg-edge/60 border border-transparent"
            }`}
          >
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
}
