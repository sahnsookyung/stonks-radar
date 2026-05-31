import { Info } from "lucide-react";
import { useId, useState } from "react";
import { useLocale } from "../lib/locale";
import { portfolioTerms } from "../lib/portfolioTerms";

export function TermTooltip({ termKey, className = "" }: { termKey: string; className?: string }) {
  const term = portfolioTerms[termKey];
  const locale = useLocale();
  const tooltipId = useId();
  const [open, setOpen] = useState(false);
  if (!term) return null;
  const description = term.long ? `${term.short} ${term.long}` : term.short;
  return (
    <span className={`group relative inline-flex align-middle ${className}`}>
      <button
        type="button"
        className="focus-ring -my-2 inline-grid h-11 w-11 place-items-center rounded-full text-muted hover:bg-panelAlt hover:text-accent"
        aria-label={`${term.label}: ${description}`}
        aria-describedby={tooltipId}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        title={`${term.label}: ${description}`}
      >
        <Info className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      <span
        id={tooltipId}
        role="tooltip"
        className={`absolute left-1/2 top-10 z-30 w-64 max-w-[calc(100vw-2rem)] -translate-x-1/2 rounded-md border border-line bg-panel p-3 text-left text-xs leading-5 text-muted shadow-insetLine group-hover:block group-focus-within:block ${open ? "block" : "hidden"}`}
      >
        <span className="block font-semibold text-ink">{term.label}</span>
        <span className="safe-text mt-1 block">{term.short}</span>
        {term.long ? <span className="safe-text mt-1 block">{term.long}</span> : null}
        <a className="focus-ring mt-2 inline-flex min-h-8 items-center rounded text-accent hover:text-sky" href={`/${locale}/portfolio/glossary#term-${termKey}`}>
          Learn more: {term.category.replace("_", " ")}
        </a>
      </span>
    </span>
  );
}
