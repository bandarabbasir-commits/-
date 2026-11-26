import React from 'react';

export const SahelLogo: React.FC<{ size?: number; showWordmark?: boolean }> = ({
  size = 34,
  showWordmark = true,
}) => {
  return (
    <div className="inline-flex items-center gap-2.5 select-none">
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        fill="none"
        aria-hidden="true"
        className="shrink-0"
      >
        <rect width="64" height="64" rx="16" fill="#0F766E" />
        <path d="M12 24H52" stroke="#99F6E4" strokeWidth="2.5" strokeLinecap="round" opacity="0.65" />
        <circle cx="44" cy="18" r="5" fill="#FDE68A" />
        <path
          d="M10 35C16 29 22 29 28 35C34 41 40 41 46 35C49 32 52 31 54 32"
          stroke="#FFFFFF"
          strokeWidth="3.5"
          strokeLinecap="round"
        />
        <path
          d="M10 45C16 39 22 39 28 45C34 51 40 51 46 45C49 42 52 41 54 42"
          stroke="#5EEAD4"
          strokeWidth="3.5"
          strokeLinecap="round"
        />
      </svg>
      {showWordmark && (
        <span className="font-bold text-base tracking-tight text-[var(--hb-text)] whitespace-nowrap">
          هرمزگان بیدار
        </span>
      )}
    </div>
  );
};
