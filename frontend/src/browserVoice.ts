/** Browser mic + speaker for PC demo; RAG still runs on UNO Q via POST /ask. */

import { VOICE_RECORD_SECONDS } from "./voiceConfig";

export function browserVoiceSupported(): boolean {
  if (typeof window === "undefined") return false;
  const hasRecognition =
    "SpeechRecognition" in window || "webkitSpeechRecognition" in window;
  return hasRecognition && "speechSynthesis" in window;
}

function speechRecognitionCtor(): SpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
}

export function listenOnce(seconds = VOICE_RECORD_SECONDS): Promise<string> {
  const Ctor = speechRecognitionCtor();
  if (!Ctor) {
    return Promise.reject(
      new Error("Speech recognition is not supported in this browser (try Chrome)."),
    );
  }

  return new Promise((resolve, reject) => {
    const recognition = new Ctor();
    recognition.lang = "en-US";
    recognition.interimResults = true;
    recognition.continuous = true;
    recognition.maxAlternatives = 1;

    let settled = false;
    let transcript = "";
    let timer: number | undefined;

    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      if (timer !== undefined) {
        window.clearTimeout(timer);
      }
      fn();
    };

    const latestTranscript = (event: SpeechRecognitionEvent) => {
      const parts: string[] = [];
      for (let i = 0; i < event.results.length; i += 1) {
        const piece = event.results[i]?.[0]?.transcript?.trim() ?? "";
        if (piece) parts.push(piece);
      }
      return parts.join(" ").trim();
    };

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const heard = latestTranscript(event);
      if (heard) transcript = heard;
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === "no-speech") {
        finish(() => reject(new Error("No speech heard. Try again and speak clearly.")));
        return;
      }
      if (event.error === "network") {
        finish(() =>
          reject(
            new Error(
              "Browser speech needs internet (Chrome uses Google). " +
                "Use hardware voice: set MOORCHEH_VOICE_PROXY_URL and run " +
                "moorcheh-edge voice serve on the UNO Q.",
            ),
          ),
        );
        return;
      }
      if (event.error === "not-allowed") {
        finish(() => reject(new Error("Microphone permission denied. Allow mic access in the browser.")));
        return;
      }
      if (event.error === "aborted") {
        if (transcript.trim()) {
          finish(() => resolve(transcript.trim()));
        } else {
          finish(() => reject(new Error("No speech heard. Try again.")));
        }
        return;
      }
      finish(() => reject(new Error(event.error || "Speech recognition failed")));
    };

    recognition.onend = () => {
      if (!settled) {
        const heard = transcript.trim();
        finish(() =>
          heard
            ? resolve(heard)
            : reject(new Error("No speech heard. Try again and speak clearly.")),
        );
      }
    };

    timer = window.setTimeout(() => {
      try {
        recognition.stop();
      } catch {
        /* already ended */
      }
    }, seconds * 1000);

    try {
      recognition.start();
    } catch (err) {
      finish(() =>
        reject(err instanceof Error ? err : new Error("Could not start microphone")),
      );
    }
  });
}

export function speakAnswer(text: string): Promise<void> {
  const cleaned = text.trim();
  if (!cleaned) {
    return Promise.reject(new Error("Nothing to speak."));
  }
  if (typeof window === "undefined" || !window.speechSynthesis) {
    return Promise.reject(new Error("Speech synthesis is not supported in this browser."));
  }

  return new Promise((resolve, reject) => {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(cleaned);
    utterance.lang = "en-US";
    utterance.onend = () => resolve();
    utterance.onerror = () => reject(new Error("Could not play spoken answer."));
    window.speechSynthesis.speak(utterance);
  });
}

/** Queue browser TTS sentence-by-sentence while tokens stream in. */
export function createStreamingSpeaker() {
  let buffer = "";
  let chain: Promise<void> = Promise.resolve();

  const enqueue = (text: string) => {
    const cleaned = text.trim();
    if (!cleaned) return;
    chain = chain
      .then(() => speakAnswer(cleaned))
      .catch(() => undefined);
  };

  return {
    push(delta: string) {
      buffer += delta;
      while (true) {
        const match = buffer.match(/^([\s\S]*?[.!?])(?:\s+|$)/);
        if (!match) break;
        const sentence = match[1].trim();
        buffer = buffer.slice(match[0].length);
        if (sentence) enqueue(sentence);
      }
    },
    flush() {
      const rest = buffer.trim();
      buffer = "";
      if (rest) enqueue(rest);
    },
    waitUntilIdle(): Promise<void> {
      return chain;
    },
  };
}
