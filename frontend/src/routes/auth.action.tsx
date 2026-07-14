import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { confirmPasswordReset, verifyPasswordResetCode } from "firebase/auth";
import { FirebaseError } from "firebase/app";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { toast } from "sonner";
import { auth } from "@/lib/firebase";

// D-11/D-12: the branded in-app Firebase action-code handler. The invite (and,
// later, forgot-password) mail lands here — the ActionCodeSettings continue URL
// is pinned to /auth/action by the backend (Plan 10-03, generate_set_password_link)
// so the first-run flow stays in the app's look and language instead of Firebase's
// hosted page. One route serves BOTH the invite set-password flow and the (later)
// forgot-password flow — mechanically the same Firebase `resetPassword` operation —
// so all copy is neutral ("choose your password"), never "reset".
export const Route = createFileRoute("/auth/action")({
  component: ActionPage,
});

// The verify step's outcome drives which UI we render: while verifying, on a valid
// code (show the form), or on an expired/invalid code (show the re-request message).
type VerifyState =
  | { status: "verifying" }
  | { status: "ready"; email: string }
  | { status: "invalid" }
  | { status: "unsupported" };

// Firebase enforces a minimum password strength server-side; mirror it client-side
// so the user gets an inline hint before the round-trip.
const MIN_PASSWORD_LENGTH = 6;

/** Map a Firebase error code to a friendly, localized message (auth namespace). */
function authErrorMessage(t: TFunction<"auth">, code: string): string {
  switch (code) {
    case "auth/expired-action-code":
    case "auth/invalid-action-code":
      return t("action.errors.expiredLink");
    case "auth/weak-password":
      return t("action.errors.weakPassword");
    case "auth/user-disabled":
      return t("action.errors.userDisabled");
    case "auth/user-not-found":
      return t("action.errors.userNotFound");
    default:
      return t("action.errors.generic");
  }
}

function ActionPage() {
  const navigate = useNavigate();
  const { t } = useTranslation("auth");

  // Read mode + oobCode from the URL Firebase redirected to
  // (?mode=resetPassword&oobCode=...). Guarded for SSR: window is undefined there,
  // so fall back to an empty search string until the effect runs in the browser.
  const [verify, setVerify] = useState<VerifyState>({ status: "verifying" });
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [oobCode, setOobCode] = useState<string | null>(null);

  // On mount: read the URL, then verify the action code. verifyPasswordResetCode
  // validates the code (rejecting expired/invalid ones) and returns the target
  // email — proving who the code belongs to before we render the form.
  useEffect(() => {
    let cancelled = false;

    const params = new URLSearchParams(
      typeof window !== "undefined" ? window.location.search : "",
    );
    const mode = params.get("mode");
    const code = params.get("oobCode");

    // The same handler URL can carry other Firebase modes (verifyEmail,
    // recoverEmail). We only support the password-set/reset flow here; anything
    // else gets a neutral message rather than a crash (D-12 graceful unknown mode).
    if (mode !== "resetPassword" || !code) {
      setVerify({ status: "unsupported" });
      return;
    }

    setOobCode(code);

    (async () => {
      try {
        const email = await verifyPasswordResetCode(auth, code);
        if (!cancelled) setVerify({ status: "ready", email });
      } catch (err) {
        // Expired / invalid / any verify failure → the friendly re-request message.
        if (!cancelled) setVerify({ status: "invalid" });
        const code2 = err instanceof FirebaseError ? err.code : "";
        if (code2) console.warn("[auth/action] verify failed:", code2);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFieldError(null);

    if (!oobCode) {
      setVerify({ status: "invalid" });
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setFieldError(t("action.errors.weakPassword"));
      return;
    }
    if (password !== confirmPassword) {
      setFieldError(t("action.errors.mismatch"));
      return;
    }

    setSubmitting(true);
    try {
      // Apply the new password. Works identically for a freshly-invited user
      // (who has a random password they never knew) and a forgot-password user.
      await confirmPasswordReset(auth, oobCode, password);
      toast.success(t("action.success"));
      navigate({ to: "/auth/login" });
    } catch (err) {
      const code = err instanceof FirebaseError ? err.code : "";
      if (code === "auth/weak-password") {
        // Weak password is a field-level problem: keep the form, show it inline.
        setFieldError(authErrorMessage(t, code));
      } else if (code === "auth/expired-action-code" || code === "auth/invalid-action-code") {
        // The code expired/was consumed between verify and submit: fall back to
        // the whole-page re-request message.
        setVerify({ status: "invalid" });
        toast.error(authErrorMessage(t, code));
      } else {
        const message = authErrorMessage(t, code);
        setFieldError(message);
        toast.error(message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper2 px-6">
      <div className="w-full max-w-md border border-ink bg-paper p-10">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink/60">Agenic × Nestor</p>
        <h1 className="mt-3 font-serif text-3xl font-normal lowercase tracking-tight text-ink">
          {t("action.heading")}
        </h1>

        {verify.status === "verifying" && (
          <p className="mt-8 text-sm text-ink/60">{t("action.verifying")}</p>
        )}

        {verify.status === "unsupported" && (
          <div className="mt-8 space-y-4">
            <p className="text-sm text-ink/70">{t("action.unsupported")}</p>
            <a
              href="/auth/login"
              className="inline-block font-mono text-xs uppercase tracking-wider text-ink underline"
            >
              {t("action.toLogin")}
            </a>
          </div>
        )}

        {verify.status === "invalid" && (
          <div className="mt-8 space-y-4">
            <p className="text-sm text-red-600">{t("action.errors.expiredLink")}</p>
            <a
              href="/auth/login"
              className="inline-block font-mono text-xs uppercase tracking-wider text-ink underline"
            >
              {t("action.toLogin")}
            </a>
          </div>
        )}

        {verify.status === "ready" && (
          <>
            <p className="mt-3 text-sm text-ink/60">
              {t("action.setPasswordFor")}{" "}
              <span className="font-mono text-ink">{verify.email}</span>.
            </p>
            <form onSubmit={handleSubmit} className="mt-8 space-y-4">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t("action.newPasswordPlaceholder")}
                autoComplete="new-password"
                required
                autoFocus
                className="w-full border border-ink/20 bg-paper px-4 py-3 text-sm outline-none focus:border-ink"
              />
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder={t("action.confirmPasswordPlaceholder")}
                autoComplete="new-password"
                required
                className="w-full border border-ink/20 bg-paper px-4 py-3 text-sm outline-none focus:border-ink"
              />
              <button
                type="submit"
                disabled={submitting}
                className="w-full bg-ink px-4 py-3 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-50"
              >
                {submitting ? t("action.submitting") : t("action.submit")}
              </button>
            </form>
            {fieldError && <p className="mt-4 text-sm text-red-600">{fieldError}</p>}
          </>
        )}
      </div>
    </div>
  );
}
