// Product feature flags. These gate whole features on/off at the product level
// (not per-user preferences — those live in Settings).

/**
 * Show Idaten's race-time prediction (the range chip on the races card, Today
 * countdown, and Trends "Race outlook").
 *
 * OFF for now: until an athlete has actually raced, Idaten's number is just
 * Garmin's number relabelled, so surfacing it as a second "prediction" only
 * duplicates what the Garmin app already shows and confuses. The backend keeps
 * computing and CALIBRATING it silently (k learns from real races), so flipping
 * this back on later — once the prediction genuinely beats Garmin — is a one-line
 * change with history already accrued. Set NEXT_PUBLIC_SHOW_RACE_PREDICTION=true
 * to enable.
 */
export const SHOW_RACE_PREDICTION = process.env.NEXT_PUBLIC_SHOW_RACE_PREDICTION === "true";
