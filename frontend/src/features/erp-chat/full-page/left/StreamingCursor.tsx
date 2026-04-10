export default function StreamingCursor() {
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block',
        width: 2,
        height: '1em',
        background: 'var(--chat-accent)',
        borderRadius: 1,
        verticalAlign: 'text-bottom',
        marginLeft: 2,
        animation: 'cursorBlink 1s steps(1) infinite',
      }}
    />
  );
}
