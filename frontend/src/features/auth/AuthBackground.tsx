/**
 * Animated background for auth pages — floating gradient blobs.
 * Pure CSS animation, no JS timers or requestAnimationFrame.
 * Respects prefers-reduced-motion via CSS (animations disabled).
 */
export function AuthBackground() {
  return (
    <div
      className="fixed inset-0 overflow-hidden pointer-events-none"
      aria-hidden="true"
    >
      {/* Primary blob — top-left */}
      <div
        className="auth-blob -top-40 -left-40 w-[320px] h-[320px] bg-[rgba(0,113,227,0.1)] animate-float"
      />
      {/* Secondary blob — right, with purple tint */}
      <div
        className="auth-blob top-1/3 -right-20 w-[384px] h-[384px] bg-[rgba(88,86,214,0.08)] animate-float-delayed"
        style={{ animationDelay: '2s' }}
      />
      {/* Tertiary blob — bottom-center */}
      <div
        className="auth-blob -bottom-24 left-1/3 w-[288px] h-[288px] bg-[rgba(0,113,227,0.06)] animate-float-slow"
        style={{ animationDelay: '4s' }}
      />
    </div>
  );
}
