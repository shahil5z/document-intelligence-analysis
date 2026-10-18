export function Logo({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
      <rect width="32" height="32" rx="8" fill="#4f46e5" />
      <path d="M10 8h8l5 5v11H10z" fill="#fff" fillOpacity="0.95" />
      <path d="M18 8v5h5" fill="#c7d2fe" />
      <circle cx="16.5" cy="18.5" r="3" fill="none" stroke="#4f46e5" strokeWidth="1.8" />
      <path d="m18.8 20.8 2.2 2.2" stroke="#4f46e5" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
