/** Browser mic + speaker for PC demo; RAG still runs on UNO Q via POST /ask. */

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

export function listenOnce(): Promise<string> {
  const Ctor = speechRecognitionCtor();
  if (!Ctor) {
    return Promise.reject(
      new Error("Speech recognition is not supported in this browser (try Chrome)."),
    );
  }

  return new Promise((resolve, reject) => {
    const recognition = new Ctor();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    let settled = false;
    const finish = (fn: () => void) => {
      if (settled) return;
      settled = true;
      fn();
    };

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const transcript = event.results[0]?.[0]?.transcript?.trim() ?? "";
      if (transcript) {
        finish(() => resolve(transcript));
      }
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
      finish(() => reject(new Error(event.error || "Speech recognition failed")));
    };

    recognition.onend = () => {
      if (!settled) {
        finish(() => reject(new Error("No speech heard. Try again.")));
      }
    };

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
