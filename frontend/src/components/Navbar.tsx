import Link from "next/link";

export default function Navbar() {
  return (
    <header className="sticky top-0 z-20 border-b border-line/80 bg-ink/80 backdrop-blur">
      <nav className="mx-auto flex max-w-7xl items-center justify-between px-5 py-3.5 sm:px-6">
        <Link href="/" className="group flex items-center gap-2.5">
          {/* gauge-mark monogram */}
          <span className="grid h-8 w-8 place-items-center rounded-full border border-cyan/50 bg-panel">
            <span className="h-2.5 w-2.5 rounded-full bg-cyan shadow-[0_0_8px_var(--cyan)]" />
          </span>
          <span className="font-display text-lg font-extrabold tracking-tight text-lume">
            AUTO<span className="text-cyan">·</span>AI
          </span>
        </Link>

        <div className="flex items-center gap-1 font-mono text-xs uppercase tracking-widest">
          <NavLink href="/">Search</NavLink>
          <NavLink href="/browse">Browse</NavLink>
          <span className="ml-3 hidden items-center gap-1.5 text-haze sm:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-go shadow-[0_0_6px_var(--go)]" />
            Online
          </span>
        </div>
      </nav>
    </header>
  );
}

function NavLink({ href, children }: { href: string; children: string }) {
  return (
    <Link
      href={href}
      className="rounded px-2.5 py-1.5 text-haze transition hover:bg-panel hover:text-lume"
    >
      {children}
    </Link>
  );
}
