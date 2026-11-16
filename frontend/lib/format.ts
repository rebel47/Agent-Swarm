export function money(value: number) {
  return new Intl.NumberFormat("en-US", {style: "currency", currency: "USD",
    minimumFractionDigits: 2, maximumFractionDigits: value > 0 && value < 0.01 ? 4 : 2}).format(value);
}
export function elapsed(seconds: number) {
  if (seconds < 60) return Math.max(0, seconds) + "s";
  return Math.floor(seconds / 60) + "m " + seconds % 60 + "s";
}
export function repositoryName(location: string) {
  return location.split(" @ ")[0].replace(/\.git$/, "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || location;
}
export function statusLabel(status: string) {
  return ({RUNNING: "In progress", COMPLETED: "Completed", FAILED: "Failed", CANCELLED: "Cancelled",
    TIMED_OUT: "Timed out", QUEUED: "Queued", CREATED: "Starting", WAITING_FOR_CHILDREN: "Waiting for team"} as Record<string, string>)[status] || status;
}
export function dateLabel(value: number) {
  return new Date(value * 1000).toLocaleDateString(undefined, {month: "short", day: "numeric"});
}
