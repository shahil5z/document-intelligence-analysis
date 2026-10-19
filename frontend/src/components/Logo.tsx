import Image from "next/image";

import { PRODUCT_NAME } from "@/lib/brand";

/** The DIA mark (480x253 source). Decorative when a text wordmark sits next to it. */
export function LogoMark({ height = 28, decorative = true }: { height?: number; decorative?: boolean }) {
  const width = Math.round((height * 480) / 253);
  return (
    <Image
      src="/brand/mark.webp"
      width={width}
      height={height}
      alt={decorative ? "" : PRODUCT_NAME}
      priority
      className="shrink-0 select-none"
    />
  );
}

/** Mark + live text wordmark (crisp at any size, follows the theme). */
export function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5" aria-label={PRODUCT_NAME}>
      <LogoMark height={compact ? 22 : 26} />
      <span className="flex flex-col leading-none" aria-hidden="true">
        <span className="text-[13px] font-semibold tracking-tight text-fg">Document Intelligence</span>
        <span className="mt-0.5 text-[12px] font-semibold tracking-tight text-gradient">&amp; Analysis</span>
      </span>
    </span>
  );
}

/** Full logo with wordmark: one image per theme (CSS switches, no hydration mismatch). */
export function FullLogo({ width = 320, className = "" }: { width?: number; className?: string }) {
  const height = Math.round((width * 456) / 720);
  return (
    <span className={`inline-block ${className}`}>
      <Image src="/brand/logo-light.webp" width={width} height={height} alt={PRODUCT_NAME} priority className="block dark:hidden" />
      <Image src="/brand/logo-dark.webp" width={width} height={height} alt={PRODUCT_NAME} priority className="hidden dark:block" />
    </span>
  );
}
