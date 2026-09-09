import { useTranslation } from "react-i18next";
import { TraceSection } from "@/components/research/ResearchTrace";

/**
 * The three honest readings of an empty feed, IN THE SECTION SHELL.
 *
 * One generic "no events" message would collapse three genuinely different situations into a
 * shrug:
 *
 *  - QUEUED: the run has been accepted but the engine has not picked it up yet, so it has no
 *    engine id and no events could exist. This is the COLD-OPEN window an operator lands in
 *    the instant they click through from the trigger — the page must read as "not started",
 *    not as "broken" and not as an error.
 *  - ACTIVE: the engine is working and the first event has not arrived (or a long poll is in
 *    flight, which is silence that is NOT a stall — the withdrawn-D-C lesson: on 2026-07-27
 *    exactly this silence was misread as a hang on a run that was fine).
 *  - TERMINAL: the run finished and left no history. For a run that predates 15.3 that is
 *    simply the truth, and saying so beats an empty page that looks like a failed load.
 *
 * It lives in its own file rather than inside the route so that "an empty run is ALREADY the
 * new design" is a testable claim — the route file cannot be imported under the node-env
 * suite without dragging the router in with it.
 *
 * `title` is passed in, not derived. The run's status vocabulary has exactly one home
 * (`statusLabel` in the route) and a second copy of it here would be a second thing to forget
 * to update when a ninth status arrives.
 */
export function EmptyFeed({
  status,
  isTerminal,
  title,
}: {
  status: string;
  isTerminal: boolean;
  title: string;
}) {
  const { t } = useTranslation("intake");
  const message = isTerminal
    ? t("research.runPage.feed.emptyTerminal")
    : status === "queued"
      ? t("research.runPage.feed.emptyQueued")
      : t("research.runPage.feed.emptyActive");
  return (
    // A QUEUED run is not live — the engine has not picked it up. A non-terminal run that is
    // not queued is working, and the badge says so even before its first event lands.
    <TraceSection title={title} active={!isTerminal && status !== "queued"} eventCount={0}>
      <p className="px-4 py-8 font-sans text-sm leading-relaxed text-ink/60 sm:px-5">{message}</p>
    </TraceSection>
  );
}
