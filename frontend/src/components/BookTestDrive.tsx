"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createBooking } from "@/lib/api";
import type { BookingResponse } from "@/lib/types";

type Status = "idle" | "submitting" | "done";

// "YYYY-MM-DDTHH:MM" in local time, for datetime-local value/min.
function localInputValue(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

export default function BookTestDrive({
  vin,
  make,
  model,
  year,
}: {
  vin: string;
  make: string;
  model: string;
  year: number;
}) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [booking, setBooking] = useState<BookingResponse | null>(null);
  const [minDT, setMinDT] = useState("");

  const firstFieldRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  // Default the picker to ~tomorrow 10:00, min = one hour out.
  useEffect(() => {
    if (!open) return;
    const min = new Date(Date.now() + 60 * 60 * 1000);
    setMinDT(localInputValue(min));
  }, [open]);

  // Focus first field on open; lock scroll; ESC to close; restore focus.
  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    firstFieldRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function close() {
    setOpen(false);
    setError(null);
    setStatus("idle");
    setBooking(null);
    triggerRef.current?.focus();
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    // datetime-local gives local wall time with no offset; send the absolute
    // instant (UTC ISO) so the server doesn't read it as UTC wall time.
    const when = String(form.get("when") || "");
    const whenDate = new Date(when);
    setStatus("submitting");
    setError(null);
    try {
      const res = await createBooking({
        vehicle_vin: vin,
        customer_name: String(form.get("name") || ""),
        customer_email: String(form.get("email") || ""),
        customer_phone: String(form.get("phone") || ""),
        appointment_datetime: isNaN(whenDate.getTime()) ? when : whenDate.toISOString(),
        notes: String(form.get("notes") || "") || undefined,
      });
      setBooking(res);
      setStatus("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Booking failed");
      setStatus("idle");
    }
  }

  return (
    <>
      <button
        ref={triggerRef}
        onClick={() => setOpen(true)}
        className="mt-1 rounded-lg border border-cyan/50 bg-cyan/15 px-5 py-3 font-mono text-sm font-semibold uppercase tracking-widest text-cyan transition hover:bg-cyan/25"
      >
        Book a test drive
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center bg-ink/80 p-4 backdrop-blur-sm sm:items-center"
          onClick={close}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md overflow-hidden rounded-2xl border border-line bg-panel shadow-[0_20px_80px_-20px_rgba(0,0,0,0.8)]"
          >
            {/* header */}
            <div className="flex items-start justify-between border-b border-line px-6 py-4">
              <div>
                <p id={titleId} className="font-mono text-[11px] uppercase tracking-widest text-cyan">
                  {status === "done" ? "Booking confirmed" : "Book a test drive"}
                </p>
                <p className="mt-0.5 font-display text-lg font-bold text-lume">
                  {year} {make} {model}
                </p>
              </div>
              <button
                onClick={close}
                aria-label="Close"
                className="rounded-md px-2 py-1 font-mono text-haze transition hover:bg-panel2 hover:text-lume"
              >
                ✕
              </button>
            </div>

            {status === "done" && booking ? (
              <Confirmation booking={booking} onClose={close} />
            ) : (
              <form onSubmit={onSubmit} className="flex flex-col gap-4 px-6 py-5">
                <Field label="Full name">
                  <input
                    ref={firstFieldRef}
                    name="name"
                    required
                    minLength={2}
                    autoComplete="name"
                    className={inputCls}
                    placeholder="Erel Edry"
                  />
                </Field>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Field label="Email">
                    <input
                      name="email"
                      type="email"
                      required
                      autoComplete="email"
                      className={inputCls}
                      placeholder="you@email.com"
                    />
                  </Field>
                  <Field label="Phone">
                    <input
                      name="phone"
                      type="tel"
                      required
                      minLength={7}
                      autoComplete="tel"
                      className={inputCls}
                      placeholder="+353 87 123 4567"
                    />
                  </Field>
                </div>
                <Field label="Preferred date & time">
                  <input
                    name="when"
                    type="datetime-local"
                    required
                    min={minDT}
                    defaultValue={minDT}
                    className={`${inputCls} [color-scheme:dark]`}
                  />
                </Field>
                <Field label="Notes (optional)">
                  <textarea
                    name="notes"
                    rows={2}
                    maxLength={500}
                    className={`${inputCls} resize-none`}
                    placeholder="Anything we should know?"
                  />
                </Field>

                {error && (
                  <p className="rounded-md border border-amber/40 bg-amber/10 px-3 py-2 font-mono text-xs text-amber">
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={status === "submitting"}
                  className="mt-1 rounded-lg border border-cyan/50 bg-cyan/15 px-5 py-3 font-mono text-sm font-semibold uppercase tracking-widest text-cyan transition hover:bg-cyan/25 disabled:opacity-60"
                >
                  {status === "submitting" ? "Requesting…" : "Request test drive"}
                </button>
                <p className="text-center font-mono text-[11px] text-haze">
                  No payment — a sales advisor confirms by email.
                </p>
              </form>
            )}
          </div>
        </div>
      )}
    </>
  );
}

const inputCls =
  "w-full rounded-md border border-line bg-panel2 px-3 py-2 text-sm text-lume outline-none transition placeholder:text-haze/60 focus:border-cyan/60 focus:shadow-[0_0_0_3px_rgba(70,217,230,0.12)]";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="font-mono text-[11px] uppercase tracking-widest text-haze">
        {label}
      </span>
      {children}
    </label>
  );
}

function Confirmation({
  booking,
  onClose,
}: {
  booking: BookingResponse;
  onClose: () => void;
}) {
  // Pin to en-IE so dates read consistently with the €/en-IE price formatting,
  // regardless of the visitor's system locale.
  const when = new Date(booking.appointment_datetime).toLocaleString("en-IE", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <div className="flex flex-col gap-4 px-6 py-6">
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-cyan/50 bg-cyan/10 text-lg text-cyan shadow-[0_0_12px_rgba(70,217,230,0.35)]">
          ✓
        </span>
        <p className="text-sm leading-relaxed text-haze">
          Test drive requested for{" "}
          <span className="text-lume">{booking.customer_name}</span>. We&apos;ll
          confirm by email.
        </p>
      </div>

      <dl className="flex flex-col gap-2 rounded-lg border border-line bg-panel2 px-4 py-3 font-mono text-xs">
        <Row label="When" value={when} />
        <Row label="Status" value={booking.status} accent />
        <Row label="Ref" value={booking.id.slice(0, 8).toUpperCase()} />
      </dl>

      <button
        onClick={onClose}
        className="rounded-lg border border-line px-5 py-2.5 font-mono text-sm uppercase tracking-widest text-haze transition hover:border-cyan/40 hover:text-lume"
      >
        Done
      </button>
    </div>
  );
}

function Row({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="uppercase tracking-widest text-haze">{label}</dt>
      <dd className={accent ? "uppercase tracking-wide text-cyan" : "text-lume"}>
        {value}
      </dd>
    </div>
  );
}
