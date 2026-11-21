/* Local endpoint timing only: this is not a speech recognizer. */
class BellaVoiceEndpoint {
  constructor() { this.reset(); }
  reset() { this.lastAt = null; this.voicedMs = 0; this.silenceAt = null; this.candidateSilenceAt = null; }
  update(rms, now) {
    const dt = this.lastAt === null ? 0 : Math.min(100, Math.max(0, now - this.lastAt));
    this.lastAt = now;
    // Hysteresis protects quiet word endings after speech has begun.
    const threshold = this.voicedMs >= 160 ? 0.010 : 0.015;
    if (rms >= threshold) {
      this.voicedMs += dt;
      this.candidateSilenceAt = null;
      this.silenceAt = null;
      return false;
    }
    if (this.voicedMs < 160) {
      this.candidateSilenceAt ??= now;
      if (now - this.candidateSilenceAt >= 180) this.voicedMs = 0;
      return false;
    }
    if (this.silenceAt === null) this.silenceAt = now;
    const holdMs = this.voicedMs <= 2000 ? 800 : 1100;
    return now - this.silenceAt >= holdMs;
  }
}
if (typeof module !== 'undefined') module.exports = BellaVoiceEndpoint;
