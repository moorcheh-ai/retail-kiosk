import { useEffect, useState } from "react";

export function useRotatingPhrase(phrases: string[], active: boolean, intervalMs = 1800) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!active || phrases.length === 0) {
      setIndex(0);
      return;
    }
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % phrases.length);
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [active, phrases, intervalMs]);

  return phrases[index] ?? phrases[0] ?? "";
}
