"use client";

import { DitheringShader } from "@/components/ui/dithering-shader";

/**
 * "AI is thinking" indicator: a dithered sphere shader rendered in the
 * Etornie brand blue (#2520FE), clipped to a circle. Used in the EtornieGPT
 * chat while an assistant response is still being generated.
 */
export default function ThinkingOrb({ label = "Thinking…" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2.5" role="status">
      <span className="relative block h-12 w-12 shrink-0 overflow-hidden rounded-full">
        <DitheringShader
          shape="sphere"
          type="random"
          colorBack="#000000"
          colorFront="#2520FE"
          pxSize={2}
          speed={1.5}
          width={48}
          height={48}
        />
      </span>
      <span className="text-sm italic text-[color:var(--color-muted)]">
        {label}
      </span>
      <span className="sr-only">The assistant is thinking</span>
    </span>
  );
}
