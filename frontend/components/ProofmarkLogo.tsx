/**
 * ProofmarkLogo — verified-delivery mark: a checkmark inside a hexagon.
 * Hexagons read as technical infrastructure (honeycomb, molecular, network
 * nodes); the check inside is the proof of delivery. Replaces the retired
 * shield logo. Colors come from the current design tokens.
 */
export function ProofmarkLogo({ size = 32 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="brand-logo"
      aria-label="Proofmark"
    >
      {/* Hexagon — network node, infrastructure */}
      <path
        d="M16 3 L27 9.5 L27 22.5 L16 29 L5 22.5 L5 9.5 Z"
        stroke="var(--proof)"
        strokeWidth="1.5"
        strokeLinejoin="round"
        fill="none"
        opacity="0.7"
      />
      {/* Inner hexagon — the verified layer */}
      <path
        d="M16 8 L23 12 L23 20 L16 24 L9 20 L9 12 Z"
        stroke="var(--proof)"
        strokeWidth="1"
        strokeLinejoin="round"
        fill="var(--proof-bg)"
        opacity="0.5"
      />
      {/* Checkmark — the proof */}
      <path
        d="M11.5 16 L14.5 19 L20.5 13"
        stroke="var(--proof-bright)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
