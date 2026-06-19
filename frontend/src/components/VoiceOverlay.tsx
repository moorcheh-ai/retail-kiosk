type Props = {
  phase: "listening" | "transcribing";
  statusLine: string;
};

export default function VoiceOverlay({ phase, statusLine }: Props) {
  return (
    <div className="voice-overlay" role="dialog" aria-label="Voice recording">
      <div className="voice-overlay-backdrop" aria-hidden />
      <div className="voice-overlay-center">
        <div className="voice-orb" data-phase={phase}>
          <span className="voice-orb-ring voice-orb-ring--1" />
          <span className="voice-orb-ring voice-orb-ring--2" />
          <span className="voice-orb-ring voice-orb-ring--3" />
          <span className="voice-orb-core">
            <svg viewBox="0 0 24 24" width="32" height="32" aria-hidden>
              <path
                fill="currentColor"
                d="M12 14a3 3 0 0 0 3-3V5a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2Z"
              />
            </svg>
          </span>
        </div>
        <p className="voice-overlay-title">
          {phase === "listening" ? "Listening…" : "Transcribing…"}
        </p>
        <p className="voice-overlay-sub">{statusLine}</p>
      </div>
    </div>
  );
}
