import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { SendIcon } from "./icons";

export function Composer({
  onSend,
  disabled,
  busy,
  placeholder,
}: {
  onSend: (t: string) => void;
  disabled: boolean;
  busy: boolean;
  placeholder: string;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  useEffect(() => {
    if (!disabled) ref.current?.focus();
  }, [disabled]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (disabled || !text.trim()) return;
    onSend(text);
    setText("");
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form
      onSubmit={submit}
      className="mx-auto w-full max-w-4xl px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 sm:px-4"
    >
      <div className="card flex items-end gap-2 p-1.5 pl-4 transition focus-within:border-accent/60 focus-within:shadow-[0_0_0_3px_rgb(var(--accent)/0.12)]">
        <textarea
          ref={ref}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          disabled={disabled}
          placeholder={placeholder}
          aria-label="Message AutoMind"
          className="max-h-[180px] min-h-[24px] flex-1 resize-none bg-transparent py-2 text-[15px] text-fg placeholder:text-muted/70 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={disabled || !text.trim()}
          aria-label="Send"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-white transition hover:bg-orange-500 disabled:cursor-not-allowed disabled:bg-panel2 disabled:text-muted"
        >
          {busy ? (
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
          ) : (
            <SendIcon />
          )}
        </button>
      </div>
      <p className="mt-1.5 hidden text-center text-[10px] text-muted/70 sm:block">
        Enter to send · Shift+Enter for a new line · Simulated and assumed
        values are labelled
      </p>
    </form>
  );
}
